# app/models/transaction.py

import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, \
    Enum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class TransactionTypeEnum(enum.Enum):
    deposit = "deposit"
    withdrawal = "withdrawal"


class WithdrawalStatusEnum(enum.Enum):
    pending = "pending"
    requested = "requested"
    approved = "approved"
    completed = "completed"
    rejected = "rejected"
    cancelled = "cancelled"


class TransactionPurposeEnum(enum.Enum):
    regular = "regular"
    system_withdrawal = "system_withdrawal"
    system_swift = "system_swift"
    user_swift = "user_swift"
    system_tax = "system_tax"
    tax_payment = "tax_payment"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    amount = Column(Float, nullable=False)
    transaction_type = Column(Enum(TransactionTypeEnum), nullable=False)
    withdrawal_status = Column(Enum(WithdrawalStatusEnum), nullable=True)
    transaction_purpose = Column(Enum(TransactionPurposeEnum),
                                 default=TransactionPurposeEnum.regular)

    payment_method = Column(String(100), nullable=True)
    wallet_address = Column(String(100), nullable=True)
    txid = Column(String(100), nullable=True, index=True)

    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="transactions")
    address_reservations = relationship("AddressReservation",
                                        back_populates="transaction")