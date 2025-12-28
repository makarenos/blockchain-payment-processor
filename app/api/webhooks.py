# app/api/webhooks.py

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any
from app.core.database import get_db
from app.services.webhook_handlers import WebhookHandlers
from app.api.utils import handle_operation_errors
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/payment")
@handle_operation_errors("process payment webhook")
async def payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle payment system webhook"""
    return await WebhookHandlers.handle_payment_webhook(request, background_tasks, db)


@router.post("/blockchain")
@handle_operation_errors("process blockchain webhook")
async def blockchain_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle blockchain confirmation webhook"""
    return await WebhookHandlers.handle_blockchain_webhook(request, background_tasks, db)


@router.get("/health")
async def webhook_health():
    """Webhook endpoint health check"""
    return {
        "status": "healthy",
        "service": "webhook_handler",
        "endpoints": [
            "/webhooks/payment",
            "/webhooks/blockchain"
        ]
    }