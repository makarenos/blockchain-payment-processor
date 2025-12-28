# tests/test_services.py

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from app.services.status_sync import UnifiedStatusSyncService
from app.services.webhook_handlers import WebhookHandlers
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum, TransactionPurposeEnum
from app.models.wallet import WalletAddress, AddressStatusEnum


class TestUnifiedStatusSyncService:
    """Test status synchronization service"""

    def test_calculate_correct_user_status_available(self, db, test_user):
        """Test calculating user status when user has no active withdrawals"""
        # No active withdrawals - should be available
        status = UnifiedStatusSyncService._calculate_correct_user_status(db,
                                                                         test_user.id)
        assert status == "available"

    def test_calculate_correct_user_status_withdrawal_requested(self, db,
                                                                test_user):
        """Test calculating user status with requested withdrawal"""
        # Create requested withdrawal
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested,
            transaction_purpose=TransactionPurposeEnum.regular
        )
        db.add(transaction)
        db.commit()

        status = UnifiedStatusSyncService._calculate_correct_user_status(db,
                                                                         test_user.id)
        assert status == "regular_withdrawal_requested"

    def test_calculate_correct_user_status_withdrawal_approved(self, db,
                                                               test_user):
        """Test calculating user status with approved withdrawal"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.approved,
            transaction_purpose=TransactionPurposeEnum.regular
        )
        db.add(transaction)
        db.commit()

        status = UnifiedStatusSyncService._calculate_correct_user_status(db,
                                                                         test_user.id)
        assert status == "regular_withdrawal_approved"

    def test_calculate_correct_user_status_withdrawal_in_progress(self, db,
                                                                  test_user):
        """Test calculating user status with non-regular withdrawal"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.pending,
            transaction_purpose=TransactionPurposeEnum.system_withdrawal
        )
        db.add(transaction)
        db.commit()

        status = UnifiedStatusSyncService._calculate_correct_user_status(db,
                                                                         test_user.id)
        assert status == "withdrawal_in_progress"

    def test_sync_user_status_on_transaction_change_no_change(self, db,
                                                              test_user,
                                                              test_deposit_transaction):
        """Test status sync when no change is needed"""
        # Mock user with correct status
        with patch.object(test_user, 'user_withdrawal_status', "available"):
            result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
                db, test_deposit_transaction.id, "test"
            )

            assert result["changed"] is False
            assert result["message"] == "Status is already correct"

    def test_sync_user_status_on_transaction_change_with_change(self, db,
                                                                test_user):
        """Test status sync when change is needed"""
        # Create a transaction that would change status
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested,
            transaction_purpose=TransactionPurposeEnum.regular
        )
        db.add(transaction)
        db.commit()

        # Mock user with wrong status
        with patch.object(test_user, 'user_withdrawal_status', "available"):
            with patch.object(User, 'user_withdrawal_status',
                              new="available") as mock_status:
                result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
                    db, transaction.id, "test"
                )

                assert result["changed"] is True
                assert result["old_status"] == "available"
                assert result["new_status"] == "regular_withdrawal_requested"

    def test_deduct_balance_on_tax_completion_success(self, db, test_user):
        """Test successful balance deduction on tax completion"""
        # Create tax transaction
        tax_transaction = Transaction(
            user_id=test_user.id,
            amount=50.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.completed,
            transaction_purpose=TransactionPurposeEnum.tax_payment,
            processed_at=datetime.utcnow()
        )
        db.add(tax_transaction)

        # Set user balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 500.0
        db.commit()

        result = UnifiedStatusSyncService._deduct_balance_on_tax_completion(db,
                                                                            test_user.id)

        assert result["success"] is True
        assert result["deducted_amount"] == 50.0
        assert result["remaining_balance"] == 450.0

        # Verify balance was actually deducted
        db.refresh(balance)
        assert balance.amount == 450.0

    def test_deduct_balance_on_tax_completion_insufficient_balance(self, db,
                                                                   test_user):
        """Test tax deduction with insufficient balance"""
        # Create tax transaction
        tax_transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.completed,
            transaction_purpose=TransactionPurposeEnum.tax_payment,
            processed_at=datetime.utcnow()
        )
        db.add(tax_transaction)

        # Set insufficient balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 50.0  # Less than tax amount
        db.commit()

        result = UnifiedStatusSyncService._deduct_balance_on_tax_completion(db,
                                                                            test_user.id)

        assert "error" in result
        assert result["error"] == "Insufficient balance"
        assert result["required"] == 100.0
        assert result["available"] == 50.0

    def test_force_sync_user_status(self, db, test_user):
        """Test forcing user status synchronization"""
        # Create withdrawal that should change status
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.approved,
            transaction_purpose=TransactionPurposeEnum.regular
        )
        db.add(transaction)
        db.commit()

        # Mock user with wrong status
        with patch.object(test_user, 'user_withdrawal_status', "available"):
            result = UnifiedStatusSyncService.force_sync_user_status(db,
                                                                     test_user.id)

            assert result["changed"] is True
            assert result["old_status"] == "available"
            assert result["new_status"] == "regular_withdrawal_approved"
            assert result["method"] == "force_sync"

    def test_sync_all_users_status(self, db, test_user, admin_user):
        """Test mass synchronization of all user statuses"""
        # Create transactions that should change statuses
        user_transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested,
            transaction_purpose=TransactionPurposeEnum.regular
        )

        admin_transaction = Transaction(
            user_id=admin_user.id,
            amount=200.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.approved,
            transaction_purpose=TransactionPurposeEnum.regular
        )

        db.add_all([user_transaction, admin_transaction])
        db.commit()

        # Mock users with wrong statuses
        with patch.object(User, 'user_withdrawal_status', new="available"):
            result = UnifiedStatusSyncService.sync_all_users_status(db)

            assert result["total_users"] >= 2
            assert result["changed_users"] >= 2
            assert len(result["synced_users"]) >= 2


