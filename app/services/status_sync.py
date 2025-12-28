# app/services/status_sync.py

from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import Optional, Dict, Any
from app.core.config import settings
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum, TransactionPurposeEnum
import logging

logger = logging.getLogger(__name__)


class UnifiedStatusSyncService:
    """Unified service for synchronizing transaction and user statuses"""

    ACTIVE_REGULAR_WITHDRAWAL_STATUSES = [
        WithdrawalStatusEnum.requested,
        WithdrawalStatusEnum.pending,
        WithdrawalStatusEnum.approved
    ]

    @staticmethod
    def sync_user_status_on_transaction_change(
            db: Session,
            transaction_id: int,
            source: str = "unknown"
    ) -> Dict[str, Any]:
        """Main function - automatically syncs user status on any transaction change"""
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id).first()

        if not transaction:
            return {"error": "Transaction not found",
                    "transaction_id": transaction_id}

        user = db.query(User).filter(User.id == transaction.user_id).first()
        if not user:
            return {"error": "User not found", "user_id": transaction.user_id}

        logger.info(
            f"Syncing user {user.id} status triggered by transaction {transaction_id} from {source}")

        # Check balance deduction on tax_payment completion
        balance_deduction_result = None
        if (
                transaction.transaction_purpose == TransactionPurposeEnum.tax_payment and
                transaction.withdrawal_status == WithdrawalStatusEnum.completed):
            logger.info(
                f"tax_payment {transaction_id} completed - checking balance deduction")
            balance_deduction_result = UnifiedStatusSyncService._deduct_balance_on_tax_completion(
                db, user.id)

        old_status = getattr(user, 'user_withdrawal_status', None)
        new_status = UnifiedStatusSyncService._calculate_correct_user_status(
            db, user.id)

        if old_status != new_status:
            if hasattr(user, 'user_withdrawal_status'):
                user.user_withdrawal_status = new_status
            db.commit()

            logger.info(
                f"User {user.id} status changed: {old_status} -> {new_status}")

            return {
                "user_id": user.id,
                "transaction_id": transaction_id,
                "old_status": old_status.value if old_status else None,
                "new_status": new_status.value if new_status else None,
                "changed": True,
                "source": source,
                "balance_deduction": balance_deduction_result,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "user_id": user.id,
                "transaction_id": transaction_id,
                "current_status": old_status.value if old_status else None,
                "changed": False,
                "source": source,
                "balance_deduction": balance_deduction_result,
                "message": "Status is already correct",
                "timestamp": datetime.utcnow().isoformat()
            }

    @staticmethod
    def _calculate_correct_user_status(db: Session, user_id: int):
        """Calculate what the user's status should be based on transactions"""
        # Check for active withdrawal requests
        active_withdrawal = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionTypeEnum.withdrawal,
            Transaction.withdrawal_status.in_(
                UnifiedStatusSyncService.ACTIVE_REGULAR_WITHDRAWAL_STATUSES)
        ).first()

        if active_withdrawal:
            # Determine status based on withdrawal purpose and status
            if active_withdrawal.transaction_purpose == TransactionPurposeEnum.regular:
                if active_withdrawal.withdrawal_status == WithdrawalStatusEnum.requested:
                    return "regular_withdrawal_requested"
                elif active_withdrawal.withdrawal_status == WithdrawalStatusEnum.approved:
                    return "regular_withdrawal_approved"

            return "withdrawal_in_progress"

        # Default status
        return "available"

    @staticmethod
    def _deduct_balance_on_tax_completion(db: Session, user_id: int) -> Dict[
        str, Any]:
        """Deduct balance when tax payment is completed"""
        try:
            user_balance = db.query(Balance).filter(
                Balance.user_id == user_id).first()
            if not user_balance:
                return {"error": "User balance not found"}

            # Find the tax transaction
            tax_transaction = db.query(Transaction).filter(
                Transaction.user_id == user_id,
                Transaction.transaction_purpose == TransactionPurposeEnum.tax_payment,
                Transaction.withdrawal_status == WithdrawalStatusEnum.completed
            ).order_by(Transaction.processed_at.desc()).first()

            if not tax_transaction:
                return {"error": "Tax transaction not found"}

            tax_amount = tax_transaction.amount

            if user_balance.amount >= tax_amount:
                user_balance.amount -= tax_amount
                db.commit()

                logger.info(
                    f"Deducted {tax_amount} from user {user_id} balance for tax payment")

                return {
                    "success": True,
                    "deducted_amount": tax_amount,
                    "remaining_balance": user_balance.amount,
                    "transaction_id": tax_transaction.id
                }
            else:
                logger.warning(
                    f"Insufficient balance for tax deduction: has {user_balance.amount}, needs {tax_amount}")
                return {
                    "error": "Insufficient balance",
                    "required": tax_amount,
                    "available": user_balance.amount
                }

        except Exception as e:
            logger.error(f"Error deducting balance on tax completion: {e}")
            return {"error": str(e)}

    @staticmethod
    def force_sync_user_status(db: Session, user_id: int) -> Dict[str, Any]:
        """Force synchronization of user status"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        old_status = getattr(user, 'user_withdrawal_status', None)
        correct_status = UnifiedStatusSyncService._calculate_correct_user_status(
            db, user_id)

        if old_status != correct_status:
            if hasattr(user, 'user_withdrawal_status'):
                user.user_withdrawal_status = correct_status
            db.commit()

            logger.info(
                f"User {user_id} status forced: {old_status} -> {correct_status}")

            return {
                "user_id": user_id,
                "old_status": old_status.value if old_status else None,
                "new_status": correct_status.value if correct_status else None,
                "changed": True,
                "method": "force_sync",
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "user_id": user_id,
                "current_status": old_status.value if old_status else None,
                "changed": False,
                "method": "force_sync",
                "message": "Status is already correct",
                "timestamp": datetime.utcnow().isoformat()
            }

    @staticmethod
    def sync_all_users_status(db: Session) -> Dict[str, Any]:
        """Mass synchronization of all user statuses"""
        logger.info("Starting mass synchronization of all user statuses")

        users = db.query(User).all()
        synced_users = []
        changed_count = 0

        for user in users:
            try:
                old_status = getattr(user, 'user_withdrawal_status', None)
                correct_status = UnifiedStatusSyncService._calculate_correct_user_status(
                    db, user.id)

                if old_status != correct_status:
                    if hasattr(user, 'user_withdrawal_status'):
                        user.user_withdrawal_status = correct_status
                    changed_count += 1

                    synced_users.append({
                        "user_id": user.id,
                        "old_status": old_status.value if old_status else None,
                        "new_status": correct_status.value if correct_status else None
                    })

                    logger.info(
                        f"User {user.id}: {old_status} -> {correct_status}")

            except Exception as e:
                logger.error(f"Error syncing user {user.id}: {e}")

        if changed_count > 0:
            db.commit()

        logger.info(
            f"Mass sync completed: {changed_count}/{len(users)} users updated")

        return {
            "total_users": len(users),
            "changed_users": changed_count,
            "synced_users": synced_users[:10],
            "timestamp": datetime.utcnow().isoformat()
        }


# Integration hooks for existing code
def hook_transaction_status_changed(db: Session, transaction_id: int,
                                    source: str = "unknown"):
    """Hook - call this function everywhere transaction status changes"""
    try:
        result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
            db, transaction_id, source)
        if result.get("changed"):
            logger.info(f"User status synced: {result}")
        return result
    except Exception as e:
        logger.error(
            f"Failed to sync user status for transaction {transaction_id}: {e}")
        return {"error": str(e)}


def hook_transaction_completed(db: Session, transaction_id: int,
                               completion_method: str = "unknown"):
    """Hook - call when any transaction is completed"""
    return hook_transaction_status_changed(db, transaction_id,
                                           f"completion_via_{completion_method}")


def hook_webhook_processed(db: Session, transaction_id: int,
                           webhook_type: str = "unknown"):
    """Hook - call when webhook is processed"""
    return hook_transaction_status_changed(db, transaction_id,
                                           f"webhook_{webhook_type}")