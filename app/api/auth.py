# app/api/auth.py

from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.core_auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    verify_password,
    get_current_user,
    get_current_admin_user
)
from app.models.user import User, Balance
from app.schemas.user import UserCreate, UserResponse, Token, UserLogin, PasswordChange
from app.api.utils import handle_operation_errors, create_success_response
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/login", response_model=Token)
@handle_operation_errors("user login")
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_db)
):
    """User login with username/password"""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    access_token_expires = timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )

    logger.info(f"User {user.username} logged in successfully")

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.post("/register", response_model=UserResponse)
@handle_operation_errors("user registration")
async def register(
        user_data: UserCreate,
        db: Session = Depends(get_db)
):
    """Register new user"""

    # Check if username already exists
    existing_user = db.query(User).filter(
        User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Check if email already exists (if provided)
    if user_data.email:
        existing_email = db.query(User).filter(
            User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

    # Create new user
    user = User(
        username=user_data.username,
        password_hash=get_password_hash(user_data.password),
        email=user_data.email,
        full_name=user_data.full_name,
        is_active=user_data.is_active,
        is_admin=False  # New users are not admin by default
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Create initial balance
    balance = Balance(user_id=user.id, amount=0.0)
    db.add(balance)
    db.commit()

    logger.info(f"New user registered: {user.username}")

    return user


@router.post("/change-password")
@handle_operation_errors("change password")
async def change_password(
        password_data: PasswordChange,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Change user password"""

    # Verify current password
    if not verify_password(password_data.current_password,
                           current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password"
        )

    # Update password
    current_user.password_hash = get_password_hash(password_data.new_password)
    db.commit()

    logger.info(f"User {current_user.username} changed password")

    return create_success_response("password_changed", {
        "message": "Password changed successfully"
    }, current_user.id)


@router.get("/me", response_model=UserResponse)
@handle_operation_errors("get current user")
async def get_current_user_info(
        current_user: User = Depends(get_current_user)
):
    """Get current user information"""
    return current_user


@router.get("/me/balance")
@handle_operation_errors("get user balance")
async def get_user_balance(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Get current user balance"""

    balance = db.query(Balance).filter(
        Balance.user_id == current_user.id).first()
    if not balance:
        # Create balance if doesn't exist
        balance = Balance(user_id=current_user.id, amount=0.0)
        db.add(balance)
        db.commit()
        db.refresh(balance)

    return create_success_response("user_balance", {
        "amount": balance.amount,
        "currency": "USDT",
        "updated_at": balance.updated_at.isoformat()
    }, current_user.id)