class TestWebhookHandlers:
    """Test webhook handling service"""

    @pytest.mark.asyncio
    async def test_handle_payment_webhook_success(self, db,
                                                  test_withdrawal_transaction):
        """Test successful payment webhook handling"""
        # Mock request with success payload
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "transaction_id": test_withdrawal_transaction.id,
            "status": "success",
            "payment_id": "pay_123"
        })

        mock_background_tasks = MagicMock()

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {"changed": True}

            result = await WebhookHandlers.handle_payment_webhook(
                mock_request, mock_background_tasks, db
            )

            assert result["status"] == "success"
            assert result["transaction_id"] == test_withdrawal_transaction.id
            assert "sync_result" in result

            # Verify transaction was updated
            db.refresh(test_withdrawal_transaction)
            assert test_withdrawal_transaction.withdrawal_status == WithdrawalStatusEnum.completed
            assert test_withdrawal_transaction.processed_at is not None

    @pytest.mark.asyncio
    async def test_handle_payment_webhook_failure(self, db,
                                                  test_withdrawal_transaction):
        """Test failed payment webhook handling"""
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "transaction_id": test_withdrawal_transaction.id,
            "status": "failed",
            "error_code": "DECLINED"
        })

        mock_background_tasks = MagicMock()

        result = await WebhookHandlers.handle_payment_webhook(
            mock_request, mock_background_tasks, db
        )

        assert result["status"] == "processed"
        assert result["transaction_id"] == test_withdrawal_transaction.id

        # Verify transaction was marked as rejected
        db.refresh(test_withdrawal_transaction)
        assert test_withdrawal_transaction.withdrawal_status == WithdrawalStatusEnum.rejected

    @pytest.mark.asyncio
    async def test_handle_payment_webhook_missing_transaction_id(self, db):
        """Test payment webhook with missing transaction ID"""
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "status": "success"
            # Missing transaction_id
        })

        mock_background_tasks = MagicMock()

        result = await WebhookHandlers.handle_payment_webhook(
            mock_request, mock_background_tasks, db
        )

        assert result["status"] == "error"
        assert result["reason"] == "Missing transaction_id"

    @pytest.mark.asyncio
    async def test_handle_blockchain_webhook_success(self, db,
                                                     test_deposit_transaction,
                                                     monkeypatch):
        """Test successful blockchain webhook handling"""
        # Mock settings
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)
        monkeypatch.setattr(config.settings, "auto_complete_enabled", True)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123",
            "confirmations": 20,
            "address": test_deposit_transaction.wallet_address,
            "amount": test_deposit_transaction.amount,
            "token": "USDT"
        })

        mock_background_tasks = MagicMock()

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {"changed": True}

            result = await WebhookHandlers.handle_blockchain_webhook(
                mock_request, mock_background_tasks, db
            )

            assert result["status"] == "auto_completed"
            assert result["transaction_id"] == test_deposit_transaction.id
            assert result["confirmations"] == 20

            # Verify transaction was updated
            db.refresh(test_deposit_transaction)
            assert test_deposit_transaction.withdrawal_status == WithdrawalStatusEnum.completed
            assert test_deposit_transaction.txid == "blockchain_tx_123"

    @pytest.mark.asyncio
    async def test_handle_blockchain_webhook_insufficient_confirmations(self,
                                                                        db,
                                                                        test_deposit_transaction,
                                                                        monkeypatch):
        """Test blockchain webhook with insufficient confirmations"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123",
            "confirmations": 15,  # Less than required
            "address": test_deposit_transaction.wallet_address,
            "amount": test_deposit_transaction.amount,
            "token": "USDT"
        })

        mock_background_tasks = MagicMock()

        result = await WebhookHandlers.handle_blockchain_webhook(
            mock_request, mock_background_tasks, db
        )

        assert result["status"] == "pending"
        assert result["confirmations"] == 15
        assert result["required_confirmations"] == 19

        # Verify transaction was NOT updated
        db.refresh(test_deposit_transaction)
        assert test_deposit_transaction.withdrawal_status == WithdrawalStatusEnum.pending
        assert test_deposit_transaction.txid is None

    @pytest.mark.asyncio
    async def test_handle_blockchain_webhook_no_matching_transaction(self, db,
                                                                     monkeypatch):
        """Test blockchain webhook with no matching transaction"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123",
            "confirmations": 20,
            "address": "TNonExistent123456789012345678901",
            "amount": 999.99,
            "token": "USDT"
        })

        mock_background_tasks = MagicMock()

        result = await WebhookHandlers.handle_blockchain_webhook(
            mock_request, mock_background_tasks, db
        )

        assert result["status"] == "no_match"
        assert result["address"] == "TNonExistent123456789012345678901"
        assert result["amount"] == 999.99

    @pytest.mark.asyncio
    async def test_handle_blockchain_webhook_wrong_event_type(self, db):
        """Test blockchain webhook with unsupported event type"""
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "event_type": "balance_updated",
            "txid": "blockchain_tx_123"
        })

        mock_background_tasks = MagicMock()

        result = await WebhookHandlers.handle_blockchain_webhook(
            mock_request, mock_background_tasks, db
        )

        assert result["status"] == "ignored"
        assert "Unsupported event type" in result["reason"]


