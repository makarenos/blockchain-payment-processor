# tests/test_auth.py

import pytest
from fastapi.testclient import TestClient
from app.core.core_auth import verify_password, get_password_hash, \
    create_access_token, verify_token
from app.models.user import User, Balance


class TestAuthService:
    """Test authentication service functions"""

    def test_password_hashing(self):
        """Test password hashing and verification"""
        password = "testpassword123"
        hashed = get_password_hash(password)

        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrongpassword", hashed) is False

    def test_jwt_token_creation_and_verification(self):
        """Test JWT token creation and verification"""
        data = {"sub": "123", "username": "testuser"}
        token = create_access_token(data)

        assert token is not None
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "123"
        assert payload["username"] == "testuser"

    def test_invalid_token_verification(self):
        """Test verification of invalid token"""
        invalid_token = "invalid.token.here"
        payload = verify_token(invalid_token)
        assert payload is None


class TestAuthAPI:
    """Test authentication API endpoints"""

    def test_user_registration_success(self, client: TestClient, db):
        """Test successful user registration"""
        user_data = {
            "username": "newuser",
            "password": "newpass123",
            "email": "newuser@example.com",
            "full_name": "New User"
        }

        response = client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        data = response.json()
        assert data["username"] == user_data["username"]
        assert data["email"] == user_data["email"]
        assert data["is_admin"] is False
        assert "password" not in data

    def test_user_login_success(self, client: TestClient, test_user):
        """Test successful login"""
        login_data = {
            "username": test_user.username,
            "password": "testpass123"
        }

        response = client.post("/api/auth/login", data=login_data)
        assert response.status_code == 200

        data = response.json()
        assert data["access_token"] is not None
        assert data["token_type"] == "bearer"

    def test_user_login_wrong_password(self, client: TestClient, test_user):
        """Test login with wrong password"""
        login_data = {
            "username": test_user.username,
            "password": "wrongpassword"
        }

        response = client.post("/api/auth/login", data=login_data)
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]

    def test_get_current_user_info(self, client: TestClient, auth_headers,
                                   test_user):
        """Test getting current user info"""
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == test_user.id
        assert data["username"] == test_user.username
        assert data["email"] == test_user.email
        assert "password" not in data

    def test_get_current_user_unauthorized(self, client: TestClient):
        """Test getting user info without auth"""
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_get_user_balance(self, client: TestClient, auth_headers,
                              test_user):
        """Test getting user balance"""
        response = client.get("/api/auth/me/balance", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["amount"] == 1000.0
        assert data["data"]["currency"] == "USDT"


class TestAuthValidation:
    """Test authentication validation"""

    def test_registration_duplicate_username(self, client: TestClient,
                                             test_user):
        """Test registration with duplicate username"""
        user_data = {
            "username": test_user.username,  # duplicate
            "password": "newpass123",
            "email": "different@example.com"
        }

        response = client.post("/api/auth/register", json=user_data)
        assert response.status_code == 400
        assert "Username already registered" in response.json()["detail"]

    def test_registration_weak_password(self, client: TestClient):
        """Test registration with weak password"""
        user_data = {
            "username": "newuser",
            "password": "123",  # too weak
            "email": "newuser@example.com"
        }

        response = client.post("/api/auth/register", json=user_data)
        assert response.status_code == 422

    def test_login_nonexistent_user(self, client: TestClient):
        """Test login with nonexistent user"""
        login_data = {
            "username": "nonexistent",
            "password": "password123"
        }

        response = client.post("/api/auth/login", data=login_data)
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]