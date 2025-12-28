# app/api/withdrawals.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.core.database import get_db
from app.core.core_auth import get_current_user
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum, TransactionPurposeEnum
from app.services.status_sync import hook_transaction_status_changed
from app.api.utils import handle_operation_errors, create_success_response, \
    validate_address_format
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/request")
@handle_operation_errors("request withdrawal")
async def request_withdrawal(
        amount: float,
        wallet_address: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Request withdrawal to external wallet"""

    # Validate amount
    if amount < settings.MIN_WITHDRAWAL_AMOUNT or amount > settings.MAX_WITHDRAWAL_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount must be between {settings.MIN_WITHDRAWAL_AMOUNT} and {settings.MAX_WITHDRAWAL_AMOUNT} USDT"
        )

    # Validate address
    if not validate_address_format(wallet_address, "TRC20"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TRC20 wallet address format"
        )

    # Check user balance
    user_balance = db.query(Balance).filter(
        Balance.user_id == current_user.id).first()
    if not user_balance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User balance not found"
        )

    # Calculate fees
    fee_amount = settings.calculate_withdrawal_fee(amount)
    total_required = amount + fee_amount

    if user_balance.amount < total_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Required: {total_required} USDT (amount: {amount} + fee: {fee_amount}), available: {user_balance.amount}"
        )

    # Create withdrawal transaction
    transaction = Transaction(
        user_id=current_user.id,
        amount=amount,
        transaction_type=TransactionTypeEnum.withdrawal,
        withdrawal_status=WithdrawalStatusEnum.requested,
        payment_method="USDT (TRC20)",
        wallet_address=wallet_address,
        transaction_purpose=TransactionPurposeEnum.regular,
        comment=f"Withdrawal request to {wallet_address}"
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    # Deduct amount from balance (including fees)
    user_balance.amount -= total_required
    db.commit()

    # Sync user status
    sync_result = hook_transaction_status_changed(
        db, transaction.id, "withdrawal_request"
    )

    logger.info(
        f"Withdrawal created: ID={transaction.id}, user={current_user.id}, amount={amount}, fee={fee_amount}")

    return create_success_response("withdrawal_requested", {
        "transaction_id": transaction.id,
        "amount": amount,
        "fee_amount": fee_amount,
        "total_deducted": total_required,
        "wallet_address": wallet_address,
        "status": "requested",
        "remaining_balance": user_balance.amount,
        "message": "Withdrawal request submitted for review",
        "sync_result": sync_result
    }, current_user.id)


@router.get("")
@handle_operation_errors("get user withdrawals")
async def get_user_withdrawals(
        limit: int = 10,
        offset: int = 0,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Get user's withdrawal history"""

    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type == TransactionTypeEnum.withdrawal
    ).order_by(Transaction.created_at.desc()).offset(offset).limit(limit).all()

    withdrawals = []
    for tx in transactions:
        withdrawals.append({
            "id": tx.id,
            "amount": tx.amount,
            "status": tx.withdrawal_status.value if tx.withdrawal_status else "pending",
            "wallet_address": tx.wallet_address,
            "txid": tx.txid,
            "created_at": tx.created_at.isoformat(),
            "processed_at": tx.processed_at.isoformat() if tx.processed_at else None,
            "comment": tx.comment,
            "purpose": tx.transaction_purpose.value if tx.transaction_purpose else "regular"
        })

    return create_success_response("user_withdrawals", {
        "withdrawals": withdrawals,
        "count": len(withdrawals),
        "offset": offset,
        "limit": limit
    }, current_user.id)


@router.post("/{transaction_id}/cancel")
@handle_operation_errors("cancel withdrawal")
async def cancel_withdrawal(
        transaction_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Cancel pending withdrawal"""

    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id,
        Transaction.transaction_type == TransactionTypeEnum.withdrawal
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Withdrawal not found"
        )

    if transaction.withdrawal_status not in [WithdrawalStatusEnum.requested,
                                             WithdrawalStatusEnum.pending]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel withdrawal with status: {transaction.withdrawal_status.value}"
        )

    # Cancel transaction
    transaction.withdrawal_status = WithdrawalStatusEnum.cancelled
    transaction.processed_at = datetime.utcnow()
    transaction.comment = "Cancelled by user"

    # Refund amount to balance
    user_balance = db.query(Balance).filter(
        Balance.user_id == current_user.id).first()
    if user_balance:
        fee_amount = settings.calculate_withdrawal_fee(transaction.amount)
        refund_amount = transaction.amount + fee_amount
        user_balance.amount += refund_amount

    db.commit()

    # Sync user status
    sync_result = hook_transaction_status_changed(
        db, transaction.id, "withdrawal_cancellation"
    )

    logger.info(
        f"Withdrawal cancelled: ID={transaction.id}, user={current_user.id}")

    return create_success_response("withdrawal_cancelled", {
        "transaction_id": transaction.id,
        "refunded_amount": refund_amount if user_balance else transaction.amount,
        "new_balance": user_balance.amount if user_balance else "unknown",
        "message": "Withdrawal cancelled and amount refunded",
        "sync_result": sync_result
    }, current_user.id)