class TestServiceIntegration:
    """Integration tests for service interactions"""

    def test_webhook_triggers_status_sync(self, db,
                                          test_withdrawal_transaction):
        """Test that webhook processing triggers status synchronization"""
        # Mock webhook success that should trigger status sync
        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {
                "user_id": test_withdrawal_transaction.user_id,
                "changed": True,
                "old_status": "withdrawal_in_progress",
                "new_status": "available"
            }

            # Simulate webhook completion
            test_withdrawal_transaction.withdrawal_status = WithdrawalStatusEnum.completed
            test_withdrawal_transaction.processed_at = datetime.utcnow()
            db.commit()

            # Trigger sync
            result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
                db, test_withdrawal_transaction.id, "webhook_test"
            )

            assert result["changed"] is True
            assert result["source"] == "webhook_test"

    def test_tax_payment_triggers_balance_deduction(self, db, test_user):
        """Test that tax payment completion triggers balance deduction"""
        # Set initial balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 1000.0
        db.commit()

        # Create and complete tax payment
        tax_transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.completed,
            transaction_purpose=TransactionPurposeEnum.tax_payment,
            processed_at=datetime.utcnow()
        )
        db.add(tax_transaction)
        db.commit()

        # Trigger status sync (should include balance deduction)
        result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
            db, tax_transaction.id, "tax_completion"
        )

        assert "balance_deduction" in result
        assert result["balance_deduction"]["success"] is True
        assert result["balance_deduction"]["deducted_amount"] == 100.0

        # Verify balance was deducted
        db.refresh(balance)
        assert balance.amount == 900.0

    def test_concurrent_status_sync(self, db, test_user):
        """Test concurrent status synchronization operations"""
        # Create multiple transactions
        transactions = []
        for i in range(3):
            tx = Transaction(
                user_id=test_user.id,
                amount=50.0 + i * 10,
                transaction_type=TransactionTypeEnum.withdrawal,
                withdrawal_status=WithdrawalStatusEnum.requested,
                transaction_purpose=TransactionPurposeEnum.regular
            )
            db.add(tx)
            transactions.append(tx)
        db.commit()

        # Simulate concurrent sync operations
        results = []
        for tx in transactions:
            result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
                db, tx.id, f"concurrent_test_{tx.id}"
            )
            results.append(result)

        # All should succeed and produce consistent results
        for result in results:
            assert "error" not in result
            assert result["user_id"] == test_user.id

    def test_service_error_handling(self, db):
        """Test service error handling with invalid data"""
        # Test status sync with non-existent transaction
        result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
            db, 999999, "error_test"
        )

        assert "error" in result
        assert result["error"] == "Transaction not found"
        assert result["transaction_id"] == 999999

        # Test force sync with non-existent user
        with pytest.raises(Exception):  # Should raise HTTPException
            UnifiedStatusSyncService.force_sync_user_status(db, 999999)


