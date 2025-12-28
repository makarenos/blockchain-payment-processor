# tests/test_withdrawals.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from app.models.user import Balance
from datetime import datetime


class TestWithdrawalAPI:
    """Test withdrawal API endpoints"""

    def test_request_withdrawal_success(self, client: TestClient, auth_headers,
                                        test_user, db):
        """Test successful withdrawal request"""
        # Ensure user has sufficient balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 1000.0
        db.commit()

        request_data = {
            "amount": 100.0,
            "wallet_address": "TDestination123456789012345678901"
        }

        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            mock_fee.return_value = 5.0  # 5 USDT fee

            response = client.post("/api/withdrawals/request",
                                   json=request_data, headers=auth_headers)
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "success"
            assert data["operation"] == "withdrawal_requested"

            withdrawal_data = data["data"]
            assert withdrawal_data["amount"] == 100.0
            assert withdrawal_data["fee_amount"] == 5.0
            assert withdrawal_data["total_deducted"] == 105.0
            assert withdrawal_data["wallet_address"] == request_data[
                "wallet_address"]
            assert withdrawal_data["status"] == "requested"
            assert withdrawal_data["remaining_balance"] == 895.0  # 1000 - 105

    def test_request_withdrawal_insufficient_balance(self, client: TestClient,
                                                     auth_headers, test_user,
                                                     db):
        """Test withdrawal request with insufficient balance"""
        # Set low balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 50.0
        db.commit()

        request_data = {
            "amount": 100.0,
            "wallet_address": "TDestination123456789012345678901"
        }

        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            mock_fee.return_value = 5.0

            response = client.post("/api/withdrawals/request",
                                   json=request_data, headers=auth_headers)
            assert response.status_code == 400
            assert "Insufficient balance" in response.json()["detail"]

    def test_request_withdrawal_amount_too_small(self, client: TestClient,
                                                 auth_headers):
        """Test withdrawal request with amount below minimum"""
        request_data = {
            "amount": 2.0,  # Below minimum (5.0)
            "wallet_address": "TDestination123456789012345678901"
        }

        response = client.post("/api/withdrawals/request", json=request_data,
                               headers=auth_headers)
        assert response.status_code == 400
        assert "Amount must be between" in response.json()["detail"]

    def test_request_withdrawal_amount_too_large(self, client: TestClient,
                                                 auth_headers):
        """Test withdrawal request with amount above maximum"""
        request_data = {
            "amount": 10000.0,  # Above maximum (5000.0)
            "wallet_address": "TDestination123456789012345678901"
        }

        response = client.post("/api/withdrawals/request", json=request_data,
                               headers=auth_headers)
        assert response.status_code == 400
        assert "Amount must be between" in response.json()["detail"]

    def test_request_withdrawal_invalid_address(self, client: TestClient,
                                                auth_headers):
        """Test withdrawal request with invalid wallet address"""
        invalid_addresses = [
            "invalid",  # Too short
            "TInvalid",  # Too short
            "BInvalidAddress12345678901234567890",  # Wrong prefix
            "TInvalidAddress123456789012345678901234567890",  # Too long
            "",  # Empty
        ]

        for address in invalid_addresses:
            request_data = {
                "amount": 100.0,
                "wallet_address": address
            }

            response = client.post("/api/withdrawals/request",
                                   json=request_data, headers=auth_headers)
            assert response.status_code == 400
            assert "Invalid TRC20 wallet address format" in response.json()[
                "detail"]

    def test_request_withdrawal_unauthorized(self, client: TestClient):
        """Test withdrawal request without authentication"""
        request_data = {
            "amount": 100.0,
            "wallet_address": "TDestination123456789012345678901"
        }

        response = client.post("/api/withdrawals/request", json=request_data)
        assert response.status_code == 401

    def test_get_user_withdrawals_empty(self, client: TestClient,
                                        auth_headers):
        """Test getting withdrawals when user has no withdrawals"""
        response = client.get("/api/withdrawals/", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["withdrawals"] == []
        assert data["data"]["count"] == 0

    def test_get_user_withdrawals_with_data(self, client: TestClient,
                                            auth_headers,
                                            test_withdrawal_transaction):
        """Test getting user withdrawals when withdrawals exist"""
        response = client.get("/api/withdrawals/", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert len(data["data"]["withdrawals"]) == 1

        withdrawal = data["data"]["withdrawals"][0]
        assert withdrawal["id"] == test_withdrawal_transaction.id
        assert withdrawal["amount"] == test_withdrawal_transaction.amount
        assert withdrawal["status"] == "requested"
        assert withdrawal[
                   "wallet_address"] == test_withdrawal_transaction.wallet_address

    def test_get_user_withdrawals_pagination(self, client: TestClient,
                                             auth_headers, test_user, db):
        """Test withdrawals pagination"""
        # Create multiple withdrawal transactions
        for i in range(12):
            transaction = Transaction(
                user_id=test_user.id,
                amount=50.0 + i,
                transaction_type=TransactionTypeEnum.withdrawal,
                withdrawal_status=WithdrawalStatusEnum.requested,
                wallet_address=f"TDest{i:029d}",
                comment=f"Test withdrawal {i}"
            )
            db.add(transaction)
        db.commit()

        # Test first page
        response = client.get("/api/withdrawals/?limit=10&offset=0",
                              headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]["withdrawals"]) == 10
        assert data["data"]["offset"] == 0

        # Test second page
        response = client.get("/api/withdrawals/?limit=10&offset=10",
                              headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]["withdrawals"]) == 2

    def test_cancel_withdrawal_success(self, client: TestClient, auth_headers,
                                       test_user, db):
        """Test successful withdrawal cancellation"""
        # Create withdrawal transaction
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested,
            wallet_address="TDestination123456789012345678901",
            comment="Test withdrawal"
        )
        db.add(transaction)
        db.commit()

        # Set initial balance (should be low since withdrawal deducted amount)
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        original_balance = balance.amount

        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            mock_fee.return_value = 5.0

            response = client.post(f"/api/withdrawals/{transaction.id}/cancel",
                                   headers=auth_headers)
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "success"
            assert data["data"]["transaction_id"] == transaction.id
            assert data["data"]["refunded_amount"] == 105.0  # 100 + 5 fee

            # Check transaction status updated
            db.refresh(transaction)
            assert transaction.withdrawal_status == WithdrawalStatusEnum.cancelled
            assert transaction.comment == "Cancelled by user"

            # Check balance refunded
            db.refresh(balance)
            assert balance.amount == original_balance + 105.0

    def test_cancel_withdrawal_not_found(self, client: TestClient,
                                         auth_headers):
        """Test cancelling non-existent withdrawal"""
        response = client.post("/api/withdrawals/999999/cancel",
                               headers=auth_headers)
        assert response.status_code == 404
        assert "Withdrawal not found" in response.json()["detail"]

    def test_cancel_withdrawal_wrong_status(self, client: TestClient,
                                            auth_headers, test_user, db):
        """Test cancelling withdrawal with wrong status"""
        # Create completed withdrawal
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.completed,
            wallet_address="TDestination123456789012345678901"
        )
        db.add(transaction)
        db.commit()

        response = client.post(f"/api/withdrawals/{transaction.id}/cancel",
                               headers=auth_headers)
        assert response.status_code == 400
        assert "Cannot cancel withdrawal with status" in response.json()[
            "detail"]

    def test_cancel_other_user_withdrawal(self, client: TestClient,
                                          auth_headers, admin_user, db):
        """Test that user cannot cancel another user's withdrawal"""
        # Create withdrawal for admin user
        transaction = Transaction(
            user_id=admin_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested,
            wallet_address="TDestination123456789012345678901"
        )
        db.add(transaction)
        db.commit()

        response = client.post(f"/api/withdrawals/{transaction.id}/cancel",
                               headers=auth_headers)
        assert response.status_code == 404  # Should not find withdrawal for this user

    def test_get_withdrawals_unauthorized(self, client: TestClient):
        """Test getting withdrawals without authentication"""
        response = client.get("/api/withdrawals/")
        assert response.status_code == 401


