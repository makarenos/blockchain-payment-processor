# Blockchain Payment Processor

USDT TRC-20 payment processing system extracted from production gambling platform.

## Features

- USDT TRC-20 integration via TronGrid API
- Wallet pool management with FIFO rotation  
- Transaction monitoring with blockchain confirmations
- Admin dashboard for pool management
- Production-ready with comprehensive error handling

## Quick Start

```bash
git clone https://github.com/makarenos/blockchain-payment-processor.git
cd blockchain-payment-processor
cp .env.example .env

docker-compose up -d
```

Local development:
```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Configuration

```bash
DATABASE_URL=postgresql://user:pass@localhost/blockchain_processor
TRON_API_URL=https://api.trongrid.io
USDT_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
ADDRESS_MIN_POOL_SIZE=50
BLOCKCHAIN_MONITORING_ENABLED=true
JWT_SECRET_KEY=your-secret-key-here
```

## Architecture

- **FastAPI** with async/await pattern
- **PostgreSQL** with SQLAlchemy async drivers
- **Address Pool Service** - FIFO rotation for deposit addresses  
- **Blockchain Monitor** - TronGrid API integration for transaction tracking
- **Admin API** - Pool management and transaction oversight

## License

MIT License