"""
021 Broker API - Real or Mock
Hybrid implementation: uses real 021 Trade API when enabled, otherwise mock data.
Set USE_REAL_API=true in .env to use real trading API.
"""

import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="021 Broker API Proxy", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USE_REAL_API = os.getenv("USE_REAL_API", "false").lower() == "true"
TRADE021_USERNAME = os.getenv("TRADE021_USERNAME", "")
TRADE021_PASSWORD = os.getenv("TRADE021_PASSWORD", "")
TRADE021_BASE_URL = os.getenv("TRADE021_BASE_URL", "https://devapi.021.trade/api/developer-api/v1")

# 021 Trade API client state
trade_api_token: Optional[str] = None
trade_api_expires: Optional[str] = None

# ---------------------------------------------------------------------------
# Mock Data (used when USE_REAL_API=false)
# ---------------------------------------------------------------------------

MOCK_PORTFOLIO = {
    "account_id": "ACC-021-DEMO",
    "account_name": "Om Ekbote",
    "funds_available": 2_500_000.0,
    "funds_used": 500_000.0,
    "total_value": 3_000_000.0,
}

MOCK_POSITIONS = {
    "RELIANCE.NS": {"quantity": 50, "avg_price": 2840.0, "side": "LONG"},
    "INFY.NS": {"quantity": 100, "avg_price": 1780.0, "side": "LONG"},
    "TCS.NS": {"quantity": 25, "avg_price": 4120.0, "side": "LONG"},
    "HDFCBANK.NS": {"quantity": 75, "avg_price": 1650.0, "side": "LONG"},
}

MOCK_ORDERS: dict = {}

FALLBACK_PRICES = {
    "RELIANCE.NS": 2905.50,
    "INFY.NS": 1823.40,
    "TCS.NS": 4215.75,
    "HDFCBANK.NS": 1698.20,
    "WIPRO.NS": 567.85,
    "SBIN.NS": 832.60,
}

redis_client: Optional[aioredis.Redis] = None


# ---------------------------------------------------------------------------
# 021 Trade API Functions
# ---------------------------------------------------------------------------

async def login_021_api() -> bool:
    """Authenticate with 021 Trade API and store token."""
    global trade_api_token, trade_api_expires

    if not TRADE021_USERNAME or not TRADE021_PASSWORD:
        print("❌ 021 Trade credentials not configured")
        return False

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{TRADE021_BASE_URL}/auth/token",
                json={"username": TRADE021_USERNAME, "password": TRADE021_PASSWORD}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("success") and data.get("data"):
                trade_api_token = data["data"]["accessToken"]
                trade_api_expires = data["data"].get("expiresAt")
                print(f"✅ 021 Trade API authenticated (expires: {trade_api_expires})")
                return True
            else:
                print(f"❌ 021 Trade login failed: {data.get('message')}")
                return False
    except Exception as e:
        print(f"❌ 021 Trade login error: {e}")
        return False


