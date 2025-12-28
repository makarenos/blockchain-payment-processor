# app/core/config.py

from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field
import os


class Settings(BaseSettings):
    """Application settings"""

    # Basic app settings
    PROJECT_NAME: str = "Blockchain Payment Processor"
    DEBUG: bool = Field(default=False, env="DEBUG")

    # Database settings
    DATABASE_URL: str = Field(
        default="postgresql://user:password@localhost:5432/blockchain_processor",
        env="DATABASE_URL"
    )

    # CORS settings
    CORS_ORIGINS: str = Field(default="*", env="CORS_ORIGINS")

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    # JWT Authentication
    JWT_SECRET_KEY: str = Field(default="your-secret-key-change-in-production",
                                env="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # TRON blockchain settings
    TRON_API_URL: str = Field(default="https://api.trongrid.io",
                              env="TRON_API_URL")
    USDT_CONTRACT: str = Field(
        default="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        env="USDT_CONTRACT"
    )

    # Blockchain monitoring
    BLOCKCHAIN_MONITORING_ENABLED: bool = Field(default=True,
                                                env="BLOCKCHAIN_MONITORING_ENABLED")
    MIN_BLOCKCHAIN_CONFIRMATIONS: int = Field(default=19,
                                              env="MIN_BLOCKCHAIN_CONFIRMATIONS")

    @property
    def current_confirmations_required(self) -> int:
        """Dynamic confirmations based on environment"""
        return self.MIN_BLOCKCHAIN_CONFIRMATIONS

    @property
    def auto_complete_enabled(self) -> bool:
        """Auto-complete transactions after confirmations"""
        return True

    # Address pool settings
    ADDRESS_MIN_POOL_SIZE: int = Field(default=50, env="ADDRESS_MIN_POOL_SIZE")
    ADDRESS_RESERVATION_MINUTES: int = Field(default=30,
                                             env="ADDRESS_RESERVATION_MINUTES")
    ADDRESS_GRACE_PERIOD_MINUTES: int = Field(default=10,
                                              env="ADDRESS_GRACE_PERIOD_MINUTES")
    ADDRESS_AUTO_CLEANUP_INTERVAL: int = Field(default=60,
                                               env="ADDRESS_AUTO_CLEANUP_INTERVAL")

    # Transaction limits
    MIN_DEPOSIT_AMOUNT: float = Field(default=1.0, env="MIN_DEPOSIT_AMOUNT")
    MAX_DEPOSIT_AMOUNT: float = Field(default=10000.0,
                                      env="MAX_DEPOSIT_AMOUNT")
    MIN_WITHDRAWAL_AMOUNT: float = Field(default=5.0,
                                         env="MIN_WITHDRAWAL_AMOUNT")
    MAX_WITHDRAWAL_AMOUNT: float = Field(default=5000.0,
                                         env="MAX_WITHDRAWAL_AMOUNT")

    # Fees
    WITHDRAWAL_FEE_PERCENTAGE: float = Field(default=0.01,
                                             env="WITHDRAWAL_FEE_PERCENTAGE")  # 1%
    WITHDRAWAL_FEE_MINIMUM: float = Field(default=1.0,
                                          env="WITHDRAWAL_FEE_MINIMUM")  # $1 min
    WITHDRAWAL_FEE_MAXIMUM: float = Field(default=50.0,
                                          env="WITHDRAWAL_FEE_MAXIMUM")  # $50 max

    def calculate_withdrawal_fee(self, amount: float) -> float:
        """Calculate withdrawal fee"""
        fee = amount * self.WITHDRAWAL_FEE_PERCENTAGE
        return max(min(fee, self.WITHDRAWAL_FEE_MAXIMUM),
                   self.WITHDRAWAL_FEE_MINIMUM)

    class Config:
        env_file = ".env"


# Create global settings instance
settings = Settings()