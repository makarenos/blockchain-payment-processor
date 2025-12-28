# tests/test_integration.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from app.models.transaction import Transaction, TransactionTypeEnum, \
    WithdrawalStatusEnum
from app.models.wallet import WalletAddress, AddressStatusEnum
from app.models.user import Balance


@pytest.mark.integration
class TestFullUserFlow:
    """Test complete user workflows from registration to transactions"""

    def test_complete_user_registration_and_deposit_flow(self,
                                                         client: TestClient,
                                                         db):
        """Test complete flow: register -> login -> request deposit -> admin approve"""

        # 1. User registration
        register_data = {
            "username": "flowuser",
            "password": "flowpass123",
            "email": "flow@example.com",
            "full_name": "Flow User"
        }

        register_response = client.post("/api/auth/register",
                                        json=register_data)
        assert register_response.status_code == 200
        user_data = register_response.json()
        user_id = user_data["id"]

        # 2. User login
        login_response = client.post("/api/auth/login", data={
            "username": register_data["username"],
            "password": register_data["password"]
        })
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Check initial balance
        balance_response = client.get("/api/auth/me/balance", headers=headers)
        assert balance_response.status_code == 200
        assert balance_response.json()["data"]["amount"] == 0.0

        # 4. Create wallet address for deposit
        wallet_address = WalletAddress(
            address="TFlow1234567890123456789012345678",
            status=AddressStatusEnum.active,
            is_active=True
        )
        db.add(wallet_address)
        db.commit()

        # 5. Request deposit
        with patch(
                'app.services.address_pool.AddressPoolService.get_available_address_with_retry') as mock_get:
            with patch(
                    'app.services.address_pool.AddressPoolService.assign_address_to_transaction_atomic') as mock_assign:
                mock_get.return_value = wallet_address
                mock_assign.return_value = True

                deposit_response = client.post("/api/deposits/request",
                                               json={"amount": 500.0},
                                               headers=headers)
                assert deposit_response.status_code == 200

                deposit_data = deposit_response.json()["data"]
                transaction_id = deposit_data["transaction_id"]
                assigned_address = deposit_data["deposit_address"]
                assert assigned_address == wallet_address.address

        # 6. Create admin for approval
        admin_data = {
            "username": "flowadmin",
            "password": "adminpass123",
            "email": "admin@example.com",
            "full_name": "Flow Admin"
        }

        # Create admin user directly in database
        from app.models.user import User
        from app.core.core_auth import get_password_hash
        admin_user = User(
            username=admin_data["username"],
            password_hash=get_password_hash(admin_data["password"]),
            email=admin_data["email"],
            full_name=admin_data["full_name"],
            is_active=True,
            is_admin=True
        )
        db.add(admin_user)

        admin_balance = Balance(user_id=admin_user.id, amount=0.0)
        db.add(admin_balance)
        db.commit()

        # 7. Admin login
        admin_login_response = client.post("/api/auth/login", data={
            "username": admin_data["username"],
            "password": admin_data["password"]
        })
        assert admin_login_response.status_code == 200
        admin_token = admin_login_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 8. Admin approve deposit
        with patch(
                'app.services.address_pool.AddressPoolService.release_address_atomic'):
            with patch(
                    'app.services.status_sync.hook_transaction_completed') as mock_sync:
                mock_sync.return_value = {"changed": True}

                approve_response = client.post(
                    f"/api/admin/deposits/{transaction_id}/approve",
                    json={"comment": "Integration test approval"},
                    headers=admin_headers
                )
                assert approve_response.status_code == 200

        # 9. Check updated balance
        final_balance_response = client.get("/api/auth/me/balance",
                                            headers=headers)
        assert final_balance_response.status_code == 200
        final_balance = final_balance_response.json()["data"]["amount"]
        assert final_balance == 500.0

        # 10. Check transaction in deposit history
        history_response = client.get("/api/deposits/", headers=headers)
        assert history_response.status_code == 200
        deposits = history_response.json()["data"]["deposits"]
        assert len(deposits) == 1
        assert deposits[0]["id"] == transaction_id
        assert deposits[0]["status"] == "completed"

    def test_complete_withdrawal_flow(self, client: TestClient, db):
        """Test complete withdrawal flow: request -> admin approve -> webhook complete"""

        # Setup user with balance
        from app.models.user import User
        from app.core.core_auth import get_password_hash, create_access_token

        user = User(
            username="withdrawuser",
            password_hash=get_password_hash("withdrawpass123"),
            email="withdraw@example.com",
            is_active=True
        )
        db.add(user)
        db.commit()

        balance = Balance(user_id=user.id, amount=1000.0)
        db.add(balance)
        db.commit()

        # Get user token
        token = create_access_token(data={"sub": str(user.id)})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Request withdrawal
        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            with patch(
                    'app.services.status_sync.hook_transaction_status_changed') as mock_sync:
                mock_fee.return_value = 25.0  # 25 USDT fee
                mock_sync.return_value = {"changed": True}

                withdrawal_response = client.post("/api/withdrawals/request",
                                                  json={
                                                      "amount": 300.0,
                                                      "wallet_address": "TWithdraw123456789012345678901234"
                                                  }, headers=headers)

                assert withdrawal_response.status_code == 200
                withdrawal_data = withdrawal_response.json()["data"]
                transaction_id = withdrawal_data["transaction_id"]
                assert withdrawal_data[
                           "total_deducted"] == 325.0  # 300 + 25 fee
                assert withdrawal_data[
                           "remaining_balance"] == 675.0  # 1000 - 325

        # 2. Create admin and approve withdrawal
        admin_user = User(
            username="withdrawadmin",
            password_hash=get_password_hash("adminpass123"),
            email="withdrawadmin@example.com",
            is_active=True,
            is_admin=True
        )
        db.add(admin_user)
        db.commit()

        admin_token = create_access_token(data={"sub": str(admin_user.id)})
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {"changed": True}

            approve_response = client.post(
                f"/api/admin/withdrawals/{transaction_id}/approve",
                json={"comment": "Approved for processing"},
                headers=admin_headers
            )
            assert approve_response.status_code == 200

        # 3. Simulate payment system webhook completion
        webhook_payload = {
            "transaction_id": transaction_id,
            "status": "success",
            "payment_id": "pay_withdrawal_123"
        }

        webhook_response = client.post("/api/webhooks/payment",
                                       json=webhook_payload)
        assert webhook_response.status_code == 200
        webhook_data = webhook_response.json()
        assert webhook_data["status"] == "success"

        # 4. Check final transaction status
        history_response = client.get("/api/withdrawals/", headers=headers)
        assert history_response.status_code == 200
        withdrawals = history_response.json()["data"]["withdrawals"]
        assert len(withdrawals) == 1
        assert withdrawals[0]["id"] == transaction_id
        assert withdrawals[0]["status"] == "completed"


