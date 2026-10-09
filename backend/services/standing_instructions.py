"""
Standing Instructions Service + Background Runner.

Rules are stored in PostgreSQL, loaded on startup, and checked against live prices.
Each rule fires exactly once — triggered_at is stamped atomically.
Rules that become stale (no price feed) are paused, not silently dropped.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
import uuid

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings


class StandingInstructionRunner:
    """
    Background task that polls active standing instructions
    and fires them when their condition is met.
    """

    def __init__(self, session_factory: async_sessionmaker, redis: aioredis.Redis):
        self.session_factory = session_factory
        self.redis = redis
        self._running = False
        self.poll_interval = 5  # seconds

    async def start(self):
        self._running = True
        print("📋 Standing instruction runner: started")
        while self._running:
            try:
                await self._check_instructions()
            except Exception as e:
                print(f"⚠️  Instruction runner error: {e}")
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        self._running = False

    async def _get_price(self, symbol: str) -> Optional[float]:
        """Get current price from Redis (set by price poller)."""
        try:
            val = await self.redis.get(f"price:{symbol}")
            return float(val) if val else None
        except Exception:
            return None

    async def _check_instructions(self):
        """Check all active instructions against current prices."""
        async with self.session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT * FROM standing_instructions
                    WHERE status = 'ACTIVE'
                    AND (expires_at IS NULL OR expires_at > NOW())
                """)
            )
            instructions = result.mappings().fetchall()

            for inst in instructions:
                symbol = inst["symbol"]
                price = await self._get_price(symbol)

                if price is None:
                    # No price data — pause the instruction (safety rule: don't fire blind)
                    await db.execute(
                        text("UPDATE standing_instructions SET status = 'PAUSED' WHERE id = :id"),
                        {"id": str(inst["id"])},
                    )
                    await db.commit()
                    continue

                condition_met = self._evaluate_condition(
                    condition_type=inst["condition_type"],
                    condition_value=float(inst["condition_value"]),
                    current_price=price,
                )

                if condition_met:
                    await self._trigger(db, inst, price)

    def _evaluate_condition(self, condition_type: str, condition_value: float, current_price: float) -> bool:
        if condition_type == "PRICE_ABOVE":
            return current_price >= condition_value
        elif condition_type == "PRICE_BELOW":
            return current_price <= condition_value
        elif condition_type == "PERCENT_CHANGE":
            # condition_value is the % threshold (positive or negative)
            # This would need a reference price — simplified for demo
            return False
        return False

    async def _trigger(self, db: AsyncSession, inst, current_price: float):
        """Fire an instruction — stamp triggered_at atomically, then send order via executor."""
        # Atomic claim — only fires once even if runner restarts
        result = await db.execute(
            text("""
                UPDATE standing_instructions
                SET status = 'TRIGGERED', triggered_at = NOW()
                WHERE id = :id AND status = 'ACTIVE' AND triggered_at IS NULL
                RETURNING id
            """),
            {"id": str(inst["id"])},
        )
        claimed = result.fetchone()
        if not claimed:
            return  # Already triggered by another instance — skip

        print(f"🔔 Instruction '{inst['name']}' triggered at price ₹{current_price}")

        # Place order via executor (bypasses LLM — uses pre-approved rule)
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as http:
            try:
                order_resp = await http.post(
                    f"{settings.mock_api_url}/orders",
                    json={
                        "client_order_id": f"SI-{uuid.uuid4().hex[:12].upper()}",
                        "symbol":       inst["symbol"],
                        "side":         inst["action_side"],
                        "order_type":   inst["action_order_type"],
                        "quantity":     inst["action_quantity"],
                    },
                )
                order_data = order_resp.json()
                order_status = order_data.get("status", "FAILED")
            except Exception as e:
                order_status = "FAILED"
                order_data = {"error": str(e)}

        # Save the resulting order to our DB and link to instruction
        order_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO orders (id, client_order_id, symbol, side, order_type, quantity,
                    quoted_price, status, filled_quantity, exchange_order_id, submitted_at,
                    risk_check_passed, raw_user_message)
                VALUES (:id, :coid, :symbol, :side, :otype, :qty,
                    :quoted_price, :status, :filled_qty, :exchange_id, NOW(),
                    TRUE, :raw_msg)
            """),
            {
                "id":          str(order_id),
                "coid":        order_data.get("client_order_id", f"SI-AUTO"),
                "symbol":      inst["symbol"],
                "side":        inst["action_side"],
                "otype":       inst["action_order_type"],
                "qty":         inst["action_quantity"],
                "quoted_price":current_price,
                "status":      order_status,
                "filled_qty":  order_data.get("filled_quantity", 0),
                "exchange_id": order_data.get("exchange_order_id"),
                "raw_msg":     f"Standing instruction: {inst['name']}",
            },
        )

        # Link order to instruction
        await db.execute(
            text("UPDATE standing_instructions SET triggered_order_id = :oid WHERE id = :id"),
            {"oid": str(order_id), "id": str(inst["id"])},
        )

        # Audit log
        await db.execute(
            text("""
                INSERT INTO audit_log (event_type, order_id, instruction_id, actor, payload)
                VALUES ('INSTRUCTION_TRIGGERED', :oid, :iid, 'SYSTEM', :payload::jsonb)
            """),
            {
                "oid": str(order_id),
                "iid": str(inst["id"]),
                "payload": json.dumps({
                    "instruction_name": inst["name"],
                    "trigger_price": current_price,
                    "order_status": order_status,
                }),
            },
        )
        await db.commit()
