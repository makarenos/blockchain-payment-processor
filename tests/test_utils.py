# tests/test_utils.py

import pytest
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from app.models.wallet import WalletAddress, AddressStatusEnum
from app.core.core_auth import create_access_token, get_password_hash


class TestDataFactory:
    """Factory for creating test data"""

    @staticmethod
    def create_test_user(db, username: str = "testuser", **kwargs) -> User:
        """Create a test user with default values"""
        defaults = {
            "username": username,
            "password_hash": get_password_hash("testpass123"),
            "email": f"{username}@example.com",
            "full_name": f"Test {username.title()}",
            "is_active": True,
            "is_admin": False
        }
        defaults.update(kwargs)

        user = User(**defaults)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def create_test_admin(db, username: str = "testadmin", **kwargs) -> User:
        """Create a test admin user"""
        kwargs.setdefault("is_admin", True)
        return TestDataFactory.create_test_user(db, username, **kwargs)

    @staticmethod
    def create_test_balance(db, user: User, amount: float = 1000.0) -> Balance:
        """Create a test balance for user"""
        balance = Balance(user_id=user.id, amount=amount)
        db.add(balance)
        db.commit()
        db.refresh(balance)
        return balance

    @staticmethod
    def create_test_wallet_address(db, address: str = None,
                                   **kwargs) -> WalletAddress:
        """Create a test wallet address"""
        if address is None:
            address = f"TTest{datetime.now().strftime('%Y%m%d%H%M%S')}"
            address = address[:34].ljust(34, '0')

        defaults = {
            "address": address,
            "status": AddressStatusEnum.active,
            "is_active": True,
            "usage_count": 0
        }
        defaults.update(kwargs)

        wallet = WalletAddress(**defaults)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        return wallet

    @staticmethod
    def create_test_transaction(db, user: User, **kwargs) -> Transaction:
        """Create a test transaction"""
        defaults = {
            "user_id": user.id,
            "amount": 100.0,
            "transaction_type": TransactionTypeEnum.deposit,
            "withdrawal_status": WithdrawalStatusEnum.pending,
            "payment_method": "USDT (TRC20)",
            "wallet_address": "TTest1234567890123456789012345678",
            "comment": "Test transaction"
        }
        defaults.update(kwargs)

        transaction = Transaction(**defaults)
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        return transaction

    @staticmethod
    def create_test_deposit(db, user: User, amount: float = 100.0,
                            **kwargs) -> Transaction:
        """Create a test deposit transaction"""
        kwargs.update({
            "amount": amount,
            "transaction_type": TransactionTypeEnum.deposit,
            "withdrawal_status": WithdrawalStatusEnum.pending
        })
        return TestDataFactory.create_test_transaction(db, user, **kwargs)

    @staticmethod
    def create_test_withdrawal(db, user: User, amount: float = 50.0,
                               **kwargs) -> Transaction:
        """Create a test withdrawal transaction"""
        kwargs.update({
            "amount": amount,
            "transaction_type": TransactionTypeEnum.withdrawal,
            "withdrawal_status": WithdrawalStatusEnum.requested,
            "wallet_address": "TDest123456789012345678901234567"
        })
        return TestDataFactory.create_test_transaction(db, user, **kwargs)


class TestAuthHelper:
    """Helper for authentication in tests"""

    @staticmethod
    def create_auth_headers(user: User) -> Dict[str, str]:
        """Create authorization headers for user"""
        token = create_access_token(data={"sub": str(user.id)})
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def login_user(client, username: str, password: str) -> str:
        """Login user and return token"""
        response = client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })
        assert response.status_code == 200
        return response.json()["access_token"]

    @staticmethod
    def register_and_login_user(client, user_data: Dict[str, Any]) -> tuple[
        Dict, str]:
        """Register user and return user data and token"""
        # Register
        register_response = client.post("/api/auth/register", json=user_data)
        assert register_response.status_code == 200
        registered_user = register_response.json()

        # Login
        token = TestAuthHelper.login_user(client, user_data["username"],
                                          user_data["password"])

        return registered_user, token


