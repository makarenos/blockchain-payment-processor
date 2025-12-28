# tests/conftest.py

import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import get_db, Base
from app.core.core_auth import create_access_token, get_password_hash
from app.models.user import User, Balance
from app.models.wallet import WalletAddress, AddressStatusEnum
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from datetime import datetime, timedelta

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={
        "check_same_thread": False,
    },
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                   bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create test database tables"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """Create a fresh database session for each test"""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client():
    """FastAPI test client"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user(db):
    """Create a test user"""
    user = User(
        username="testuser",
        password_hash=get_password_hash("testpass123"),
        email="test@example.com",
        full_name="Test User",
        is_active=True,
        is_admin=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create balance
    balance = Balance(user_id=user.id, amount=1000.0)
    db.add(balance)
    db.commit()

    return user


@pytest.fixture
def admin_user(db):
    """Create a test admin user"""
    admin = User(
        username="adminuser",
        password_hash=get_password_hash("adminpass123"),
        email="admin@example.com",
        full_name="Admin User",
        is_active=True,
        is_admin=True
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    # Create balance
    balance = Balance(user_id=admin.id, amount=5000.0)
    db.add(balance)
    db.commit()

    return admin


@pytest.fixture
def user_token(test_user):
    """Create JWT token for test user"""
    return create_access_token(data={"sub": str(test_user.id)})


@pytest.fixture
def admin_token(admin_user):
    """Create JWT token for admin user"""
    return create_access_token(data={"sub": str(admin_user.id)})


@pytest.fixture
def auth_headers(user_token):
    """Authorization headers for regular user"""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def admin_headers(admin_token):
    """Authorization headers for admin user"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def test_wallet_address(db):
    """Create a test wallet address"""
    address = WalletAddress(
        address="TTest1234567890123456789012345678",
        status=AddressStatusEnum.active,
        is_active=True,
        usage_count=0
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@pytest.fixture
def test_deposit_transaction(db, test_user, test_wallet_address):
    """Create a test deposit transaction"""
    transaction = Transaction(
        user_id=test_user.id,
        amount=100.0,
        transaction_type=TransactionTypeEnum.deposit,
        withdrawal_status=WithdrawalStatusEnum.pending,
        payment_method="USDT (TRC20)",
        wallet_address=test_wallet_address.address,
        comment="Test deposit"
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@pytest.fixture
def test_withdrawal_transaction(db, test_user):
    """Create a test withdrawal transaction"""
    transaction = Transaction(
        user_id=test_user.id,
        amount=50.0,
        transaction_type=TransactionTypeEnum.withdrawal,
        withdrawal_status=WithdrawalStatusEnum.requested,
        payment_method="USDT (TRC20)",
        wallet_address="TTarget1234567890123456789012345",
        comment="Test withdrawal"
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@pytest.fixture
def mock_tron_api_success():
    """Mock successful TronGrid API response"""
    return {
        "success": True,
        "data": [
            {
                "transaction_id": "test_txid_123",
                "block_timestamp": int(datetime.utcnow().timestamp() * 1000),
                "from": "TSender123456789012345678901234",
                "to": "TReceiver12345678901234567890123",
                "value": "100000000",  # 100 USDT (6 decimals)
                "confirmed": True,
                "confirmations": 20
            }
        ]
    }


@pytest.fixture
def mock_webhook_payload():
    """Mock webhook payload"""
    return {
        "event_type": "transaction_confirmed",
        "txid": "test_txid_123",
        "confirmations": 20,
        "address": "TTest1234567890123456789012345678",
        "amount": 100.0,
        "token": "USDT",
        "timestamp": int(datetime.utcnow().timestamp())
    }


# Test data constants
TEST_WALLET_ADDRESSES = [
    "TTest1234567890123456789012345678",
    "TTest2345678901234567890123456789",
    "TTest3456789012345678901234567890",
    "TTest4567890123456789012345678901",
    "TTest5678901234567890123456789012"
]

TEST_USER_DATA = {
    "username": "newtestuser",
    "password": "newpass123",
    "email": "newtest@example.com",
    "full_name": "New Test User"
}

TEST_ADMIN_DATA = {
    "username": "newadminuser",
    "password": "newadminpass123",
    "email": "newadmin@example.com",
    "full_name": "New Admin User"
}