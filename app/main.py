# app/main.py

import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.config import settings
from app.core.database import get_db

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="USDT TRC-20 payment processing system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.error(f"Unhandled error in middleware: {str(exc)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

# TODO: Import and include routers
# from app.api.deposits import router as deposits_router
# from app.api.withdrawals import router as withdrawals_router
# from app.api.admin import router as admin_router

# app.include_router(deposits_router, prefix="/api/deposits", tags=["deposits"])
# app.include_router(withdrawals_router, prefix="/api/withdrawals", tags=["withdrawals"])
# app.include_router(admin_router, prefix="/api/admin", tags=["admin"])

@app.get("/", tags=["status"])
def root():
    return {
        "status": "ok",
        "version": "1.0.0",
        "service": settings.PROJECT_NAME
    }

@app.get("/health", tags=["status"])
def health_check():
    return {
        "status": "healthy",
        "timestamp": str(logging.datetime.datetime.utcnow()),
        "blockchain_monitoring": settings.BLOCKCHAIN_MONITORING_ENABLED,
        "pool_size": settings.ADDRESS_MIN_POOL_SIZE
    }

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(f"HTTPException {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body}
    )

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.PROJECT_NAME}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Blockchain monitoring: {settings.BLOCKCHAIN_MONITORING_ENABLED}")
    
    # TODO: Initialize services
    # start_blockchain_monitoring()
    # start_address_auto_cleanup()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"Shutting down {settings.PROJECT_NAME}")
    
    # TODO: Cleanup services
    # stop_blockchain_monitoring()
    # stop_address_auto_cleanup()
