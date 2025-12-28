# app/services/blockchain_monitor.py

import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import httpx
import base58
import hashlib
from app.models.wallet import WalletAddress, AddressReservation
from app.models.transaction import Transaction, WithdrawalStatusEnum
from app.core.config import settings

logger = logging.getLogger(__name__)


class BlockchainMonitorService:
    """Service for monitoring TRON blockchain transactions"""

    TRON_API_URL = settings.TRON_API_URL
    USDT_CONTRACT = settings.USDT_CONTRACT
    MAX_RESERVATION_HOURS = 24
    POOL_CHECK_INTERVAL = settings.POOL_HEALTH_CHECK_MINUTES * 60

    @staticmethod
    def tron_address_to_hex(base58_address: str) -> str:
        """Convert TRON address from Base58 to Hex"""
        try:
            decoded = base58.b58decode(base58_address)
            hex_address = decoded[1:-4].hex()
            return '41' + hex_address.lower()
        except Exception as e:
            logger.debug(f"Error converting address to hex: {e}")
            return ""

    @staticmethod
    def hex_to_tron_address(hex_address: str) -> str:
        """Convert Hex address to TRON Base58"""
        try:
            if hex_address.startswith('41'):
                hex_address = hex_address[2:]

            address_bytes = bytes.fromhex('41' + hex_address)
            hash1 = hashlib.sha256(address_bytes).digest()
            hash2 = hashlib.sha256(hash1).digest()
            checksum = hash2[:4]

            full_address = address_bytes + checksum
            return base58.b58encode(full_address).decode()
        except Exception as e:
            logger.debug(f"Error converting hex to address: {e}")
            return ""

    @staticmethod
    async def monitor_addresses(db: Session) -> Dict[str, Any]:
        """Monitor all reserved addresses for incoming transactions"""
        logger.info(f"Starting blockchain monitoring cycle (Token: {settings.current_token})")

        active_reservations = db.query(AddressReservation).join(
            WalletAddress, AddressReservation.address_id == WalletAddress.id
        ).join(
            Transaction, AddressReservation.transaction_id == Transaction.id
        ).filter(
            AddressReservation.status == "active",
            AddressReservation.expires_at > datetime.utcnow(),
            AddressReservation.transaction_id.isnot(None)
        ).all()

        if not active_reservations:
            logger.info("No active reservations with transactions to monitor")
            return {"monitored": 0, "processed": 0}

        processed_count = 0

        for reservation in active_reservations:
            try:
                if not reservation.transaction:
                    logger.warning(f"Reservation {reservation.id} has no transaction, skipping")
                    continue

                if not reservation.address:
                    logger.warning(f"Reservation {reservation.id} has no address, skipping")
                    continue

                address = reservation.address.address
                expected_amount = reservation.transaction.amount

                transactions = await BlockchainMonitorService._get_incoming_transactions(
                    address, expected_amount
                )

                if transactions:
                    logger.info(f"Found {len(transactions)} matching transactions for {address}")
                    processed_count += 1
                    # Process transaction confirmation logic here

            except Exception as e:
                logger.error(f"Error monitoring reservation {reservation.id}: {e}")
                continue

        try:
            db.commit()
            logger.debug("Blockchain monitoring changes committed successfully")
        except Exception as e:
            logger.error(f"Failed to commit blockchain monitoring changes: {e}")
            db.rollback()
            raise

        return {
            "monitored": len(active_reservations),
            "processed": processed_count,
            "token": settings.current_token
        }

    @staticmethod
    async def _get_incoming_transactions(address: str, expected_amount: float) -> List[Dict]:
        """Get incoming transactions for address"""
        try:
            logger.info(f"Checking {settings.current_token} transactions for {address}, expected: {expected_amount}")

            async with httpx.AsyncClient() as client:
                if settings.is_monitoring_trx:
                    return await BlockchainMonitorService._get_trx_transactions(
                        client, address, expected_amount
                    )
                else:
                    return await BlockchainMonitorService._get_usdt_transactions(
                        client, address, expected_amount
                    )

        except Exception as e:
            logger.error(f"Error getting transactions for address {address}: {str(e)}")
            return []

    @staticmethod
    async def _get_usdt_transactions(client: httpx.AsyncClient, address: str, expected_amount: float) -> List[Dict]:
        """Get USDT TRC20 transactions"""
        try:
            logger.info(f"Checking USDT transactions for {address}, expected: {expected_amount} USDT")

            url = f"{BlockchainMonitorService.TRON_API_URL}/v1/accounts/{address}/transactions/trc20"
            params = {
                "limit": 20,
                "contract_address": BlockchainMonitorService.USDT_CONTRACT,
                "only_confirmed": True,
                "only_to": True
            }

            headers = settings.get_api_headers()
            logger.info(f"API Request: {url} with params {params}")

            response = await client.get(url, params=params, headers=headers, timeout=15.0)
            response.raise_for_status()

            data = response.json()

            if not data.get("success", True):
                logger.error(f"API Error: {data}")
                return []

            transactions = data.get("data", [])
            matching_transfers = []

            for tx in transactions:
                try:
                    token_info = tx.get("token_info", {})
                    if token_info.get("symbol") != "USDT":
                        continue

                    value_raw = tx.get("value", "0")
                    amount_usdt = float(value_raw) / (10 ** 6)  # USDT has 6 decimals

                    if abs(amount_usdt - expected_amount) < 0.000001:
                        matching_transfers.append({
                            "txid": tx.get("transaction_id"),
                            "amount": amount_usdt,
                            "from": tx.get("from"),
                            "to": tx.get("to"),
                            "timestamp": tx.get("block_timestamp"),
                            "confirmations": tx.get("confirmations", 0)
                        })

                except Exception as e:
                    logger.error(f"Error parsing transaction: {e}")
                    continue

            logger.info(f"Found {len(matching_transfers)} matching USDT transfers")
            return matching_transfers

        except Exception as e:
            logger.error(f"Error getting USDT transactions: {str(e)}")
            return []

    @staticmethod
    async def _get_trx_transactions(client: httpx.AsyncClient, address: str, expected_amount: float) -> List[Dict]:
        """Get native TRX transactions"""
        try:
            logger.info(f"Checking TRX transactions for {address}, expected: {expected_amount} TRX")

            url = f"{BlockchainMonitorService.TRON_API_URL}/v1/accounts/{address}/transactions"
            params = {
                "limit": 20,
                "only_confirmed": True,
                "only_to": True
            }

            headers = settings.get_api_headers()
            logger.info(f"API Request: {url} with params {params}")

            response = await client.get(url, params=params, headers=headers, timeout=15.0)
            response.raise_for_status()

            data = response.json()

            if not data.get("success", True):
                logger.error(f"API Error: {data}")
                return []

            transactions = data.get("data", [])
            matching_transfers = []

            for tx in transactions:
                try:
                    raw_data = tx.get("raw_data", {})
                    contract = raw_data.get("contract", [{}])[0]

                    if contract.get("type") != "TransferContract":
                        continue

                    parameter = contract.get("parameter", {})
                    value = parameter.get("value", {})

                    amount_raw = value.get("amount", 0)
                    amount_trx = float(amount_raw) / (10 ** 6)  # TRX has 6 decimals

                    if abs(amount_trx - expected_amount) < 0.000001:
                        matching_transfers.append({
                            "txid": tx.get("txID"),
                            "amount": amount_trx,
                            "from": value.get("owner_address"),
                            "to": value.get("to_address"),
                            "timestamp": raw_data.get("timestamp"),
                            "confirmations": tx.get("confirmations", 0)
                        })

                except Exception as e:
                    logger.error(f"Error parsing transaction: {e}")
                    continue

            logger.info(f"Found {len(matching_transfers)} matching TRX transfers")
            return matching_transfers

        except Exception as e:
            logger.error(f"Error getting TRX transactions: {str(e)}")
            return []
