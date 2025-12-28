# app/api/utils.py

import logging
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Callable, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.user import User

logger = logging.getLogger(__name__)


def handle_operation_errors(operation_name: str):
    """Decorator for unified error handling"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error in {operation_name}: {str(e)}",
                             exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to {operation_name}: {str(e)}"
                )

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error in {operation_name}: {str(e)}",
                             exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to {operation_name}: {str(e)}"
                )

        # Return appropriate wrapper based on function type
        if hasattr(func, '__code__') and 'await' in func.__code__.co_names:
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def validate_admin_rights(db: Session, user_id: int) -> None:
    """Validate user has admin rights"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin rights required"
        )


def create_success_response(
        operation: str,
        data: Dict[str, Any],
        user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Create standardized success response"""
    response = {
        "status": "success",
        "operation": operation,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }

    if user_id:
        response["user_id"] = user_id

    return response


def log_admin_operation(
        operation: str,
        admin_id: int,
        details: Optional[Dict[str, Any]] = None
) -> None:
    """Log admin operations for audit"""
    log_entry = {
        "operation": operation,
        "admin_id": admin_id,
        "timestamp": datetime.utcnow().isoformat(),
        "details": details or {}
    }

    logger.info(f"Admin operation: {log_entry}")


def ensure_atomic_operation(func: Callable) -> Callable:
    """Decorator to ensure database operations are atomic"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract db session from kwargs or args
        db = None
        for arg in args:
            if hasattr(arg, 'query'):  # Check if it's a Session
                db = arg
                break

        if 'db' in kwargs:
            db = kwargs['db']

        if not db:
            return func(*args, **kwargs)

        # Use savepoint for nested transaction
        savepoint = db.begin_nested()
        try:
            result = func(*args, **kwargs)
            savepoint.commit()
            return result
        except Exception as e:
            savepoint.rollback()
            logger.error(f"Atomic operation failed: {e}")
            raise

    return wrapper


def validate_transaction_purpose(purpose: str) -> bool:
    """Validate transaction purpose"""
    valid_purposes = [
        "regular",
        "system_withdrawal",
        "system_swift",
        "user_swift",
        "system_tax",
        "tax_payment"
    ]
    return purpose in valid_purposes


def format_currency_amount(amount: float, currency: str = "USDT") -> str:
    """Format currency amount for display"""
    if currency == "USDT":
        return f"{amount:.6f} USDT"
    else:
        return f"{amount:.2f} {currency}"


def validate_address_format(address: str, network: str = "TRC20") -> bool:
    """Validate cryptocurrency address format"""
    if network == "TRC20":
        return bool(address and len(address) == 34 and address.startswith('T'))
    return False


class TransactionError(Exception):
    """Custom exception for transaction-related errors"""
    pass


class AddressPoolError(Exception):
    """Custom exception for address pool-related errors"""
    pass


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass