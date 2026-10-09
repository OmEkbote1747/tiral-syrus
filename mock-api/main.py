"""
Mock 021 Broker API
Simulates the 021 trading platform REST endpoints.
Prices are injected from the backend price feed (yfinance via Redis).
Order execution is simulated with realistic fills and partial fills.
"""

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Mock 021 Broker API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory state (resets on restart — good enough for a demo)
# ---------------------------------------------------------------------------

MOCK_PORTFOLIO = {
    "account_id": "ACC-021-DEMO",
    "account_name": "Om Ekbote",
    "funds_available": 2_500_000.0,   # ₹25 lakh
    "funds_used":        500_000.0,
    "total_value":     3_000_000.0,
}

MOCK_POSITIONS = {
    "RELIANCE.NS": {"quantity": 50,  "avg_price": 2840.0, "side": "LONG"},
    "INFY.NS":     {"quantity": 100, "avg_price": 1780.0, "side": "LONG"},
    "TCS.NS":      {"quantity": 25,  "avg_price": 4120.0, "side": "LONG"},
    "HDFCBANK.NS": {"quantity": 75,  "avg_price": 1650.0, "side": "LONG"},
}

MOCK_ORDERS: dict = {}   # order_id -> order dict

INSTRUMENT_MASTER = {
    "RELIANCE.NS": {"name": "Reliance Industries Ltd", "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "INFY.NS":     {"name": "Infosys Ltd",             "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "TCS.NS":      {"name": "Tata Consultancy Services","exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "HDFCBANK.NS": {"name": "HDFC Bank Ltd",           "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "WIPRO.NS":    {"name": "Wipro Ltd",               "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "SBIN.NS":     {"name": "State Bank of India",     "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "BAJFINANCE.NS":{"name": "Bajaj Finance Ltd",      "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "ICICIBANK.NS":{"name": "ICICI Bank Ltd",          "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "AXISBANK.NS": {"name": "Axis Bank Ltd",           "exchange": "NSE", "lot_size": 1,  "tick_size": 0.05},
    "NIFTY50":     {"name": "Nifty 50 Index",          "exchange": "NSE", "lot_size": 50, "tick_size": 0.05},
}

# Fallback prices used if Redis/yfinance data isn't available yet
FALLBACK_PRICES = {
    "RELIANCE.NS": 2905.50,
    "INFY.NS":     1823.40,
    "TCS.NS":      4215.75,
    "HDFCBANK.NS": 1698.20,
    "WIPRO.NS":     567.85,
    "SBIN.NS":      832.60,
    "BAJFINANCE.NS":7243.10,
    "ICICIBANK.NS": 1312.45,
    "AXISBANK.NS":  1187.90,
    "NIFTY50":    24830.15,
}

redis_client: Optional[aioredis.Redis] = None


@app.on_event("startup")
async def startup():
    global redis_client
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        print("✅ Redis connected")
    except Exception as e:
        print(f"⚠️  Redis not available, using fallback prices: {e}")
        redis_client = None


async def get_live_price(symbol: str) -> float:
    """Get live price from Redis (set by backend's yfinance poller). Fallback to static."""
    if redis_client:
        try:
            val = await redis_client.get(f"price:{symbol}")
            if val:
                return float(val)
        except Exception:
            pass
    # Add small random drift to fallback prices for realism
    base = FALLBACK_PRICES.get(symbol, 1000.0)
    return round(base * (1 + random.uniform(-0.002, 0.002)), 2)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PlaceOrderRequest(BaseModel):
    client_order_id: str
    symbol: str
    side: str           # BUY | SELL
    order_type: str     # MARKET | LIMIT | SL | SL-M
    quantity: int
    price: Optional[float] = None
    trigger_price: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-021-api", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/instruments")
async def get_instruments(search: str = Query(default="")):
    """Search instrument master."""
    if not search:
        return {"instruments": list(INSTRUMENT_MASTER.items())}
    search = search.upper()
    results = {k: v for k, v in INSTRUMENT_MASTER.items() if search in k or search in v["name"].upper()}
    return {"instruments": results}


@app.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """Get live quote for a symbol."""
    symbol = symbol.upper()
    if symbol not in INSTRUMENT_MASTER:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found in instrument master")
    price = await get_live_price(symbol)
    spread = round(price * 0.0001, 2)
    return {
        "symbol": symbol,
        "ltp": price,                            # Last Traded Price
        "bid": round(price - spread, 2),
        "ask": round(price + spread, 2),
        "open":  round(price * random.uniform(0.995, 1.005), 2),
        "high":  round(price * random.uniform(1.001, 1.012), 2),
        "low":   round(price * random.uniform(0.988, 0.999), 2),
        "prev_close": round(price * random.uniform(0.993, 1.007), 2),
        "volume": random.randint(50_000, 5_000_000),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/account")
async def get_account():
    """Get account summary."""
    # Compute live portfolio value
    total_position_value = 0.0
    for symbol, pos in MOCK_POSITIONS.items():
        price = await get_live_price(symbol)
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
    """Get current open positions with live P&L."""
    positions = []
    for symbol, pos in MOCK_POSITIONS.items():
        ltp = await get_live_price(symbol)
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


@app.get("/orders")
async def get_orders(status: str = Query(default="ALL")):
    """Get order history."""
    orders = list(MOCK_ORDERS.values())
    if status != "ALL":
        orders = [o for o in orders if o["status"] == status]
    orders.sort(key=lambda o: o["created_at"], reverse=True)
    return {"orders": orders, "total": len(orders)}


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    """Get single order status."""
    if order_id not in MOCK_ORDERS:
        raise HTTPException(status_code=404, detail="Order not found")
    return MOCK_ORDERS[order_id]


@app.post("/orders")
async def place_order(req: PlaceOrderRequest):
    """
    Place an order. Called only by the Executor service (never by LLM directly).
    Simulates realistic fill scenarios.
    """
    symbol = req.symbol.upper()

    # Validate symbol
    if symbol not in INSTRUMENT_MASTER:
        raise HTTPException(status_code=400, detail=f"Symbol {symbol} not in instrument master")

    # Check idempotency — if client_order_id already exists, return existing order
    for order in MOCK_ORDERS.values():
        if order["client_order_id"] == req.client_order_id:
            return order

    ltp = await get_live_price(symbol)

    # Simulate execution
    exchange_order_id = f"NSE{random.randint(100000000, 999999999)}"
    fill_scenario = random.choices(
        ["FILLED", "PARTIAL", "REJECTED"],
        weights=[85, 10, 5]
    )[0]

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

    # Update mock positions if filled
    if fill_scenario in ("FILLED", "PARTIAL") and avg_price:
        _update_positions(symbol, req.side, filled_qty, avg_price)

    return order


@app.delete("/orders/{order_id}")
async def cancel_order(order_id: str):
    """Cancel an open order."""
    if order_id not in MOCK_ORDERS:
        raise HTTPException(status_code=404, detail="Order not found")
    order = MOCK_ORDERS[order_id]
    if order["status"] in ("FILLED", "CANCELLED", "REJECTED"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel order in status {order['status']}")
    order["status"] = "CANCELLED"
    return {"message": "Order cancelled", "order_id": order_id}


@app.get("/price-stream/{symbol}")
async def price_stream(symbol: str):
    """SSE price stream for a symbol. Sends a new tick every second."""
    symbol = symbol.upper()
    if symbol not in INSTRUMENT_MASTER:
        raise HTTPException(status_code=404, detail="Symbol not found")

    async def generate():
        while True:
            price = await get_live_price(symbol)
            data = json.dumps({
                "symbol": symbol,
                "price": price,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            yield f"data: {data}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_positions(symbol: str, side: str, qty: int, price: float):
    """Update mock positions after a fill (simplified averaging)."""
    if symbol not in MOCK_POSITIONS:
        if side == "BUY":
            MOCK_POSITIONS[symbol] = {"quantity": qty, "avg_price": price, "side": "LONG"}
    else:
        pos = MOCK_POSITIONS[symbol]
        if side == "BUY":
            total_qty = pos["quantity"] + qty
            pos["avg_price"] = round(
                (pos["avg_price"] * pos["quantity"] + price * qty) / total_qty, 2
            )
            pos["quantity"] = total_qty
        elif side == "SELL":
            pos["quantity"] = max(0, pos["quantity"] - qty)
            if pos["quantity"] == 0:
                del MOCK_POSITIONS[symbol]