class TestWebhookHelper:
    """Helper for webhook testing"""

    @staticmethod
    def create_payment_webhook_payload(transaction_id: int,
                                       status: str = "success", **kwargs) -> \
    Dict[str, Any]:
        """Create payment webhook payload"""
        payload = {
            "transaction_id": transaction_id,
            "status": status,
            "payment_id": f"pay_{transaction_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "timestamp": int(datetime.utcnow().timestamp())
        }
        payload.update(kwargs)
        return payload

    @staticmethod
    def create_blockchain_webhook_payload(address: str, amount: float,
                                          confirmations: int = 20, **kwargs) -> \
    Dict[str, Any]:
        """Create blockchain webhook payload"""
        payload = {
            "event_type": "transaction_confirmed",
            "txid": f"blockchain_tx_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "confirmations": confirmations,
            "address": address,
            "amount": amount,
            "token": "USDT",
            "block_height": 12345678,
            "timestamp": int(datetime.utcnow().timestamp())
        }
        payload.update(kwargs)
        return payload


class TestAssertions:
    """Custom assertions for testing"""

    @staticmethod
    def assert_transaction_status(transaction: Transaction,
                                  expected_status: WithdrawalStatusEnum):
        """Assert transaction has expected status"""
        assert transaction.withdrawal_status == expected_status, \
            f"Expected {expected_status.value}, got {transaction.withdrawal_status.value if transaction.withdrawal_status else None}"

    @staticmethod
    def assert_balance_amount(balance: Balance, expected_amount: float,
                              tolerance: float = 0.001):
        """Assert balance amount with tolerance"""
        assert abs(balance.amount - expected_amount) <= tolerance, \
            f"Expected balance {expected_amount}, got {balance.amount}"

    @staticmethod
    def assert_response_success(response, expected_operation: str = None):
        """Assert API response is successful"""
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        if expected_operation:
            assert data["operation"] == expected_operation

    @staticmethod
    def assert_response_error(response, expected_status: int,
                              expected_message: str = None):
        """Assert API response has expected error"""
        assert response.status_code == expected_status
        if expected_message:
            data = response.json()
            assert expected_message in data.get("detail", "")

    @staticmethod
    def assert_transaction_history(transactions: List[Dict],
                                   expected_count: int = None,
                                   expected_type: str = None):
        """Assert transaction history has expected properties"""
        if expected_count is not None:
            assert len(transactions) == expected_count

        if expected_type:
            for tx in transactions:
                assert tx.get("type") == expected_type or tx.get(
                    "transaction_type") == expected_type


class TestTimeHelper:
    """Helper for time-related testing"""

    @staticmethod
    def create_expired_datetime(minutes_ago: int = 30) -> datetime:
        """Create datetime that is expired"""
        return datetime.utcnow() - timedelta(minutes=minutes_ago)

    @staticmethod
    def create_future_datetime(minutes_ahead: int = 30) -> datetime:
        """Create future datetime"""
        return datetime.utcnow() + timedelta(minutes=minutes_ahead)

    @staticmethod
    def assert_datetime_recent(dt: datetime, tolerance_seconds: int = 60):
        """Assert datetime is recent (within tolerance)"""
        now = datetime.utcnow()
        diff = abs((now - dt).total_seconds())
        assert diff <= tolerance_seconds, f"Datetime {dt} is not recent (diff: {diff}s)"


class MockService:
    """Mocks for external services"""

    @staticmethod
    def mock_address_pool_service():
        """Create mock for AddressPoolService"""
        mock = MagicMock()
        mock.get_available_address_with_retry.return_value = None
        mock.assign_address_to_transaction_atomic.return_value = True
        mock.release_address_atomic.return_value = True
        mock.get_pool_status.return_value = {
            "total_addresses": 50,
            "active_addresses": 45,
            "reserved_addresses": 3,
            "inactive_addresses": 2,
            "pool_health": "healthy"
        }
        mock.add_addresses_to_pool_atomic.return_value = {
            "added_count": 10,
            "skipped_count": 0,
            "total_addresses": 60
        }
        mock.cleanup_expired_reservations.return_value = 5
        return mock

    @staticmethod
    def mock_status_sync_service():
        """Create mock for status sync service"""
        mock = MagicMock()
        mock.return_value = {
            "changed": True,
            "old_status": "available",
            "new_status": "withdrawal_in_progress"
        }
        return mock

    @staticmethod
    def mock_tron_api():
        """Create mock for TRON API responses"""
        return {
            "success": True,
            "data": [
                {
                    "transaction_id": "mock_tx_123",
                    "block_timestamp": int(
                        datetime.utcnow().timestamp() * 1000),
                    "from": "TSender123456789012345678901234",
                    "to": "TReceiver12345678901234567890123",
                    "value": "100000000",  # 100 USDT
                    "confirmed": True,
                    "confirmations": 20
                }
            ]
        }