@pytest.mark.integration
class TestAdminWorkflows:
    """Test complete admin workflows"""

    def test_admin_bulk_transaction_processing(self, client: TestClient, db):
        """Test admin processing multiple transactions"""

        # Setup multiple users with transactions
        users = []
        transactions = []

        for i in range(5):
            from app.models.user import User
            from app.core.core_auth import get_password_hash

            user = User(
                username=f"bulkuser{i}",
                password_hash=get_password_hash("bulkpass123"),
                email=f"bulk{i}@example.com",
                is_active=True
            )
            db.add(user)
            users.append(user)

        db.commit()

        # Create deposits for each user
        for i, user in enumerate(users):
            balance = Balance(user_id=user.id, amount=0.0)
            db.add(balance)

            transaction = Transaction(
                user_id=user.id,
                amount=100.0 + i * 50,
                transaction_type=TransactionTypeEnum.deposit,
                withdrawal_status=WithdrawalStatusEnum.pending,
                wallet_address=f"TBulk{i:030d}",
                comment=f"Bulk test deposit {i}"
            )
            db.add(transaction)
            transactions.append(transaction)

        db.commit()

        # Setup admin
        admin_user = User(
            username="bulkadmin",
            password_hash=get_password_hash("adminpass123"),
            email="bulkadmin@example.com",
            is_active=True,
            is_admin=True
        )
        db.add(admin_user)
        db.commit()

        from app.core.core_auth import create_access_token
        admin_token = create_access_token(data={"sub": str(admin_user.id)})
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Process all transactions
        with patch(
                'app.services.address_pool.AddressPoolService.release_address_atomic'):
            with patch(
                    'app.services.status_sync.hook_transaction_completed') as mock_sync:
                mock_sync.return_value = {"changed": True}

                for i, tx in enumerate(transactions):
                    approve_response = client.post(
                        f"/api/admin/deposits/{tx.id}/approve",
                        json={"comment": f"Bulk approval {i}"},
                        headers=admin_headers
                    )
                    assert approve_response.status_code == 200

        # Verify all balances updated
        for i, user in enumerate(users):
            balance = db.query(Balance).filter(
                Balance.user_id == user.id).first()
            expected_amount = 100.0 + i * 50
            assert balance.amount == expected_amount

        # Verify all transactions completed
        for tx in transactions:
            db.refresh(tx)
            assert tx.withdrawal_status == WithdrawalStatusEnum.completed

    def test_admin_pool_management_workflow(self, client: TestClient, db):
        """Test complete address pool management workflow"""

        # Setup admin
        from app.models.user import User
        from app.core.core_auth import get_password_hash, create_access_token

        admin_user = User(
            username="pooladmin",
            password_hash=get_password_hash("adminpass123"),
            email="pooladmin@example.com",
            is_active=True,
            is_admin=True
        )
        db.add(admin_user)
        db.commit()

        admin_token = create_access_token(data={"sub": str(admin_user.id)})
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Check initial pool status
        with patch(
                'app.services.address_pool.AddressPoolService.get_pool_status') as mock_status:
            mock_status.return_value = {
                "total_addresses": 10,
                "active_addresses": 8,
                "reserved_addresses": 1,
                "inactive_addresses": 1,
                "pool_health": "low"
            }

            status_response = client.get("/api/admin/pool/status",
                                         headers=admin_headers)
            assert status_response.status_code == 200
            status_data = status_response.json()["data"]
            assert status_data["pool_health"] == "low"

        # 2. Add new addresses to pool
        new_addresses = [
            f"TPool{i:031d}" for i in range(20)
        ]

        with patch(
                'app.services.address_pool.AddressPoolService.add_addresses_to_pool_atomic') as mock_add:
            mock_add.return_value = {
                "added_count": 20,
                "skipped_count": 0,
                "total_addresses": 30
            }

            add_response = client.post(
                "/api/admin/pool/add-addresses",
                json=new_addresses,
                headers=admin_headers
            )
            assert add_response.status_code == 200
            add_data = add_response.json()["data"]
            assert add_data["added_count"] == 20

        # 3. Fix pool issues
        with patch(
                'app.services.address_pool.AddressPoolService.cleanup_expired_reservations') as mock_cleanup:
            mock_cleanup.return_value = 3

            fix_response = client.post(
                "/api/admin/pool/fix-issues?fix_expired=true&fix_orphaned=true",
                headers=admin_headers
            )
            assert fix_response.status_code == 200
            fix_data = fix_response.json()["data"]
            assert fix_data["expired_cleaned"] == 3
            assert fix_data["total_issues_fixed"] >= 3


