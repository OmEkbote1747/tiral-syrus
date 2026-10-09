"""
Price Poller — fetches live NSE prices via yfinance every 15 seconds
and pushes them to Redis so the mock API and agent tools can read them.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

# Symbols we track for the demo
TRACKED_SYMBOLS = [
    "RELIANCE.NS",
    "INFY.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "WIPRO.NS",
    "SBIN.NS",
    "BAJFINANCE.NS",
    "ICICIBANK.NS",
    "AXISBANK.NS",
    "^NSEI",  # Nifty 50 index — stored as NIFTY50 in Redis
]

SYMBOL_ALIAS = {"^NSEI": "NIFTY50"}
POLL_INTERVAL = 15  # seconds


class PricePoller:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self._running = False

    async def start(self):
        """Main polling loop. Run as a background asyncio task."""
        self._running = True
        print("📈 Price poller: starting first fetch...")
        while self._running:
            try:
                await self._fetch_and_cache()
            except Exception as e:
                print(f"⚠️  Price poller error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    def stop(self):
        self._running = False

    async def _fetch_and_cache(self):
        """
        Fetch prices via yfinance in a thread (it's blocking/sync).
        Cache individual prices and a full snapshot to Redis.
        """
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            prices = await loop.run_in_executor(pool, self._fetch_yfinance)

        if not prices:
            print("⚠️  Price poller: no prices returned from yfinance")
            return

        pipe = self.redis.pipeline()
        snapshot = {}

        for symbol, price in prices.items():
            redis_key = SYMBOL_ALIAS.get(symbol, symbol)
            pipe.set(f"price:{redis_key}", str(price), ex=60)  # expires in 60s
            snapshot[redis_key] = price

        # Full snapshot for the ticker strip
        pipe.set(
            "price:snapshot",
            json.dumps({"prices": snapshot, "updated_at": datetime.now(timezone.utc).isoformat()}),
            ex=60,
        )

        await pipe.execute()
        print(f"📈 Prices updated: {', '.join(f'{k}={v}' for k, v in snapshot.items())}")

    def _fetch_yfinance(self) -> dict:
        """Synchronous yfinance call — runs in a thread pool."""
        try:
            import yfinance as yf
            tickers = yf.Tickers(" ".join(TRACKED_SYMBOLS))
            result = {}
            for symbol in TRACKED_SYMBOLS:
                try:
                    info = tickers.tickers[symbol].fast_info
                    price = getattr(info, "last_price", None)
                    if price and price > 0:
                        result[symbol] = round(float(price), 2)
                except Exception as e:
                    print(f"⚠️  Could not fetch {symbol}: {e}")
            return result
        except Exception as e:
            print(f"❌ yfinance error: {e}")
            return {}
