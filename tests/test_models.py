# tests/test_models.py

import pytest
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from app.models.user import User, Balance
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum, TransactionPurposeEnum
from app.models.wallet import WalletAddress, AddressReservation, \
    AddressStatusEnum
from app.core.core_auth import get_password_hash


class TestUserModel:
    """Test User model functionality"""

    def test_create_user(self, db):
        """Test creating a new user"""
        user = User(
            username="testuser",
            password_hash=get_password_hash("password123"),
            email="test@example.com",
            full_name="Test User",
            is_active=True,
            is_admin=False
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.id is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_admin is False
        assert user.created_at is not None
        assert user.updated_at is not None

    def test_user_unique_username(self, db):
        """Test that usernames must be unique"""
        user1 = User(
            username="unique_user",
            password_hash=get_password_hash("password123"),
            email="user1@example.com"
        )
        db.add(user1)
        db.commit()

        # Try to create another user with same username
        user2 = User(
            username="unique_user",  # Duplicate username
            password_hash=get_password_hash("password456"),
            email="user2@example.com"
        )
        db.add(user2)

        with pytest.raises(IntegrityError):
            db.commit()

    def test_user_unique_email(self, db):
        """Test that emails must be unique"""
        user1 = User(
            username="user1",
            password_hash=get_password_hash("password123"),
            email="same@example.com"
        )
        db.add(user1)
        db.commit()

        user2 = User(
            username="user2",
            password_hash=get_password_hash("password456"),
            email="same@example.com"  # Duplicate email
        )
        db.add(user2)

        with pytest.raises(IntegrityError):
            db.commit()

    def test_user_balance_relationship(self, db, test_user):
        """Test User-Balance relationship"""
        balance = Balance(user_id=test_user.id, amount=100.0)
        db.add(balance)
        db.commit()

        # Test accessing balance through user
        db.refresh(test_user)
        assert test_user.balance is not None
        assert test_user.balance.amount == 100.0

    def test_user_transactions_relationship(self, db, test_user):
        """Test User-Transaction relationship"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=50.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending
        )
        db.add(transaction)
        db.commit()

        # Test accessing transactions through user
        db.refresh(test_user)
        assert len(test_user.transactions) == 1
        assert test_user.transactions[0].amount == 50.0


class TestBalanceModel:
    """Test Balance model functionality"""

    def test_create_balance(self, db, test_user):
        """Test creating a balance"""
        balance = Balance(user_id=test_user.id, amount=1000.0)
        db.add(balance)
        db.commit()
        db.refresh(balance)

        assert balance.id is not None
        assert balance.user_id == test_user.id
        assert balance.amount == 1000.0
        assert balance.created_at is not None
        assert balance.updated_at is not None

    def test_balance_user_relationship(self, db, test_user):
        """Test Balance-User relationship"""
        balance = Balance(user_id=test_user.id, amount=500.0)
        db.add(balance)
        db.commit()
        db.refresh(balance)

        # Test accessing user through balance
        assert balance.user is not None
        assert balance.user.id == test_user.id
        assert balance.user.username == test_user.username

    def test_balance_amount_precision(self, db, test_user):
        """Test balance amount precision"""
        balance = Balance(user_id=test_user.id, amount=123.456789)
        db.add(balance)
        db.commit()
        db.refresh(balance)

        # Should maintain precision
        assert balance.amount == 123.456789


class TestTransactionModel:
    """Test Transaction model functionality"""

    def test_create_deposit_transaction(self, db, test_user):
        """Test creating a deposit transaction"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending,
            payment_method="USDT (TRC20)",
            wallet_address="TTest1234567890123456789012345678",
            comment="Test deposit"
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        assert transaction.id is not None
        assert transaction.user_id == test_user.id
        assert transaction.amount == 100.0
        assert transaction.transaction_type == TransactionTypeEnum.deposit
        assert transaction.withdrawal_status == WithdrawalStatusEnum.pending
        assert transaction.created_at is not None

    def test_create_withdrawal_transaction(self, db, test_user):
        """Test creating a withdrawal transaction"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=50.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested,
            wallet_address="TDest123456789012345678901234567",
            transaction_purpose=TransactionPurposeEnum.regular
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        assert transaction.transaction_type == TransactionTypeEnum.withdrawal
        assert transaction.withdrawal_status == WithdrawalStatusEnum.requested
        assert transaction.transaction_purpose == TransactionPurposeEnum.regular

    def test_transaction_enums(self, db, test_user):
        """Test transaction enum values"""
        # Test all transaction types
        deposit = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending
        )

        withdrawal = Transaction(
            user_id=test_user.id,
            amount=50.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested
        )

        db.add_all([deposit, withdrawal])
        db.commit()

        # Test all withdrawal statuses
        statuses = [
            WithdrawalStatusEnum.pending,
            WithdrawalStatusEnum.requested,
            WithdrawalStatusEnum.approved,
            WithdrawalStatusEnum.completed,
            WithdrawalStatusEnum.rejected,
            WithdrawalStatusEnum.cancelled
        ]

        for status in statuses:
            transaction = Transaction(
                user_id=test_user.id,
                amount=10.0,
                transaction_type=TransactionTypeEnum.deposit,
                withdrawal_status=status
            )
            db.add(transaction)

        db.commit()

        # Verify all were created
        all_transactions = db.query(Transaction).filter(
            Transaction.user_id == test_user.id).all()
        assert len(all_transactions) == len(
            statuses) + 2  # +2 for initial deposit/withdrawal

    def test_transaction_user_relationship(self, db, test_user):
        """Test Transaction-User relationship"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=75.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.completed
        )
        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        # Test accessing user through transaction
        assert transaction.user is not None
        assert transaction.user.id == test_user.id
        assert transaction.user.username == test_user.username

    def test_transaction_processed_at(self, db, test_user):
        """Test transaction processed_at field"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=25.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested
        )
        db.add(transaction)
        db.commit()

        # Initially should be None
        assert transaction.processed_at is None

        # Update to completed
        transaction.withdrawal_status = WithdrawalStatusEnum.completed
        transaction.processed_at = datetime.utcnow()
        db.commit()
        db.refresh(transaction)

        assert transaction.processed_at is not None
        assert isinstance(transaction.processed_at, datetime)


class TestWalletModel:
    """Test Wallet and Address models"""

    def test_create_wallet_address(self, db):
        """Test creating a wallet address"""
        address = WalletAddress(
            address="TTest1234567890123456789012345678",
            status=AddressStatusEnum.active,
            is_active=True,
            usage_count=0
        )

        db.add(address)
        db.commit()
        db.refresh(address)

        assert address.id is not None
        assert address.address == "TTest1234567890123456789012345678"
        assert address.status == AddressStatusEnum.active
        assert address.is_active is True
        assert address.usage_count == 0
        assert address.created_at is not None

    def test_wallet_address_unique(self, db):
        """Test that wallet addresses must be unique"""
        address1 = WalletAddress(
            address="TUnique123456789012345678901234567",
            status=AddressStatusEnum.active
        )
        db.add(address1)
        db.commit()

        address2 = WalletAddress(
            address="TUnique123456789012345678901234567",  # Duplicate
            status=AddressStatusEnum.active
        )
        db.add(address2)

        with pytest.raises(IntegrityError):
            db.commit()

    def test_address_status_enum(self, db):
        """Test address status enum values"""
        statuses = [
            AddressStatusEnum.active,
            AddressStatusEnum.reserved,
            AddressStatusEnum.inactive
        ]

        for i, status in enumerate(statuses):
            address = WalletAddress(
                address=f"TStatus{i:030d}",
                status=status,
                is_active=True
            )
            db.add(address)

        db.commit()

        # Verify all statuses work
        addresses = db.query(WalletAddress).all()
        assert len(addresses) == len(statuses)

    def test_create_address_reservation(self, db, test_user,
                                        test_wallet_address):
        """Test creating an address reservation"""
        reservation = AddressReservation(
            address_id=test_wallet_address.id,
            user_id=test_user.id,
            reserved_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            status="active"
        )

        db.add(reservation)
        db.commit()
        db.refresh(reservation)

        assert reservation.id is not None
        assert reservation.address_id == test_wallet_address.id
        assert reservation.user_id == test_user.id
        assert reservation.status == "active"
        assert reservation.reserved_at is not None
        assert reservation.expires_at is not None

    def test_address_reservation_relationships(self, db, test_user,
                                               test_wallet_address):
        """Test AddressReservation relationships"""
        reservation = AddressReservation(
            address_id=test_wallet_address.id,
            user_id=test_user.id,
            reserved_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            status="active"
        )

        db.add(reservation)
        db.commit()
        db.refresh(reservation)

        # Test relationships
        assert reservation.address is not None
        assert reservation.address.id == test_wallet_address.id
        assert reservation.user is not None
        assert reservation.user.id == test_user.id

    def test_wallet_address_reservations_relationship(self, db, test_user,
                                                      test_wallet_address):
        """Test WalletAddress-Reservations relationship"""
        reservation = AddressReservation(
            address_id=test_wallet_address.id,
            user_id=test_user.id,
            reserved_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            status="active"
        )

        db.add(reservation)
        db.commit()

        # Access reservations through wallet address
        db.refresh(test_wallet_address)
        assert len(test_wallet_address.reservations) == 1
        assert test_wallet_address.reservations[0].user_id == test_user.id


class TestModelValidation:
    """Test model validation and constraints"""

    def test_user_required_fields(self, db):
        """Test user required field validation"""
        # Username is required
        with pytest.raises(IntegrityError):
            user = User(
                password_hash=get_password_hash("password123"),
                email="test@example.com"
                # Missing username
            )
            db.add(user)
            db.commit()

    def test_transaction_required_fields(self, db, test_user):
        """Test transaction required field validation"""
        # Amount and type are required
        with pytest.raises(IntegrityError):
            transaction = Transaction(
                user_id=test_user.id
                # Missing amount and transaction_type
            )
            db.add(transaction)
            db.commit()

    def test_balance_foreign_key_constraint(self, db):
        """Test balance foreign key constraint"""
        with pytest.raises(IntegrityError):
            balance = Balance(
                user_id=999999,  # Non-existent user
                amount=100.0
            )
            db.add(balance)
            db.commit()

    def test_address_reservation_foreign_keys(self, db):
        """Test address reservation foreign key constraints"""
        with pytest.raises(IntegrityError):
            reservation = AddressReservation(
                address_id=999999,  # Non-existent address
                user_id=999999,  # Non-existent user
                reserved_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            db.add(reservation)
            db.commit()


class TestModelQueries:
    """Test model query functionality"""

    def test_find_user_by_username(self, db, test_user):
        """Test finding user by username"""
        found_user = db.query(User).filter(
            User.username == test_user.username).first()
        assert found_user is not None
        assert found_user.id == test_user.id

    def test_find_user_by_email(self, db, test_user):
        """Test finding user by email"""
        found_user = db.query(User).filter(
            User.email == test_user.email).first()
        assert found_user is not None
        assert found_user.id == test_user.id

    def test_find_transactions_by_user(self, db, test_user,
                                       test_deposit_transaction):
        """Test finding transactions by user"""
        transactions = db.query(Transaction).filter(
            Transaction.user_id == test_user.id).all()
        assert len(transactions) >= 1
        assert test_deposit_transaction.id in [tx.id for tx in transactions]

    def test_find_transactions_by_type(self, db, test_user):
        """Test finding transactions by type"""
        # Create transactions of different types
        deposit = Transaction(
            user_id=test_user.id,
            amount=100.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending
        )

        withdrawal = Transaction(
            user_id=test_user.id,
            amount=50.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.requested
        )

        db.add_all([deposit, withdrawal])
        db.commit()

        # Query by type
        deposits = db.query(Transaction).filter(
            Transaction.transaction_type == TransactionTypeEnum.deposit
        ).all()

        withdrawals = db.query(Transaction).filter(
            Transaction.transaction_type == TransactionTypeEnum.withdrawal
        ).all()

        assert len(deposits) >= 1
        assert len(withdrawals) >= 1
        assert all(tx.transaction_type == TransactionTypeEnum.deposit for tx in
                   deposits)
        assert all(
            tx.transaction_type == TransactionTypeEnum.withdrawal for tx in
            withdrawals)

    def test_find_active_addresses(self, db):
        """Test finding active wallet addresses"""
        # Create addresses with different statuses
        active_addr = WalletAddress(
            address="TActive123456789012345678901234567",
            status=AddressStatusEnum.active,
            is_active=True
        )

        reserved_addr = WalletAddress(
            address="TReserved1234567890123456789012345",
            status=AddressStatusEnum.reserved,
            is_active=True
        )

        inactive_addr = WalletAddress(
            address="TInactive123456789012345678901234",
            status=AddressStatusEnum.inactive,
            is_active=False
        )

        db.add_all([active_addr, reserved_addr, inactive_addr])
        db.commit()

        # Query active addresses
        active_addresses = db.query(WalletAddress).filter(
            WalletAddress.status == AddressStatusEnum.active,
            WalletAddress.is_active == True
        ).all()

        assert len(active_addresses) >= 1
        assert all(addr.status == AddressStatusEnum.active for addr in
                   active_addresses)
        assert all(addr.is_active is True for addr in active_addresses)


class TestModelTimestamps:
    """Test model timestamp functionality"""

    def test_user_timestamps(self, db):
        """Test user created_at and updated_at timestamps"""
        user = User(
            username="timestamp_user",
            password_hash=get_password_hash("password123"),
            email="timestamp@example.com"
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        created_at = user.created_at
        updated_at = user.updated_at

        assert created_at is not None
        assert updated_at is not None
        assert created_at <= updated_at

        # Update user and check updated_at changes
        user.full_name = "Updated Name"
        db.commit()
        db.refresh(user)

        assert user.created_at == created_at  # Should not change
        assert user.updated_at >= updated_at  # Should be updated

    def test_balance_timestamps(self, db, test_user):
        """Test balance timestamps"""
        balance = Balance(user_id=test_user.id, amount=100.0)

        db.add(balance)
        db.commit()
        db.refresh(balance)

        created_at = balance.created_at
        updated_at = balance.updated_at

        assert created_at is not None
        assert updated_at is not None

        # Update balance
        balance.amount = 200.0
        db.commit()
        db.refresh(balance)

        assert balance.created_at == created_at
        assert balance.updated_at >= updated_at

    def test_transaction_created_at(self, db, test_user):
        """Test transaction created_at timestamp"""
        transaction = Transaction(
            user_id=test_user.id,
            amount=50.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        assert transaction.created_at is not None
        assert isinstance(transaction.created_at, datetime)