class TestServicePerformance:
    """Test service performance and optimization"""

    def test_bulk_status_sync_performance(self, db):
        """Test performance of bulk status synchronization"""
        import time

        # Create multiple users with transactions
        users = []
        for i in range(10):
            user = User(
                username=f"perf_user_{i}",
                password_hash="dummy_hash",
                email=f"perf_{i}@example.com",
                is_active=True
            )
            db.add(user)
            users.append(user)

        db.commit()

        # Create transactions for each user
        for user in users:
            balance = Balance(user_id=user.id, amount=1000.0)
            db.add(balance)

            tx = Transaction(
                user_id=user.id,
                amount=100.0,
                transaction_type=TransactionTypeEnum.withdrawal,
                withdrawal_status=WithdrawalStatusEnum.requested,
                transaction_purpose=TransactionPurposeEnum.regular
            )
            db.add(tx)

        db.commit()

        # Time bulk sync operation
        start_time = time.time()
        result = UnifiedStatusSyncService.sync_all_users_status(db)
        end_time = time.time()

        # Should complete reasonably quickly (< 1 second for 10 users)
        assert (end_time - start_time) < 1.0
        assert result["total_users"] >= 10
        assert result["changed_users"] >= 10

    def test_individual_sync_performance(self, db, test_user):
        """Test performance of individual status synchronization"""
        import time

        # Create transaction
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.approved,
            transaction_purpose=TransactionPurposeEnum.regular
        )
        db.add(transaction)
        db.commit()

        # Time individual sync
        start_time = time.time()
        result = UnifiedStatusSyncService.sync_user_status_on_transaction_change(
            db, transaction.id, "performance_test"
        )
        end_time = time.time()

        # Should complete very quickly (< 0.1 seconds)
        assert (end_time - start_time) < 0.1
        assert "error" not in result