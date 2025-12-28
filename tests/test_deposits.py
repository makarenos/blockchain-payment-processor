# tests/test_deposits.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.models.wallet import WalletAddress, AddressStatusEnum, \
    AddressReservation
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from datetime import datetime, timedelta


class TestDepositAPI:
    """Test deposit API endpoints"""

    def test_request_deposit_address_success(self, client: TestClient,
                                             auth_headers, test_wallet_address,
                                             db):
        """Test successful deposit address request"""
        request_data = {"amount": 100.0}

        response = client.post("/api/deposits/request", json=request_data,
                               headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["operation"] == "deposit_address_assigned"

        deposit_data = data["data"]
        assert deposit_data["amount"] == 100.0
        assert deposit_data["network"] == "TRC-20"
        assert deposit_data["status"] == "pending"
        assert "deposit_address" in deposit_data
        assert "transaction_id" in deposit_data
        assert "expires_at" in deposit_data

    def test_request_deposit_amount_too_small(self, client: TestClient,
                                              auth_headers):
        """Test deposit request with amount too small"""
        request_data = {"amount": 0.5}  # Below minimum

        response = client.post("/api/deposits/request", json=request_data,
                               headers=auth_headers)
        assert response.status_code == 400
        assert "Amount must be between" in response.json()["detail"]

    def test_request_deposit_amount_too_large(self, client: TestClient,
                                              auth_headers):
        """Test deposit request with amount too large"""
        request_data = {"amount": 50000.0}  # Above maximum

        response = client.post("/api/deposits/request", json=request_data,
                               headers=auth_headers)
        assert response.status_code == 400
        assert "Amount must be between" in response.json()["detail"]

    def test_request_deposit_no_addresses_available(self, client: TestClient,
                                                    auth_headers, db):
        """Test deposit request when no addresses are available"""
        # Remove all addresses from pool
        db.query(WalletAddress).delete()
        db.commit()

        request_data = {"amount": 100.0}

        with patch(
                'app.services.address_pool.AddressPoolService.get_available_address_with_retry') as mock_get_address:
            mock_get_address.return_value = None

            response = client.post("/api/deposits/request", json=request_data,
                                   headers=auth_headers)
            assert response.status_code == 503
            assert "No addresses available" in response.json()["detail"]

    def test_request_deposit_unauthorized(self, client: TestClient):
        """Test deposit request without authentication"""
        request_data = {"amount": 100.0}

        response = client.post("/api/deposits/request", json=request_data)
        assert response.status_code == 401

    def test_get_user_deposits_empty(self, client: TestClient, auth_headers):
        """Test getting deposits when user has no deposits"""
        response = client.get("/api/deposits/", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["deposits"] == []
        assert data["data"]["count"] == 0

    def test_get_user_deposits_with_data(self, client: TestClient,
                                         auth_headers,
                                         test_deposit_transaction):
        """Test getting user deposits when deposits exist"""
        response = client.get("/api/deposits/", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert len(data["data"]["deposits"]) == 1

        deposit = data["data"]["deposits"][0]
        assert deposit["id"] == test_deposit_transaction.id
        assert deposit["amount"] == test_deposit_transaction.amount
        assert deposit["status"] == "pending"
        assert deposit["address"] == test_deposit_transaction.wallet_address

    def test_get_user_deposits_pagination(self, client: TestClient,
                                          auth_headers, test_user, db):
        """Test deposits pagination"""
        # Create multiple deposit transactions
        for i in range(15):
            transaction = Transaction(
                user_id=test_user.id,
                amount=100.0 + i,
                transaction_type=TransactionTypeEnum.deposit,
                withdrawal_status=WithdrawalStatusEnum.pending,
                wallet_address=f"TTest{i:030d}",
                comment=f"Test deposit {i}"
            )
            db.add(transaction)
        db.commit()

        # Test first page
        response = client.get("/api/deposits/?limit=10&offset=0",
                              headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]["deposits"]) == 10
        assert data["data"]["offset"] == 0
        assert data["data"]["limit"] == 10

        # Test second page
        response = client.get("/api/deposits/?limit=10&offset=10",
                              headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]["deposits"]) == 5
        assert data["data"]["offset"] == 10

    def test_get_user_deposits_only_own_deposits(self, client: TestClient,
                                                 auth_headers, test_user,
                                                 admin_user, db):
        """Test that user only sees their own deposits"""
        # Create deposit for test user
        user_transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending,
            wallet_address="TTest1234567890123456789012345678",
            comment="User deposit"
        )
        db.add(user_transaction)

        # Create deposit for admin user
        admin_transaction = Transaction(
            user_id=admin_user.id,
            amount=200.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending,
            wallet_address="TTest2345678901234567890123456789",
            comment="Admin deposit"
        )
        db.add(admin_transaction)
        db.commit()

        response = client.get("/api/deposits/", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        deposits = data["data"]["deposits"]
        assert len(deposits) == 1
        assert deposits[0]["id"] == user_transaction.id
        assert deposits[0]["amount"] == 100.0

    def test_get_deposits_unauthorized(self, client: TestClient):
        """Test getting deposits without authentication"""
        response = client.get("/api/deposits/")
        assert response.status_code == 401


class TestDepositIntegration:
    """Integration tests for deposit flow"""

    @patch(
        'app.services.address_pool.AddressPoolService.get_available_address_with_retry')
    @patch(
        'app.services.address_pool.AddressPoolService.assign_address_to_transaction_atomic')
    def test_full_deposit_request_flow(self, mock_assign, mock_get_address,
                                       client: TestClient, auth_headers,
                                       test_wallet_address, db):
        """Test complete deposit request flow"""
        # Mock address pool service
        mock_get_address.return_value = test_wallet_address
        mock_assign.return_value = True

        # Request deposit
        request_data = {"amount": 250.0}
        response = client.post("/api/deposits/request", json=request_data,
                               headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        transaction_id = data["data"]["transaction_id"]

        # Verify transaction was created in database
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id).first()
        assert transaction is not None
        assert transaction.amount == 250.0
        assert transaction.transaction_type == TransactionTypeEnum.deposit
        assert transaction.withdrawal_status == WithdrawalStatusEnum.pending
        assert transaction.wallet_address == test_wallet_address.address

        # Verify address assignment was called
        mock_assign.assert_called_once_with(db, transaction.id,
                                            test_wallet_address.id)

    def test_deposit_request_creates_proper_transaction_record(self,
                                                               client: TestClient,
                                                               auth_headers,
                                                               test_wallet_address,
                                                               test_user, db):
        """Test that deposit request creates proper transaction record"""
        with patch(
                'app.services.address_pool.AddressPoolService.get_available_address_with_retry') as mock_get:
            with patch(
                    'app.services.address_pool.AddressPoolService.assign_address_to_transaction_atomic'):
                mock_get.return_value = test_wallet_address

                request_data = {"amount": 150.0}
                response = client.post("/api/deposits/request",
                                       json=request_data, headers=auth_headers)

                # Get transaction from database
                transaction = db.query(Transaction).filter(
                    Transaction.user_id == test_user.id,
                    Transaction.amount == 150.0
                ).first()

                assert transaction is not None
                assert transaction.transaction_type == TransactionTypeEnum.deposit
                assert transaction.withdrawal_status == WithdrawalStatusEnum.pending
                assert transaction.payment_method == "USDT (TRC20)"
                assert transaction.wallet_address == test_wallet_address.address
                assert "Deposit address assigned" in transaction.comment
                assert transaction.created_at is not None

    def test_concurrent_deposit_requests(self, client: TestClient,
                                         auth_headers, db):
        """Test multiple concurrent deposit requests"""
        # Create multiple addresses
        addresses = []
        for i in range(3):
            address = WalletAddress(
                address=f"TTest{i:030d}",
                status=AddressStatusEnum.active,
                is_active=True
            )
            db.add(address)
            addresses.append(address)
        db.commit()

        with patch(
                'app.services.address_pool.AddressPoolService.get_available_address_with_retry') as mock_get:
            with patch(
                    'app.services.address_pool.AddressPoolService.assign_address_to_transaction_atomic'):
                # Mock to return different addresses for each call
                mock_get.side_effect = addresses

                # Make multiple requests
                responses = []
                for i in range(3):
                    request_data = {"amount": 100.0 + i * 10}
                    response = client.post("/api/deposits/request",
                                           json=request_data,
                                           headers=auth_headers)
                    responses.append(response)

                # All should succeed
                for i, response in enumerate(responses):
                    assert response.status_code == 200
                    data = response.json()
                    assert data["data"]["amount"] == 100.0 + i * 10


class TestDepositValidation:
    """Test deposit request validation"""

    def test_deposit_amount_validation(self, client: TestClient, auth_headers):
        """Test various amount validation scenarios"""
        test_cases = [
            (0, 400),  # Zero amount
            (-10, 422),  # Negative amount
            (0.9, 400),  # Below minimum
            (10001, 400),  # Above maximum
            (50, 200),  # Valid amount
        ]

        for amount, expected_status in test_cases:
            with patch(
                    'app.services.address_pool.AddressPoolService.get_available_address_with_retry') as mock_get:
                if expected_status == 200:
                    mock_address = MagicMock()
                    mock_address.address = "TTest1234567890123456789012345678"
                    mock_address.id = 1
                    mock_get.return_value = mock_address

                    with patch(
                            'app.services.address_pool.AddressPoolService.assign_address_to_transaction_atomic'):
                        request_data = {"amount": amount}
                        response = client.post("/api/deposits/request",
                                               json=request_data,
                                               headers=auth_headers)
                        assert response.status_code == expected_status
                else:
                    request_data = {"amount": amount}
                    response = client.post("/api/deposits/request",
                                           json=request_data,
                                           headers=auth_headers)
                    assert response.status_code == expected_status

    def test_deposit_request_malformed_data(self, client: TestClient,
                                            auth_headers):
        """Test deposit request with malformed data"""
        test_cases = [
            {},  # Missing amount
            {"amount": "invalid"},  # Invalid amount type
            {"amount": 100, "extra": 1},  # Extra fields (should be ignored)
            {"wrong_field": 100},  # Wrong field name
        ]

        for request_data in test_cases:
            response = client.post("/api/deposits/request", json=request_data,
                                   headers=auth_headers)
            assert response.status_code in [400,
                                            422]  # Bad request or validation error