# app/api/deposits.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.core_auth import get_current_user
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum, TransactionPurposeEnum
from app.models.wallet import WalletAddress, AddressReservation
from app.services.address_pool import AddressPoolService
from app.api.utils import handle_operation_errors, create_success_response
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/request")
@handle_operation_errors("request deposit address")
async def request_deposit_address(
        amount: float,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Request deposit address for USDT payment"""

    # Validate amount
    if amount < settings.MIN_DEPOSIT_AMOUNT or amount > settings.MAX_DEPOSIT_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount must be between {settings.MIN_DEPOSIT_AMOUNT} and {settings.MAX_DEPOSIT_AMOUNT} USDT"
        )

    # Get address from pool
    reservation_minutes = settings.ADDRESS_RESERVATION_MINUTES
    wallet_address = AddressPoolService.get_available_address_with_retry(
        db, current_user.id, reservation_minutes
    )

    if not wallet_address:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No addresses available. Please try again later."
        )

    # Create transaction
    transaction_dict = {
        "amount": amount,
        "transaction_type": TransactionTypeEnum.deposit,
        "withdrawal_status": WithdrawalStatusEnum.pending,
        "payment_method": "USDT (TRC20)",
        "wallet_address": wallet_address.address,
        "transaction_purpose": TransactionPurposeEnum.regular,
        "comment": "Deposit address assigned"
    }

    transaction = Transaction(
        user_id=current_user.id,
        **transaction_dict
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    # Link address to transaction
    AddressPoolService.assign_address_to_transaction_atomic(
        db, transaction.id, wallet_address.id
    )

    logger.info(
        f"Deposit created: ID={transaction.id}, user={current_user.id}, amount={amount}")

    return create_success_response("deposit_address_assigned", {
        "transaction_id": transaction.id,
        "deposit_address": wallet_address.address,
        "amount": amount,
        "network": "TRC-20",
        "status": "pending",
        "expires_at": (datetime.utcnow() + timedelta(
            minutes=reservation_minutes)).isoformat(),
        "message": f"Send {amount} USDT to {wallet_address.address}",
        "note": "Deposit will be credited after blockchain confirmation"
    }, current_user.id)


@router.get("")
@handle_operation_errors("get user deposits")
async def get_user_deposits(
        limit: int = 10,
        offset: int = 0,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Get user's deposit history"""

    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type == TransactionTypeEnum.deposit
    ).order_by(Transaction.created_at.desc()).offset(offset).limit(limit).all()

    deposits = []
    for tx in transactions:
        deposits.append({
            "id": tx.id,
            "amount": tx.amount,
            "status": tx.withdrawal_status.value if tx.withdrawal_status else "pending",
            "address": tx.wallet_address,
            "txid": tx.txid,
            "created_at": tx.created_at.isoformat(),
            "processed_at": tx.processed_at.isoformat() if tx.processed_at else None,
            "comment": tx.comment
        })

    return create_success_response("user_deposits", {
        "deposits": deposits,
        "count": len(deposits),
        "offset": offset,
        "limit": limit
    }, current_user.id)