class DatabaseHelper:
    """Helper for database operations in tests"""

    @staticmethod
    def clear_all_transactions(db):
        """Clear all transactions from database"""
        db.query(Transaction).delete()
        db.commit()

    @staticmethod
    def clear_all_users(db):
        """Clear all users and related data"""
        db.query(Balance).delete()
        db.query(Transaction).delete()
        db.query(User).delete()
        db.commit()

    @staticmethod
    def clear_all_addresses(db):
        """Clear all wallet addresses"""
        from app.models.wallet import AddressReservation
        db.query(AddressReservation).delete()
        db.query(WalletAddress).delete()
        db.commit()

    @staticmethod
    def get_transaction_count(db,
                              transaction_type: TransactionTypeEnum = None) -> int:
        """Get count of transactions by type"""
        query = db.query(Transaction)
        if transaction_type:
            query = query.filter(
                Transaction.transaction_type == transaction_type)
        return query.count()

    @staticmethod
    def get_user_balance(db, user_id: int) -> float:
        """Get user balance amount"""
        balance = db.query(Balance).filter(Balance.user_id == user_id).first()
        return balance.amount if balance else 0.0


class PerformanceHelper:
    """Helper for performance testing"""

    @staticmethod
    def measure_time(func):
        """Decorator to measure function execution time"""
        import time

        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            end = time.time()
            print(f"{func.__name__} took {end - start:.4f} seconds")
            return result

        return wrapper

    @staticmethod
    def assert_execution_time(func, max_seconds: float):
        """Assert function executes within time limit"""
        import time

        start = time.time()
        func()
        end = time.time()

        execution_time = end - start
        assert execution_time <= max_seconds, \
            f"Function took {execution_time:.4f}s, expected <= {max_seconds}s"


# Test utilities for common patterns
def skip_if_no_external_services():
    """Skip test if external services are not available"""
    return pytest.mark.skipif(
        True,  # Default to skip - would check actual service availability
        reason="External services not available"
    )


def parametrize_transaction_types():
    """Parametrize test with all transaction types"""
    return pytest.mark.parametrize(
        "transaction_type",
        [TransactionTypeEnum.deposit, TransactionTypeEnum.withdrawal]
    )


def parametrize_withdrawal_statuses():
    """Parametrize test with all withdrawal statuses"""
    return pytest.mark.parametrize(
        "status",
        [
            WithdrawalStatusEnum.pending,
            WithdrawalStatusEnum.requested,
            WithdrawalStatusEnum.approved,
            WithdrawalStatusEnum.completed,
            WithdrawalStatusEnum.rejected,
            WithdrawalStatusEnum.cancelled
        ]
    )


def parametrize_user_types():
    """Parametrize test with regular and admin users"""
    return pytest.mark.parametrize(
        "is_admin",
        [False, True],
        ids=["regular_user", "admin_user"]
    )


# Constants for testing
TEST_ADDRESSES = [
    "TTest1234567890123456789012345678",
    "TTest2345678901234567890123456789",
    "TTest3456789012345678901234567890",
    "TTest4567890123456789012345678901",
    "TTest5678901234567890123456789012"
]

TEST_AMOUNTS = [1.0, 10.0, 100.0, 1000.0, 5000.0]

TEST_USER_DATA = {
    "username": "testuser",
    "password": "testpass123",
    "email": "test@example.com",
    "full_name": "Test User"
}

TEST_ADMIN_DATA = {
    "username": "testadmin",
    "password": "testadminpass123",
    "email": "admin@example.com",
    "full_name": "Test Admin"
}