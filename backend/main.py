"""
Syrus Backend — Main FastAPI Application
"""
from contextlib import asynccontextmanager
import asyncio

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db import init_db
from services.price_poller import PricePoller


# Global redis client shared across services
redis_client: aioredis.Redis = None
price_poller: PricePoller = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global redis_client, price_poller

    # Connect Redis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis_client
    print("✅ Redis connected")

    # Init DB
    await init_db()
    print("✅ Database ready")

    # Start price poller (pushes yfinance prices to Redis every 15s)
    price_poller = PricePoller(redis_client)
    poller_task = asyncio.create_task(price_poller.start())
    print("✅ Price poller started")

    yield  # App runs here

    # Cleanup
    poller_task.cancel()
    await redis_client.aclose()
    print("Syrus backend shut down cleanly.")


app = FastAPI(
    title="Syrus AI Trading Copilot API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers
from routers import chat, orders, instructions, audit

app.include_router(chat.router,         prefix="/chat",         tags=["Chat"])
app.include_router(orders.router,       prefix="/orders",       tags=["Orders"])
app.include_router(instructions.router, prefix="/instructions", tags=["Standing Instructions"])
app.include_router(audit.router,        prefix="/audit",        tags=["Audit"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "syrus-backend"}


@app.get("/")
async def root():
    return {"message": "Syrus AI Trading Copilot — backend running"}