async def call_021_api(method: str, endpoint: str, **kwargs) -> dict:
    """Make authenticated call to 021 Trade API."""
    global trade_api_token

    if not trade_api_token:
        if not await login_021_api():
            raise HTTPException(status_code=503, detail="021 Trade API not available")

    headers = {
        "Authorization": f"Bearer {trade_api_token}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=f"{TRADE021_BASE_URL}{endpoint}",
                headers=headers,
                **kwargs
            )

            # Handle token expiration
            if response.status_code == 401:
                print("🔄 Token expired, re-authenticating...")
                trade_api_token = None
                if await login_021_api():
                    headers["Authorization"] = f"Bearer {trade_api_token}"
                    response = await client.request(
                        method=method,
                        url=f"{TRADE021_BASE_URL}{endpoint}",
                        headers=headers,
                        **kwargs
                    )

            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        print(f"❌ 021 API HTTP error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        print(f"❌ 021 API error: {e}")
        raise HTTPException(status_code=503, detail=f"021 API error: {str(e)}")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    global redis_client

    print("=" * 60)
    print("021 Broker API Proxy Starting...")
    print(f"Mode: {'🔴 REAL 021 Trade API' if USE_REAL_API else '🟢 MOCK DATA'}")
    print("=" * 60)

    # Connect to Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        print("✅ Redis connected")
    except Exception as e:
        print(f"⚠️  Redis not available: {e}")
        redis_client = None

    # Authenticate with 021 Trade if using real API
    if USE_REAL_API:
        if await login_021_api():
            print("✅ Ready to use 021 Trade API")
        else:
            print("⚠️  021 Trade authentication failed, will retry on first request")
    else:
        print("✅ Using mock data (set USE_REAL_API=true for real trading)")


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

async def get_mock_price(symbol: str) -> float:
    """Get price from Redis/yfinance or fallback."""
    if redis_client:
        try:
            val = await redis_client.get(f"price:{symbol}")
            if val:
                return float(val)
        except Exception:
            pass
    base = FALLBACK_PRICES.get(symbol, 1000.0)
    return round(base * (1 + random.uniform(-0.002, 0.002)), 2)


# ---------------------------------------------------------------------------
# API Models
# ---------------------------------------------------------------------------

class PlaceOrderRequest(BaseModel):
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: Optional[float] = None
    trigger_price: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "021-broker-api-proxy",
        "mode": "real" if USE_REAL_API else "mock",
        "authenticated": trade_api_token is not None if USE_REAL_API else None,
        "ts": datetime.now(timezone.utc).isoformat()
    }


@app.get("/account")
async def get_account():
    """Get account summary."""
    if USE_REAL_API:
        # Call real 021 API - Note: endpoint might be different, adjust as needed
        try:
            data = await call_021_api("GET", "/portfolio/positions")
            # Transform to our format if needed
            return data
        except Exception as e:
            print(f"Using fallback due to error: {e}")
            # Fallback to mock if API fails

    # Mock response
    total_position_value = 0.0
    for symbol, pos in MOCK_POSITIONS.items():
        price = await get_mock_price(symbol)
        total_position_value += price * pos["quantity"]

    return {
        "account_id": MOCK_PORTFOLIO["account_id"],
        "account_name": MOCK_PORTFOLIO["account_name"],
        "funds_available": MOCK_PORTFOLIO["funds_available"],
        "funds_used": MOCK_PORTFOLIO["funds_used"],
        "position_value": round(total_position_value, 2),
        "total_value": round(MOCK_PORTFOLIO["funds_available"] + total_position_value, 2),
        "currency": "INR",
    }


@app.get("/positions")
async def get_positions():
    """Get current positions."""
    if USE_REAL_API:
        try:
            result = await call_021_api("GET", "/portfolio/positions")
            if result.get("success") and result.get("data"):
                # Transform 021 Trade format to our format
                positions = []
                for pos in result["data"]:
                    # 021 uses tokens, we use symbols - you may need mapping
                    positions.append({
                        "symbol": f"TOKEN_{pos.get('token')}",  # TODO: map token to symbol
                        "quantity": pos.get("qty", 0),
                        "side": "LONG" if pos.get("qty", 0) > 0 else "SHORT",
                        "avg_price": pos.get("avgPrice", 0) / 100,  # Convert from paise
                        "ltp": pos.get("ltp", 0) / 100,
                        "pnl": pos.get("realizedPnl", 0) / 100,
                        "pnl_pct": 0,  # Calculate if needed
                        "current_value": (pos.get("ltp", 0) / 100) * pos.get("qty", 0)
                    })
                return {"positions": positions}
        except Exception as e:
            print(f"Using fallback due to error: {e}")

    # Mock response
    positions = []
    for symbol, pos in MOCK_POSITIONS.items():
        ltp = await get_mock_price(symbol)
        pnl = (ltp - pos["avg_price"]) * pos["quantity"]
        pnl_pct = ((ltp - pos["avg_price"]) / pos["avg_price"]) * 100
        positions.append({
            "symbol": symbol,
            "quantity": pos["quantity"],
            "side": pos["side"],
            "avg_price": pos["avg_price"],
            "ltp": ltp,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "current_value": round(ltp * pos["quantity"], 2),
        })
    return {"positions": positions}


@app.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """Get live quote."""
    symbol = symbol.upper()

    if USE_REAL_API:
        # TODO: Implement quote fetching from 021 API
        # Note: 021 Trade uses tokens, not symbols
        # You'll need to map symbol to token first
        print(f"⚠️  Real quote API not yet implemented for {symbol}, using mock")

    # Mock response
    price = await get_mock_price(symbol)
    spread = round(price * 0.0001, 2)
    return {
        "symbol": symbol,
        "ltp": price,
        "bid": round(price - spread, 2),
        "ask": round(price + spread, 2),
        "open": round(price * random.uniform(0.995, 1.005), 2),
        "high": round(price * random.uniform(1.001, 1.012), 2),
        "low": round(price * random.uniform(0.988, 0.999), 2),
        "prev_close": round(price * random.uniform(0.993, 1.007), 2),
        "volume": random.randint(50_000, 5_000_000),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/orders")
async def get_orders(status: str = Query(default="ALL")):
    """Get order history."""
    if USE_REAL_API:
        try:
            result = await call_021_api("GET", "/orders")
            if result.get("success"):
                return {"orders": result.get("data", []), "total": len(result.get("data", []))}
        except Exception as e:
            print(f"Using fallback due to error: {e}")

    # Mock response
    orders = list(MOCK_ORDERS.values())
    if status != "ALL":
        orders = [o for o in orders if o["status"] == status]
    orders.sort(key=lambda o: o["created_at"], reverse=True)
    return {"orders": orders, "total": len(orders)}


@app.post("/orders")
async def place_order(req: PlaceOrderRequest):
    """Place an order."""
    if USE_REAL_API:
        print(f"⚠️  Real order placement not yet implemented, using mock")
        # TODO: Implement real order placement
        # Need to convert symbol to token, price to paise, etc.

    # Mock order execution
    symbol = req.symbol.upper()
    ltp = await get_mock_price(symbol)

    # Check idempotency
    for order in MOCK_ORDERS.values():
        if order["client_order_id"] == req.client_order_id:
            return order

    # Simulate execution
    exchange_order_id = f"NSE{random.randint(100000000, 999999999)}"
    fill_scenario = random.choices(["FILLED", "PARTIAL", "REJECTED"], weights=[85, 10, 5])[0]

    if fill_scenario == "FILLED":
        slippage = ltp * random.uniform(-0.0005, 0.0005)
        avg_price = round(ltp + slippage, 2)
        filled_qty = req.quantity
        status = "FILLED"
    elif fill_scenario == "PARTIAL":
        slippage = ltp * random.uniform(-0.001, 0.001)
        avg_price = round(ltp + slippage, 2)
        filled_qty = random.randint(1, req.quantity - 1)
        status = "PARTIAL"
    else:
        avg_price = None
        filled_qty = 0
        status = "REJECTED"

    order = {
        "order_id": str(uuid.uuid4()),
        "client_order_id": req.client_order_id,
        "exchange_order_id": exchange_order_id,
        "symbol": symbol,
        "side": req.side,
        "order_type": req.order_type,
        "quantity": req.quantity,
        "price": req.price,
        "trigger_price": req.trigger_price,
        "filled_quantity": filled_qty,
        "average_price": avg_price,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "filled_at": datetime.now(timezone.utc).isoformat() if fill_scenario != "REJECTED" else None,
        "reject_reason": "Insufficient liquidity" if fill_scenario == "REJECTED" else None,
    }

    MOCK_ORDERS[order["order_id"]] = order
    return order


@app.get("/instruments")
async def get_instruments(search: str = Query(default="")):
    """Search instruments."""
    # TODO: Implement real instrument fetch from 021 API
    # For now, return mock data
    instruments = {
        "RELIANCE.NS": {"name": "Reliance Industries Ltd", "exchange": "NSE", "token": 2885},
        "INFY.NS": {"name": "Infosys Ltd", "exchange": "NSE", "token": 1594},
        "TCS.NS": {"name": "Tata Consultancy Services", "exchange": "NSE", "token": 11536},
        "HDFCBANK.NS": {"name": "HDFC Bank Ltd", "exchange": "NSE", "token": 1333},
    }

    if search:
        search = search.upper()
        instruments = {k: v for k, v in instruments.items() if search in k or search in v["name"].upper()}

    return {"instruments": instruments}