class TestWithdrawalValidation:
    """Test withdrawal request validation"""

    def test_withdrawal_amount_validation(self, client: TestClient,
                                          auth_headers, test_user, db):
        """Test various amount validation scenarios"""
        # Set high balance to avoid balance issues
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 10000.0
        db.commit()

        test_cases = [
            (0, 422),  # Zero amount
            (-10, 422),  # Negative amount
            (2.0, 400),  # Below minimum (5.0)
            (6000, 400),  # Above maximum (5000.0)
            (50, 200),  # Valid amount
        ]

        for amount, expected_status in test_cases:
            with patch(
                    'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
                mock_fee.return_value = 2.0

                with patch(
                        'app.services.status_sync.hook_transaction_status_changed'):
                    request_data = {
                        "amount": amount,
                        "wallet_address": "TDestination123456789012345678901"
                    }
                    response = client.post("/api/withdrawals/request",
                                           json=request_data,
                                           headers=auth_headers)
                    assert response.status_code == expected_status

    def test_withdrawal_address_validation(self, client: TestClient,
                                           auth_headers, test_user, db):
        """Test wallet address validation"""
        # Set sufficient balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 1000.0
        db.commit()

        valid_addresses = [
            "TDestination123456789012345678901",
            "T1234567890123456789012345678901234",
            "TXYZ567890123456789012345678901234"
        ]

        invalid_addresses = [
            "short",  # Too short
            "BDestination12345678901234567890123456",  # Wrong prefix
            "TDestination1234567890123456789012345678901234567890",  # Too long
            "TDestination12345678901234567890!",  # Invalid characters
            "",  # Empty
        ]

        # Test valid addresses
        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            mock_fee.return_value = 5.0

            with patch(
                    'app.services.status_sync.hook_transaction_status_changed'):
                for address in valid_addresses:
                    request_data = {
                        "amount": 50.0,
                        "wallet_address": address
                    }
                    response = client.post("/api/withdrawals/request",
                                           json=request_data,
                                           headers=auth_headers)
                    assert response.status_code == 200

        # Test invalid addresses
        for address in invalid_addresses:
            request_data = {
                "amount": 50.0,
                "wallet_address": address
            }
            response = client.post("/api/withdrawals/request",
                                   json=request_data, headers=auth_headers)
            assert response.status_code == 400


class TestWithdrawalIntegration:
    """Integration tests for withdrawal flow"""

    def test_full_withdrawal_request_flow(self, client: TestClient,
                                          auth_headers, test_user, db):
        """Test complete withdrawal request flow"""
        # Setup sufficient balance
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        initial_balance = 1000.0
        balance.amount = initial_balance
        db.commit()

        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            with patch(
                    'app.services.status_sync.hook_transaction_status_changed') as mock_sync:
                mock_fee.return_value = 10.0
                mock_sync.return_value = {"changed": True}

                # Request withdrawal
                request_data = {
                    "amount": 200.0,
                    "wallet_address": "TDestination123456789012345678901"
                }
                response = client.post("/api/withdrawals/request",
                                       json=request_data, headers=auth_headers)

                assert response.status_code == 200
                data = response.json()
                transaction_id = data["data"]["transaction_id"]

                # Verify transaction in database
                transaction = db.query(Transaction).filter(
                    Transaction.id == transaction_id).first()
                assert transaction is not None
                assert transaction.amount == 200.0
                assert transaction.transaction_type == TransactionTypeEnum.withdrawal
                assert transaction.withdrawal_status == WithdrawalStatusEnum.requested
                assert transaction.wallet_address == request_data[
                    "wallet_address"]
                assert transaction.user_id == test_user.id

                # Verify balance deducted
                db.refresh(balance)
                expected_balance = initial_balance - 200.0 - 10.0  # amount + fee
                assert balance.amount == expected_balance

                # Verify status sync was called
                mock_sync.assert_called_once()

    def test_withdrawal_balance_deduction(self, client: TestClient,
                                          auth_headers, test_user, db):
        """Test that withdrawal properly deducts balance"""
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 500.0
        db.commit()

        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            with patch(
                    'app.services.status_sync.hook_transaction_status_changed'):
                mock_fee.return_value = 8.0

                request_data = {
                    "amount": 100.0,
                    "wallet_address": "TDestination123456789012345678901"
                }

                response = client.post("/api/withdrawals/request",
                                       json=request_data, headers=auth_headers)
                assert response.status_code == 200

                # Check balance deducted
                db.refresh(balance)
                assert balance.amount == 392.0  # 500 - 100 - 8

    def test_withdrawal_cancellation_flow(self, client: TestClient,
                                          auth_headers, test_user, db):
        """Test complete withdrawal cancellation flow"""
        # Create withdrawal
        transaction = Transaction(
            user_id=test_user.id,
            amount=150.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.pending,
            wallet_address="TDestination123456789012345678901"
        )
        db.add(transaction)

        # Set balance (as if amount was already deducted)
        balance = db.query(Balance).filter(
            Balance.user_id == test_user.id).first()
        balance.amount = 500.0  # Simulated post-withdrawal balance
        db.commit()

        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            with patch(
                    'app.services.status_sync.hook_transaction_status_changed') as mock_sync:
                mock_fee.return_value = 7.5
                mock_sync.return_value = {"changed": True}

                # Cancel withdrawal
                response = client.post(
                    f"/api/withdrawals/{transaction.id}/cancel",
                    headers=auth_headers)
                assert response.status_code == 200

                # Verify transaction updated
                db.refresh(transaction)
                assert transaction.withdrawal_status == WithdrawalStatusEnum.cancelled
                assert transaction.processed_at is not None
                assert transaction.comment == "Cancelled by user"

                # Verify balance refunded
                db.refresh(balance)
                assert balance.amount == 657.5  # 500 + 150 + 7.5

                # Verify status sync was called
                mock_sync.assert_called_once()