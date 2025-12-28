# app/api/admin.py

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.core_auth import get_current_admin_user
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from app.models.wallet import WalletAddress, AddressReservation, \
    AddressStatusEnum
from app.services.address_pool import AddressPoolService
from app.services.status_sync import hook_transaction_completed, \
    UnifiedStatusSyncService
from app.api.utils import (
    handle_operation_errors,
    create_success_response,
    validate_admin_rights,
    log_admin_operation,
    ensure_atomic_operation
)
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# Transaction Management
@router.get("/transactions")
@handle_operation_errors("get all transactions")
async def get_all_transactions(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        transaction_type: Optional[TransactionTypeEnum] = None,
        status: Optional[WithdrawalStatusEnum] = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_admin_user)
):
    """Get all transactions with filtering"""
    validate_admin_rights(db, current_user.id)

    query = db.query(Transaction).join(User)

    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)

    if status:
        query = query.filter(Transaction.withdrawal_status == status)

    transactions = query.order_by(Transaction.created_at.desc()).offset(
        offset).limit(limit).all()

    transaction_list = []
    for tx in transactions:
        user = tx.user
        transaction_list.append({
            "id": tx.id,
            "user_id": tx.user_id,
            "username": user.username if user else "unknown",
            "amount": tx.amount,
            "type": tx.transaction_type.value,
            "status": tx.withdrawal_status.value if tx.withdrawal_status else "pending",
            "purpose": tx.transaction_purpose.value if tx.transaction_purpose else "regular",
            "wallet_address": tx.wallet_address,
            "txid": tx.txid,
            "created_at": tx.created_at.isoformat(),
            "processed_at": tx.processed_at.isoformat() if tx.processed_at else None,
            "comment": tx.comment
        })

    return create_success_response("all_transactions", {
        "transactions": transaction_list,
        "count": len(transaction_list),
        "offset": offset,
        "limit": limit,
        "filters": {
            "type": transaction_type.value if transaction_type else None,
            "status": status.value if status else None
        }
    }, current_user.id)


@router.post("/deposits/{transaction_id}/approve")
@handle_operation_errors("approve deposit")
@ensure_atomic_operation
async def approve_deposit(
        transaction_id: int,
        comment: Optional[str] = Body(None),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_admin_user)
):
    """Approve deposit and credit user balance"""
    validate_admin_rights(db, current_user.id)

    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.transaction_type == TransactionTypeEnum.deposit
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deposit not found"
        )

    if transaction.withdrawal_status == WithdrawalStatusEnum.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deposit already approved"
        )

    # Update transaction
    transaction.withdrawal_status = WithdrawalStatusEnum.completed
    transaction.processed_at = datetime.utcnow()
    transaction.comment = comment or f"Approved by admin {current_user.id}"

    # Credit user balance
    user_balance = db.query(Balance).filter(
        Balance.user_id == transaction.user_id).first()
    if not user_balance:
        user_balance = Balance(user_id=transaction.user_id, amount=0.0)
        db.add(user_balance)

    user_balance.amount += transaction.amount

    # Release address back to pool
    if transaction.wallet_address:
        address_record = db.query(WalletAddress).filter(
            WalletAddress.address == transaction.wallet_address
        ).first()

        if address_record:
            AddressPoolService.release_address_atomic(
                db, address_record.id, transaction_id=transaction.id
            )

    db.commit()

    # Sync user status
    sync_result = hook_transaction_completed(
        db, transaction.id, "admin_approval"
    )

    log_admin_operation("approve_deposit", current_user.id, {
        "transaction_id": transaction_id,
        "amount": transaction.amount,
        "user_id": transaction.user_id
    })

    return create_success_response("deposit_approved", {
        "transaction_id": transaction_id,
        "amount": transaction.amount,
        "user_id": transaction.user_id,
        "new_balance": user_balance.amount,
        "sync_result": sync_result,
        "message": f"Deposit of {transaction.amount} USDT approved and credited"
    }, current_user.id)


@router.post("/withdrawals/{transaction_id}/approve")
@handle_operation_errors("approve withdrawal")
@ensure_atomic_operation
async def approve_withdrawal(
        transaction_id: int,
        comment: Optional[str] = Body(None),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_admin_user)
):
    """Approve withdrawal for processing"""
    validate_admin_rights(db, current_user.id)

    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.transaction_type == TransactionTypeEnum.withdrawal
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Withdrawal not found"
        )

    if transaction.withdrawal_status != WithdrawalStatusEnum.requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve withdrawal with status: {transaction.withdrawal_status.value}"
        )

    # Update transaction
    transaction.withdrawal_status = WithdrawalStatusEnum.approved
    transaction.comment = comment or f"Approved by admin {current_user.id}"
    db.commit()

    # Sync user status
    sync_result = hook_transaction_completed(
        db, transaction.id, "admin_approval"
    )

    log_admin_operation("approve_withdrawal", current_user.id, {
        "transaction_id": transaction_id,
        "amount": transaction.amount,
        "user_id": transaction.user_id,
        "wallet_address": transaction.wallet_address
    })

    return create_success_response("withdrawal_approved", {
        "transaction_id": transaction_id,
        "amount": transaction.amount,
        "wallet_address": transaction.wallet_address,
        "status": "approved",
        "sync_result": sync_result,
        "message": f"Withdrawal of {transaction.amount} USDT approved for processing"
    }, current_user.id)


# Pool Management
@router.get("/pool/status")
@handle_operation_errors("get pool status")
async def get_pool_status(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_admin_user)
):
    """Get address pool status and health"""
    validate_admin_rights(db, current_user.id)

    pool_status = AddressPoolService.get_pool_status(db)

    return create_success_response("pool_status", pool_status, current_user.id)


@router.post("/pool/add-addresses")
@handle_operation_errors("add addresses to pool")
async def add_addresses_to_pool(
        addresses: List[str] = Body(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_admin_user)
):
    """Add new addresses to the pool"""
    validate_admin_rights(db, current_user.id)

    result = AddressPoolService.add_addresses_to_pool_atomic(db, addresses)

    log_admin_operation("add_addresses_to_pool", current_user.id, {
        "addresses_count": len(addresses),
        "result": result
    })

    return create_success_response("addresses_added", result, current_user.id)