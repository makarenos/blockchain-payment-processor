# app/services/webhook_handlers.py

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import Request, BackgroundTasks, HTTPException, status
from typing import Dict, Any
from app.models.transaction import Transaction, WithdrawalStatusEnum
from app.models.user import User
from app.core.config import settings

logger = logging.getLogger(__name__)


class WebhookHandlers:
    """Service for processing payment and blockchain webhooks"""

    @staticmethod
    async def handle_payment_webhook(
            request: Request,
            background_tasks: BackgroundTasks,
            db: Session
    ) -> Dict[str, Any]:
        """Handle payment system webhook"""
        try:
            payload = await request.json()
            logger.info(f"Received payment webhook: {payload}")

            transaction_id = payload.get("transaction_id")
            payment_status = payload.get("status")

            if not transaction_id:
                logger.error("Missing transaction_id in webhook payload")
                return {"status": "error", "reason": "Missing transaction_id"}

            transaction = db.query(Transaction).filter(
                Transaction.id == transaction_id
            ).first()

            if not transaction:
                logger.error(f"Transaction {transaction_id} not found")
                return {"status": "error", "reason": "Transaction not found"}

            user = db.query(User).filter(
                User.id == transaction.user_id).first()
            if not user:
                logger.error(f"User {transaction.user_id} not found")
                return {"status": "error", "reason": "User not found"}

            if payment_status == "success":
                transaction.withdrawal_status = WithdrawalStatusEnum.completed
                transaction.processed_at = datetime.utcnow()
                transaction.comment = f"Подтверждено платежной системой: {transaction_id}"
                db.commit()

                logger.info(
                    f"Transaction {transaction.id} confirmed via webhook")

                # Sync user status
                from app.services.status_sync import hook_transaction_completed
                sync_result = hook_transaction_completed(db, transaction.id,
                                                         "payment_webhook")

                logger.info(f"User status sync result: {sync_result}")

                return {
                    "status": "success",
                    "transaction_id": transaction.id,
                    "user_id": user.id,
                    "withdrawal_status": transaction.withdrawal_status.value,
                    "sync_result": sync_result
                }

            elif payment_status == "failed":
                transaction.withdrawal_status = WithdrawalStatusEnum.rejected
                transaction.comment = f"Отклонено платежной системой: {transaction_id}"
                db.commit()

                logger.info(
                    f"Transaction {transaction.id} marked as rejected via webhook")

                return {
                    "status": "processed",
                    "transaction_id": transaction.id,
                    "user_id": user.id,
                    "withdrawal_status": transaction.withdrawal_status.value
                }
            else:
                logger.warning(f"Unsupported payment status: {payment_status}")
                return {"status": "error",
                        "reason": f"Unsupported payment status: {payment_status}"}

        except Exception as e:
            logger.exception(f"Error processing webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing webhook: {str(e)}"
            )

    @staticmethod
    async def handle_blockchain_webhook(
            request: Request,
            background_tasks: BackgroundTasks,
            db: Session
    ) -> Dict[str, Any]:
        """Handle blockchain confirmation webhook"""
        try:
            payload = await request.json()
            logger.info(f"Received blockchain webhook: {payload}")

            event_type = payload.get("event_type")
            if event_type != "transaction_confirmed":
                logger.info(
                    f"Ignoring blockchain webhook with event type: {event_type}")
                return {"status": "ignored",
                        "reason": f"Unsupported event type: {event_type}"}

            txid = payload.get("txid")
            confirmations = payload.get("confirmations", 0)
            address = payload.get("address")
            amount = payload.get("amount")
            token = payload.get("token")

            required_confirmations = settings.current_confirmations_required
            if confirmations < required_confirmations:
                logger.info(
                    f"Not enough confirmations: {confirmations}/{required_confirmations}")
                return {
                    "status": "pending",
                    "txid": txid,
                    "confirmations": confirmations,
                    "required_confirmations": required_confirmations
                }

            # Find transaction by address and amount
            transaction = db.query(Transaction).filter(
                Transaction.wallet_address == address,
                Transaction.amount == amount,
                Transaction.withdrawal_status == WithdrawalStatusEnum.pending
            ).first()

            if not transaction:
                logger.warning(
                    f"No matching transaction found for address {address}, amount {amount}")
                return {"status": "no_match", "address": address,
                        "amount": amount}

            # Update transaction
            transaction.withdrawal_status = WithdrawalStatusEnum.completed
            transaction.processed_at = datetime.utcnow()
            transaction.txid = txid
            transaction.comment = f"Blockchain confirmed: {confirmations} confirmations"
            db.commit()

            logger.info(
                f"Transaction {transaction.id} confirmed via blockchain webhook")

            # Auto-complete if enabled
            if settings.auto_complete_enabled:
                from app.services.status_sync import hook_transaction_completed
                sync_result = hook_transaction_completed(db, transaction.id,
                                                         "blockchain_webhook")

                logger.info(f"Auto-completion sync result: {sync_result}")

                return {
                    "status": "auto_completed",
                    "transaction_id": transaction.id,
                    "confirmations": confirmations,
                    "auto_sync_result": sync_result
                }
            else:
                return {
                    "status": "confirmed",
                    "transaction_id": transaction.id,
                    "confirmations": confirmations,
                    "note": "Auto-completion disabled, manual review required"
                }

        except Exception as e:
            logger.exception(f"Error processing blockchain webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing blockchain webhook: {str(e)}"
            )