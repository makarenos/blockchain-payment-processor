# app/models/wallet.py

import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, \
    Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class AddressStatusEnum(enum.Enum):
    active = "active"
    reserved = "reserved"
    inactive = "inactive"


class WalletAddress(Base):
    __tablename__ = "wallet_addresses"

    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(100), unique=True, index=True, nullable=False)
    status = Column(Enum(AddressStatusEnum), default=AddressStatusEnum.active)
    is_active = Column(Boolean, default=True)

    usage_count = Column(Integer, default=0)
    last_reserved_at = Column(DateTime, nullable=True)
    last_released_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    reservations = relationship("AddressReservation", back_populates="address")


class AddressReservation(Base):
    __tablename__ = "address_reservations"

    id = Column(Integer, primary_key=True, index=True)
    address_id = Column(Integer, ForeignKey("wallet_addresses.id"),
                        nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"),
                            nullable=True)

    reserved_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    released_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="active")  # active, expired, released

    # Relationships
    address = relationship("WalletAddress", back_populates="reservations")
    user = relationship("User", back_populates="address_reservations")
    transaction = relationship("Transaction",
                               back_populates="address_reservations")