# app/services/address_pool.py

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import time
import threading
from app.core.config import settings
from app.models.wallet import WalletAddress, AddressReservation, AddressStatusEnum
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)


class AddressPoolService:
    """Service for managing address pool with FIFO rotation"""
    
    DEFAULT_RESERVATION_MINUTES: int = 30
    GRACE_PERIOD_MINUTES: int = 10
    TOTAL_WINDOW_MINUTES: int = 40
    MAX_RETRY_ATTEMPTS: int = 3
    AUTO_RELEASE_CHECK_INTERVAL: int = settings.ADDRESS_AUTO_CLEANUP_INTERVAL

    _auto_release_running: bool = False
    _last_auto_release_run: Optional[datetime] = None
    _auto_release_thread: Optional[threading.Thread] = None

    @staticmethod
    @contextmanager
    def atomic_operation(db: Session):
        """Atomic operation with automatic rollback"""
        savepoint = db.begin_nested()
        try:
            yield
            savepoint.commit()
        except Exception as e:
            savepoint.rollback()
            logger.error(f"Atomic operation failed: {e}")
            raise

    @staticmethod
    def get_available_address_with_retry(
            db: Session,
            user_id: int,
            reservation_minutes: int = None
    ) -> Optional[WalletAddress]:
        """Get address with retry attempts"""
        if reservation_minutes is None:
            reservation_minutes = AddressPoolService.DEFAULT_RESERVATION_MINUTES

        logger.info(f"Getting address for user {user_id}")

        pool_status = AddressPoolService.get_pool_status(db)
        if pool_status["total_addresses"] == 0:
            logger.error("NO ADDRESSES IN DATABASE! Need to add addresses to pool!")
            return None

        if pool_status["active_addresses"] == 0:
            logger.error(f"No active addresses! Reserved: {pool_status['reserved_addresses']}")
            return None

        for attempt in range(AddressPoolService.MAX_RETRY_ATTEMPTS):
            try:
                logger.debug(f"Attempt {attempt + 1}/{AddressPoolService.MAX_RETRY_ATTEMPTS}")
                address = AddressPoolService.get_available_address_atomic(db, user_id, reservation_minutes)
                if address:
                    logger.info(f"Address assigned: {address.address}")
                    return address
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == AddressPoolService.MAX_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(0.1)

        logger.error(f"All attempts failed for user {user_id}")
        return None

    @staticmethod
    def get_available_address_atomic(
            db: Session,
            user_id: int,
            reservation_minutes: int
    ) -> Optional[WalletAddress]:
        """Get available address atomically"""
        with AddressPoolService.atomic_operation(db):
            now = datetime.utcnow()
            expires_at = now + timedelta(minutes=reservation_minutes)

            # FIFO: Get oldest released address first
            available_query = db.query(WalletAddress).filter(
                WalletAddress.status == AddressStatusEnum.active,
                WalletAddress.is_active == True,
                or_(
                    WalletAddress.grace_period_until.is_(None),
                    WalletAddress.grace_period_until <= now
                )
            ).order_by(
                WalletAddress.last_released_at.asc().nulls_first(),
                WalletAddress.id.asc()
            ).with_for_update(skip_locked=True)

            address = available_query.first()
            if not address:
                logger.warning("No available addresses in pool")
                return None

            # Reserve the address
            address.status = AddressStatusEnum.reserved
            address.last_reserved_at = now
            address.usage_count += 1

            # Create reservation record
            reservation = AddressReservation(
                address_id=address.id,
                user_id=user_id,
                expires_at=expires_at,
                status="active"
            )
            db.add(reservation)
            db.flush()

            logger.debug(f"Address {address.id} reserved for user {user_id} until {expires_at}")
            return address

    @staticmethod
    def release_address_atomic(
            db: Session,
            address_id: int,
            transaction_id: int = None
    ) -> bool:
        """Release address with FIFO fields"""
        try:
            with AddressPoolService.atomic_operation(db):
                now = datetime.utcnow()
                logger.debug(f"Releasing address {address_id}")

                address = db.query(WalletAddress).filter(
                    WalletAddress.id == address_id
                ).with_for_update().first()

                if not address:
                    logger.warning(f"Address {address_id} not found")
                    return False

                # Mark reservation as used/expired
                query = db.query(AddressReservation).filter(
                    AddressReservation.address_id == address_id,
                    AddressReservation.status == "active"
                )
                if transaction_id:
                    query = query.filter(AddressReservation.transaction_id == transaction_id)

                reservation = query.with_for_update().first()
                if reservation:
                    reservation.status = "used" if transaction_id else "expired"

                # Release address with FIFO fields
                address.status = AddressStatusEnum.active
                address.last_released_at = now
                address.grace_period_until = now + timedelta(
                    minutes=AddressPoolService.GRACE_PERIOD_MINUTES
                )

                logger.debug(f"Address {address_id} released with grace period until {address.grace_period_until}")
                return True

        except Exception as e:
            logger.error(f"Error releasing address {address_id}: {e}")
            return False

    @staticmethod
    def get_pool_status(db: Session) -> Dict[str, Any]:
        """Get comprehensive pool status"""
        now = datetime.utcnow()
        
        total_addresses = db.query(WalletAddress).filter(WalletAddress.is_active == True).count()
        
        active_addresses = db.query(WalletAddress).filter(
            WalletAddress.status == AddressStatusEnum.active,
            WalletAddress.is_active == True,
            or_(
                WalletAddress.grace_period_until.is_(None),
                WalletAddress.grace_period_until <= now
            )
        ).count()
        
        reserved_addresses = db.query(WalletAddress).filter(
            WalletAddress.status == AddressStatusEnum.reserved,
            WalletAddress.is_active == True
        ).count()
        
        expired_reservations = db.query(AddressReservation).filter(
            AddressReservation.status == "active",
            AddressReservation.expires_at < now
        ).count()

        utilization_percent = 0
        if total_addresses > 0:
            utilization_percent = (reserved_addresses / total_addresses) * 100

        pool_health = "excellent"
        if active_addresses == 0:
            pool_health = "critical"
        elif active_addresses <= settings.POOL_LOW_BALANCE_THRESHOLD:
            pool_health = "warning"
        elif utilization_percent > 90:
            pool_health = "high_utilization"

        return {
            "total_addresses": total_addresses,
            "active_addresses": active_addresses,
            "reserved_addresses": reserved_addresses,
            "inactive_addresses": total_addresses - active_addresses - reserved_addresses,
            "expired_reservations": expired_reservations,
            "utilization_percent": round(utilization_percent, 2),
            "pool_health": pool_health,
            "grace_period_minutes": AddressPoolService.GRACE_PERIOD_MINUTES
        }

    @staticmethod
    def cleanup_expired_reservations(db: Session) -> int:
        """Clean up expired reservations"""
        now = datetime.utcnow()
        
        expired_reservations = db.query(AddressReservation).filter(
            AddressReservation.status == "active",
            AddressReservation.expires_at < now
        ).all()

        cleaned_count = 0
        for reservation in expired_reservations:
            try:
                # Mark reservation as expired
                reservation.status = "expired"
                
                # Release the address if it's still reserved
                address = reservation.address
                if address and address.status == AddressStatusEnum.reserved:
                    address.status = AddressStatusEnum.active
                    address.last_released_at = now
                    address.grace_period_until = now + timedelta(
                        minutes=AddressPoolService.GRACE_PERIOD_MINUTES
                    )
                
                cleaned_count += 1
                
            except Exception as e:
                logger.error(f"Error cleaning reservation {reservation.id}: {e}")
                continue

        if cleaned_count > 0:
            db.commit()
            logger.info(f"Cleaned {cleaned_count} expired reservations")

        return cleaned_count

    @staticmethod
    def add_addresses_to_pool_atomic(db: Session, addresses: List[str]) -> Dict[str, Any]:
        """Add addresses to pool atomically"""
        with AddressPoolService.atomic_operation(db):
            added = 0
            skipped = 0
            errors = []

            for address_str in addresses:
                try:
                    # Validate TRON address
                    if not settings.validate_tron_address(address_str):
                        errors.append(f"Invalid TRON address format: {address_str}")
                        continue

                    # Check duplicates
                    existing = db.query(WalletAddress).filter(
                        WalletAddress.address == address_str
                    ).first()

                    if existing:
                        skipped += 1
                        continue

                    new_address = WalletAddress(
                        address=address_str,
                        status=AddressStatusEnum.active,
                        is_active=True
                    )
                    db.add(new_address)
                    added += 1

                except Exception as e:
                    errors.append(f"Error adding {address_str}: {str(e)}")

            return {
                "added": added,
                "skipped": skipped,
                "errors": errors,
                "total_processed": len(addresses)
            }

    @staticmethod
    def assign_address_to_transaction_atomic(db: Session, transaction_id: int, address_id: int) -> bool:
        """Assign address to transaction"""
        try:
            with AddressPoolService.atomic_operation(db):
                transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
                if not transaction:
                    return False

                reservation = db.query(AddressReservation).filter(
                    AddressReservation.address_id == address_id,
                    AddressReservation.user_id == transaction.user_id,
                    AddressReservation.status == "active"
                ).first()

                if not reservation:
                    return False

                transaction.assigned_address_id = address_id
                transaction.address_expires_at = reservation.expires_at
                reservation.transaction_id = transaction_id
                db.flush()

                logger.info(f"Address {address_id} assigned to transaction {transaction_id}")
                return True

        except Exception as e:
            logger.error(f"Error assigning address {address_id} to transaction {transaction_id}: {e}")
            return False
