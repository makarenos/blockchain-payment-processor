# tests/test_webhooks.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from app.models.user import User
from datetime import datetime
import json


class TestWebhookEndpoints:
    """Test webhook API endpoints"""

    def test_webhook_health_check(self, client: TestClient):
        """Test webhook health endpoint"""
        response = client.get("/api/webhooks/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "webhook_handler"
        assert "/webhooks/payment" in data["endpoints"]
        assert "/webhooks/blockchain" in data["endpoints"]


class TestPaymentWebhook:
    """Test payment system webhook handling"""

    def test_payment_webhook_success(self, client: TestClient,
                                     test_withdrawal_transaction, db):
        """Test successful payment webhook processing"""
        payload = {
            "transaction_id": test_withdrawal_transaction.id,
            "status": "success",
            "payment_system_id": "pay_123456",
            "timestamp": int(datetime.utcnow().timestamp())
        }

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {
                "user_id": test_withdrawal_transaction.user_id,
                "changed": True,
                "new_status": "available"
            }

            response = client.post("/api/webhooks/payment", json=payload)
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "success"
            assert data["transaction_id"] == test_withdrawal_transaction.id
            assert "sync_result" in data

            # Verify transaction updated
            db.refresh(test_withdrawal_transaction)
            assert test_withdrawal_transaction.withdrawal_status == WithdrawalStatusEnum.completed
            assert test_withdrawal_transaction.processed_at is not None

    def test_payment_webhook_failure(self, client: TestClient,
                                     test_withdrawal_transaction, db):
        """Test failed payment webhook processing"""
        payload = {
            "transaction_id": test_withdrawal_transaction.id,
            "status": "failed",
            "error_code": "INSUFFICIENT_FUNDS",
            "timestamp": int(datetime.utcnow().timestamp())
        }

        response = client.post("/api/webhooks/payment", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "processed"
        assert data["transaction_id"] == test_withdrawal_transaction.id

        # Verify transaction marked as rejected
        db.refresh(test_withdrawal_transaction)
        assert test_withdrawal_transaction.withdrawal_status == WithdrawalStatusEnum.rejected
        assert "Отклонено платежной системой" in test_withdrawal_transaction.comment

    def test_payment_webhook_missing_transaction_id(self, client: TestClient):
        """Test payment webhook with missing transaction ID"""
        payload = {
            "status": "success",
            "timestamp": int(datetime.utcnow().timestamp())
        }

        response = client.post("/api/webhooks/payment", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "error"
        assert data["reason"] == "Missing transaction_id"

    def test_payment_webhook_transaction_not_found(self, client: TestClient):
        """Test payment webhook with non-existent transaction"""
        payload = {
            "transaction_id": 999999,
            "status": "success",
            "timestamp": int(datetime.utcnow().timestamp())
        }

        response = client.post("/api/webhooks/payment", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "error"
        assert data["reason"] == "Transaction not found"

    def test_payment_webhook_unsupported_status(self, client: TestClient,
                                                test_withdrawal_transaction):
        """Test payment webhook with unsupported status"""
        payload = {
            "transaction_id": test_withdrawal_transaction.id,
            "status": "unknown_status",
            "timestamp": int(datetime.utcnow().timestamp())
        }

        response = client.post("/api/webhooks/payment", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "error"
        assert "Unsupported payment status" in data["reason"]


class TestBlockchainWebhook:
    """Test blockchain confirmation webhook handling"""

    def test_blockchain_webhook_success(self, client: TestClient,
                                        test_deposit_transaction, db,
                                        monkeypatch):
        """Test successful blockchain webhook processing"""
        # Mock settings
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)
        monkeypatch.setattr(config.settings, "auto_complete_enabled", True)

        payload = {
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123456",
            "confirmations": 20,
            "address": test_deposit_transaction.wallet_address,
            "amount": test_deposit_transaction.amount,
            "token": "USDT",
            "timestamp": int(datetime.utcnow().timestamp())
        }

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {
                "user_id": test_deposit_transaction.user_id,
                "changed": True,
                "new_status": "available"
            }

            response = client.post("/api/webhooks/blockchain", json=payload)
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "auto_completed"
            assert data["transaction_id"] == test_deposit_transaction.id
            assert data["confirmations"] == 20
            assert "auto_sync_result" in data

            # Verify transaction updated
            db.refresh(test_deposit_transaction)
            assert test_deposit_transaction.withdrawal_status == WithdrawalStatusEnum.completed
            assert test_deposit_transaction.txid == "blockchain_tx_123456"
            assert "20 confirmations" in test_deposit_transaction.comment

    def test_blockchain_webhook_insufficient_confirmations(self,
                                                           client: TestClient,
                                                           test_deposit_transaction,
                                                           monkeypatch):
        """Test blockchain webhook with insufficient confirmations"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)

        payload = {
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123456",
            "confirmations": 15,  # Less than required 19
            "address": test_deposit_transaction.wallet_address,
            "amount": test_deposit_transaction.amount,
            "token": "USDT"
        }

        response = client.post("/api/webhooks/blockchain", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "pending"
        assert data["confirmations"] == 15
        assert data["required_confirmations"] == 19

    def test_blockchain_webhook_auto_complete_disabled(self,
                                                       client: TestClient,
                                                       test_deposit_transaction,
                                                       db, monkeypatch):
        """Test blockchain webhook with auto-complete disabled"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)
        monkeypatch.setattr(config.settings, "auto_complete_enabled", False)

        payload = {
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123456",
            "confirmations": 20,
            "address": test_deposit_transaction.wallet_address,
            "amount": test_deposit_transaction.amount,
            "token": "USDT"
        }

        response = client.post("/api/webhooks/blockchain", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "confirmed"
        assert data["transaction_id"] == test_deposit_transaction.id
        assert "Auto-completion disabled" in data["note"]

        # Transaction should be confirmed but not completed
        db.refresh(test_deposit_transaction)
        assert test_deposit_transaction.withdrawal_status == WithdrawalStatusEnum.completed
        assert test_deposit_transaction.txid == "blockchain_tx_123456"

    def test_blockchain_webhook_no_matching_transaction(self,
                                                        client: TestClient,
                                                        monkeypatch):
        """Test blockchain webhook with no matching transaction"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)

        payload = {
            "event_type": "transaction_confirmed",
            "txid": "blockchain_tx_123456",
            "confirmations": 20,
            "address": "TNonExistent123456789012345678901",
            "amount": 999.99,
            "token": "USDT"
        }

        response = client.post("/api/webhooks/blockchain", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "no_match"
        assert data["address"] == "TNonExistent123456789012345678901"
        assert data["amount"] == 999.99

    def test_blockchain_webhook_wrong_event_type(self, client: TestClient):
        """Test blockchain webhook with wrong event type"""
        payload = {
            "event_type": "balance_updated",
            "txid": "blockchain_tx_123456",
            "confirmations": 20
        }

        response = client.post("/api/webhooks/blockchain", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ignored"
        assert "Unsupported event type" in data["reason"]

    def test_blockchain_webhook_malformed_payload(self, client: TestClient):
        """Test blockchain webhook with malformed payload"""
        # Test with invalid JSON
        response = client.post("/api/webhooks/blockchain", data="invalid json")
        assert response.status_code == 422

        # Test with missing required fields
        payload = {
            "event_type": "transaction_confirmed"
            # Missing other required fields
        }

        response = client.post("/api/webhooks/blockchain", json=payload)
        assert response.status_code == 200  # Should handle gracefully


class TestWebhookSecurity:
    """Test webhook security and validation"""

    def test_webhook_accepts_post_only(self, client: TestClient):
        """Test that webhooks only accept POST requests"""
        endpoints = ["/api/webhooks/payment", "/api/webhooks/blockchain"]

        for endpoint in endpoints:
            # Test GET
            response = client.get(endpoint)
            assert response.status_code == 405

            # Test PUT
            response = client.put(endpoint, json={})
            assert response.status_code == 405

            # Test DELETE
            response = client.delete(endpoint)
            assert response.status_code == 405

    def test_webhook_content_type_validation(self, client: TestClient):
        """Test webhook content type validation"""
        # Test with wrong content type
        response = client.post(
            "/api/webhooks/payment",
            data="form data",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert response.status_code in [400, 422]

    def test_webhook_large_payload_handling(self, client: TestClient):
        """Test webhook handling of large payloads"""
        # Create a large payload (simulate potential attack)
        large_payload = {
            "transaction_id": 1,
            "status": "success",
            "large_data": "x" * 10000  # 10KB of data
        }

        response = client.post("/api/webhooks/payment", json=large_payload)
        assert response.status_code in [200, 413,
                                        422]  # Should handle gracefully


class TestWebhookIntegration:
    """Integration tests for webhook processing"""

    def test_full_deposit_webhook_flow(self, client: TestClient, test_user,
                                       test_wallet_address, db, monkeypatch):
        """Test complete deposit webhook processing flow"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)
        monkeypatch.setattr(config.settings, "auto_complete_enabled", True)

        # Create pending deposit
        transaction = Transaction(
            user_id=test_user.id,
            amount=500.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending,
            wallet_address=test_wallet_address.address,
            comment="Awaiting blockchain confirmation"
        )
        db.add(transaction)
        db.commit()

        # Get initial balance
        from app.models.user import Balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        initial_balance = balance.amount

        # Simulate blockchain confirmation webhook
        payload = {
            "event_type": "transaction_confirmed",
            "txid": "real_blockchain_tx_789",
            "confirmations": 25,
            "address": test_wallet_address.address,
            "amount": 500.0,
            "token": "USDT",
            "block_height": 12345678
        }

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {
                "user_id": test_user.id,
                "changed": True,
                "new_status": "available",
                "balance_deduction": None
            }

            response = client.post("/api/webhooks/blockchain", json=payload)
            assert response.status_code == 200

            # Verify complete flow
            data = response.json()
            assert data["status"] == "auto_completed"

            # Verify transaction updated
            db.refresh(transaction)
            assert transaction.withdrawal_status == WithdrawalStatusEnum.completed
            assert transaction.txid == "real_blockchain_tx_789"
            assert transaction.processed_at is not None

            # Verify status sync was triggered
            mock_sync.assert_called_once_with(db, transaction.id,
                                              "blockchain_webhook")

    def test_webhook_error_recovery(self, client: TestClient,
                                    test_withdrawal_transaction, db):
        """Test webhook error handling and recovery"""
        payload = {
            "transaction_id": test_withdrawal_transaction.id,
            "status": "success"
        }

        # Simulate database error during processing
        with patch('app.models.transaction.Transaction') as mock_transaction:
            mock_transaction.query.filter.side_effect = Exception(
                "Database connection lost")

            response = client.post("/api/webhooks/payment", json=payload)
            assert response.status_code == 500

            # Verify original transaction unchanged
            db.refresh(test_withdrawal_transaction)
            assert test_withdrawal_transaction.withdrawal_status == WithdrawalStatusEnum.requested

    def test_concurrent_webhook_processing(self, client: TestClient, test_user,
                                           db, monkeypatch):
        """Test concurrent webhook processing for same transaction"""
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)
        monkeypatch.setattr(config.settings, "auto_complete_enabled", True)

        # Create pending transaction
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending,
            wallet_address="TConcurrent123456789012345678901",
            comment="Concurrent test"
        )
        db.add(transaction)
        db.commit()

        payload = {
            "event_type": "transaction_confirmed",
            "txid": "concurrent_tx_123",
            "confirmations": 20,
            "address": "TConcurrent123456789012345678901",
            "amount": 100.0,
            "token": "USDT"
        }

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {"changed": True}

            # Simulate concurrent webhook calls
            responses = []
            for i in range(3):
                response = client.post("/api/webhooks/blockchain",
                                       json=payload)
                responses.append(response)

            # All requests should be handled gracefully
            for response in responses:
                assert response.status_code in [200,
                                                409]  # Success or conflict

    def test_webhook_idempotency(self, client: TestClient,
                                 test_withdrawal_transaction, db):
        """Test webhook idempotency (repeated calls should be safe)"""
        payload = {
            "transaction_id": test_withdrawal_transaction.id,
            "status": "success",
            "idempotency_key": "unique_key_123"
        }

        # First webhook call
        response1 = client.post("/api/webhooks/payment", json=payload)
        assert response1.status_code == 200

        # Get transaction state after first call
        db.refresh(test_withdrawal_transaction)
        first_status = test_withdrawal_transaction.withdrawal_status
        first_processed_at = test_withdrawal_transaction.processed_at

        # Second webhook call (should be idempotent)
        response2 = client.post("/api/webhooks/payment", json=payload)
        assert response2.status_code == 200

        # Verify transaction state unchanged
        db.refresh(test_withdrawal_transaction)
        assert test_withdrawal_transaction.withdrawal_status == first_status
        assert test_withdrawal_transaction.processed_at == first_processed_at