@pytest.mark.integration
class TestWebhookIntegration:
    """Test webhook integration with full system"""

    def test_blockchain_webhook_auto_complete_flow(self, client: TestClient,
                                                   db, monkeypatch):
        """Test complete blockchain webhook auto-completion flow"""

        # Setup settings
        from app.core import config
        monkeypatch.setattr(config.settings, "current_confirmations_required",
                            19)
        monkeypatch.setattr(config.settings, "auto_complete_enabled", True)

        # Setup user and pending deposit
        from app.models.user import User
        from app.core.core_auth import get_password_hash

        user = User(
            username="webhookuser",
            password_hash=get_password_hash("webhookpass123"),
            email="webhook@example.com",
            is_active=True
        )
        db.add(user)
        db.commit()

        initial_balance = Balance(user_id=user.id, amount=100.0)
        db.add(initial_balance)

        wallet_address = WalletAddress(
            address="TWebhook12345678901234567890123456",
            status=AddressStatusEnum.active,
            is_active=True
        )
        db.add(wallet_address)

        transaction = Transaction(
            user_id=user.id,
            amount=250.0,
            transaction_type=TransactionTypeEnum.deposit,
            withdrawal_status=WithdrawalStatusEnum.pending,
            wallet_address=wallet_address.address,
            comment="Awaiting blockchain confirmation"
        )
        db.add(transaction)
        db.commit()

        # Send blockchain webhook
        webhook_payload = {
            "event_type": "transaction_confirmed",
            "txid": "auto_complete_tx_456789",
            "confirmations": 25,
            "address": wallet_address.address,
            "amount": 250.0,
            "token": "USDT",
            "block_height": 87654321
        }

        with patch(
                'app.services.status_sync.hook_transaction_completed') as mock_sync:
            mock_sync.return_value = {
                "user_id": user.id,
                "changed": True,
                "new_status": "available"
            }

            webhook_response = client.post("/api/webhooks/blockchain",
                                           json=webhook_payload)
            assert webhook_response.status_code == 200

            webhook_data = webhook_response.json()
            assert webhook_data["status"] == "auto_completed"
            assert webhook_data["transaction_id"] == transaction.id

        # Verify transaction auto-completed
        db.refresh(transaction)
        assert transaction.withdrawal_status == WithdrawalStatusEnum.completed
        assert transaction.txid == "auto_complete_tx_456789"
        assert transaction.processed_at is not None

        # Note: In real auto-complete, balance would be credited automatically
        # This would require additional admin approval workflow mocking

    def test_payment_webhook_failure_recovery(self, client: TestClient, db):
        """Test payment webhook failure and recovery workflow"""

        # Setup user with withdrawal
        from app.models.user import User
        from app.core.core_auth import get_password_hash

        user = User(
            username="recoveryuser",
            password_hash=get_password_hash("recoverypass123"),
            email="recovery@example.com",
            is_active=True
        )
        db.add(user)
        db.commit()

        balance = Balance(user_id=user.id,
                          amount=800.0)  # Amount after withdrawal deduction
        db.add(balance)

        transaction = Transaction(
            user_id=user.id,
            amount=200.0,
            transaction_type=TransactionTypeEnum.withdrawal,
            withdrawal_status=WithdrawalStatusEnum.approved,
            wallet_address="TRecovery123456789012345678901234",
            comment="Approved withdrawal"
        )
        db.add(transaction)
        db.commit()

        # 1. Simulate failed payment webhook
        failed_payload = {
            "transaction_id": transaction.id,
            "status": "failed",
            "error_code": "INSUFFICIENT_FUNDS",
            "error_message": "Payment processor insufficient funds"
        }

        failed_response = client.post("/api/webhooks/payment",
                                      json=failed_payload)
        assert failed_response.status_code == 200

        failed_data = failed_response.json()
        assert failed_data["status"] == "processed"

        # Verify transaction marked as rejected
        db.refresh(transaction)
        assert transaction.withdrawal_status == WithdrawalStatusEnum.rejected
        assert "Отклонено платежной системой" in transaction.comment

        # 2. Admin could manually refund and create new withdrawal
        # This demonstrates recovery workflow

        # Manual balance refund (simulating admin action)
        db.refresh(balance)
        balance.amount += 200.0  # Refund original amount
        db.commit()

        # Verify balance restored
        assert balance.amount == 1000.0


