# app/schemas/transaction.py

from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
from enum import Enum
from app.models.transaction import TransactionTypeEnum, WithdrawalStatusEnum, \
    TransactionPurposeEnum


class TransactionBase(BaseModel):
    amount: float = Field(..., gt=0, description="Transaction amount")
    payment_method: Optional[str] = None
    wallet_address: Optional[str] = None
    comment: Optional[str] = None


class DepositRequest(BaseModel):
    amount: float = Field(..., gt=0, le=10000,
                          description="Deposit amount in USDT")

    @validator('amount')
    def validate_amount(cls, v):
        if v < 1.0:
            raise ValueError('Minimum deposit amount is 1 USDT')
        if v > 10000.0:
            raise ValueError('Maximum deposit amount is 10,000 USDT')
        return v


class WithdrawalRequest(BaseModel):
    amount: float = Field(..., gt=0, le=5000,
                          description="Withdrawal amount in USDT")
    wallet_address: str = Field(..., min_length=34, max_length=34,
                                description="TRC20 wallet address")

    @validator('amount')
    def validate_amount(cls, v):
        if v < 5.0:
            raise ValueError('Minimum withdrawal amount is 5 USDT')
        if v > 5000.0:
            raise ValueError('Maximum withdrawal amount is 5,000 USDT')
        return v

    @validator('wallet_address')
    def validate_address(cls, v):
        if not v.startswith('T'):
            raise ValueError('Invalid TRC20 address format')
        if len(v) != 34:
            raise ValueError('TRC20 address must be 34 characters')
        return v


class TransactionResponse(BaseModel):
    id: int
    amount: float
    transaction_type: TransactionTypeEnum
    withdrawal_status: Optional[WithdrawalStatusEnum]
    payment_method: Optional[str]
    wallet_address: Optional[str]
    txid: Optional[str]
    transaction_purpose: Optional[TransactionPurposeEnum]
    comment: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


class TransactionCreate(TransactionBase):
    transaction_type: TransactionTypeEnum
    withdrawal_status: Optional[
        WithdrawalStatusEnum] = WithdrawalStatusEnum.pending
    transaction_purpose: Optional[
        TransactionPurposeEnum] = TransactionPurposeEnum.regular


class AdminTransactionUpdate(BaseModel):
    withdrawal_status: Optional[WithdrawalStatusEnum]
    comment: Optional[str]
    txid: Optional[str]


class DepositAddressResponse(BaseModel):
    transaction_id: int
    deposit_address: str
    amount: float
    network: str
    status: str
    expires_at: str
    message: str
    note: str


class WithdrawalStatusResponse(BaseModel):
    transaction_id: int
    amount: float
    wallet_address: str
    status: str
    created_at: str
    processed_at: Optional[str]
    comment: Optional[str]
    purpose: str


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    count: int
    offset: int
    limit: int