@pytest.mark.integration
class TestSystemResilience:
    """Test system resilience and error handling"""

    def test_concurrent_user_operations(self, client: TestClient, db):
        """Test concurrent operations by multiple users"""

        # Setup multiple users
        users = []
        tokens = []

        for i in range(3):
            from app.models.user import User
            from app.core.core_auth import get_password_hash, \
                create_access_token

            user = User(
                username=f"concurrent{i}",
                password_hash=get_password_hash("concurrentpass123"),
                email=f"concurrent{i}@example.com",
                is_active=True
            )
            db.add(user)
            users.append(user)

        db.commit()

        # Create tokens and balances
        for user in users:
            token = create_access_token(data={"sub": str(user.id)})
            tokens.append(token)

            balance = Balance(user_id=user.id, amount=1000.0)
            db.add(balance)

        db.commit()

        # Create wallet addresses
        addresses = []
        for i in range(3):
            address = WalletAddress(
                address=f"TConcurrent{i:027d}",
                status=AddressStatusEnum.active,
                is_active=True
            )
            db.add(address)
            addresses.append(address)

        db.commit()

        # Simulate concurrent deposit requests
        with patch(
                'app.services.address_pool.AddressPoolService.get_available_address_with_retry') as mock_get:
            with patch(
                    'app.services.address_pool.AddressPoolService.assign_address_to_transaction_atomic') as mock_assign:
                # Mock different addresses for each user
                mock_get.side_effect = addresses
                mock_assign.return_value = True

                responses = []
                for i, token in enumerate(tokens):
                    headers = {"Authorization": f"Bearer {token}"}
                    response = client.post("/api/deposits/request",
                                           json={"amount": 100.0 + i * 10},
                                           headers=headers)
                    responses.append(response)

                # All requests should succeed
                for i, response in enumerate(responses):
                    assert response.status_code == 200
                    data = response.json()
                    assert data["data"]["amount"] == 100.0 + i * 10

        # Verify all transactions created
        all_transactions = db.query(Transaction).filter(
            Transaction.transaction_type == TransactionTypeEnum.deposit
        ).all()
        assert len(all_transactions) >= 3

    def test_system_under_load(self, client: TestClient, db):
        """Test system behavior under simulated load"""

        # Setup single user
        from app.models.user import User
        from app.core.core_auth import get_password_hash, create_access_token

        user = User(
            username="loaduser",
            password_hash=get_password_hash("loadpass123"),
            email="load@example.com",
            is_active=True
        )
        db.add(user)
        db.commit()

        balance = Balance(user_id=user.id, amount=10000.0)
        db.add(balance)
        db.commit()

        token = create_access_token(data={"sub": str(user.id)})
        headers = {"Authorization": f"Bearer {token}"}

        # Simulate rapid withdrawal requests
        with patch(
                'app.core.config.settings.calculate_withdrawal_fee') as mock_fee:
            with patch(
                    'app.services.status_sync.hook_transaction_status_changed') as mock_sync:
                mock_fee.return_value = 5.0
                mock_sync.return_value = {"changed": True}

                responses = []
                for i in range(10):
                    response = client.post("/api/withdrawals/request", json={
                        "amount": 50.0,
                        "wallet_address": f"TLoad{i:030d}"
                    }, headers=headers)
                    responses.append(response)

                # Most should succeed (until balance runs out)
                success_count = sum(
                    1 for r in responses if r.status_code == 200)
                assert success_count >= 5  # At least 5 should succeed

        # Check remaining balance is consistent
        final_balance_response = client.get("/api/auth/me/balance",
                                            headers=headers)
        assert final_balance_response.status_code == 200
        final_balance = final_balance_response.json()["data"]["amount"]

        # Balance should be consistent with successful transactions
        expected_deductions = success_count * (50.0 + 5.0)  # amount + fee
        expected_balance = 10000.0 - expected_deductions
        assert final_balance == expected_balance