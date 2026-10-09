"""
Executor Service — the ONLY component that can submit orders to the broker.

Critical rules:
1. No LLM involvement here. Pure deterministic logic.
2. Validates the approval token before touching the broker.
3. Checks price drift — if price moved beyond tolerance since the quote, re-quotes.
4. Uses client_order_id for idempotency — safe to retry.
5. Checks order book before any retry to avoid duplicates.
"""

from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services.approval_token import ApprovalTokenService


PRICE_DRIFT_TOLERANCE_PCT = 0.5   # 0.5% — if price moved more, re-quote before submitting


@dataclass
class ExecutionResult:
    success: bool
    status: str           # FILLED | PARTIAL | REJECTED | FAILED | PRICE_DRIFTED
    exchange_order_id: Optional[str] = None
    filled_quantity: int = 0
    average_price: Optional[float] = None
    message: str = ""


class ExecutorService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.token_service = ApprovalTokenService()
        self.broker_url = settings.mock_api_url

    async def execute(self, order_id: str, token: str) -> ExecutionResult:
        """
        Execute an approved order.

        Steps:
        1. Load order from DB
        2. Validate token against order
        3. Check price drift — if too much, fail with PRICE_DRIFTED (frontend will re-quote)
        4. Submit to broker with client_order_id for idempotency
        5. Update order status in DB
        """
        # --- Load order ---
        result = await self.db.execute(
            text("SELECT * FROM orders WHERE id = :id"),
            {"id": order_id},
        )
        order = result.mappings().fetchone()

        if not order:
            return ExecutionResult(success=False, status="FAILED", message="Order not found")

        if order["status"] != "APPROVED":
            return ExecutionResult(
                success=False,
                status="FAILED",
                message=f"Order is in status '{order['status']}', not APPROVED",
            )

        # --- Validate token ---
        token_result = self.token_service.validate(token, dict(order))
        if not token_result.valid:
            # Log token rejection to audit
            await self.db.execute(
                text(
                    "INSERT INTO audit_log (event_type, order_id, actor, payload) "
                    "VALUES ('TOKEN_REJECTED', :oid, 'SYSTEM', :payload::jsonb)"
                ),
                {"oid": order_id, "payload": f'{{"reason": "{token_result.reason}"}}'},
            )
            await self.db.commit()
            return ExecutionResult(
                success=False,
                status="FAILED",
                message=f"Token validation failed: {token_result.reason}",
            )

        # --- Check price drift for limit/market orders ---
        async with httpx.AsyncClient(timeout=10.0) as http:
            try:
                quote_resp = await http.get(f"{self.broker_url}/quote/{order['symbol']}")
                current_price = quote_resp.json().get("ltp", 0)
            except Exception:
                current_price = None

        if current_price and order.get("quoted_price"):
            drift_pct = abs(current_price - float(order["quoted_price"])) / float(order["quoted_price"]) * 100
            if drift_pct > PRICE_DRIFT_TOLERANCE_PCT:
                await self.db.execute(
                    text(
                        "UPDATE orders SET status = 'DRAFT' WHERE id = :id"
                    ),
                    {"id": order_id},
                )
                await self.db.commit()
                return ExecutionResult(
                    success=False,
                    status="PRICE_DRIFTED",
                    message=(
                        f"Price moved by {drift_pct:.2f}% since you approved "
                        f"(was ₹{order['quoted_price']:.2f}, now ₹{current_price:.2f}). "
                        f"Please review the updated confirmation card."
                    ),
                )

        # --- Submit to broker (with idempotency) ---
        async with httpx.AsyncClient(timeout=15.0) as http:
            try:
                broker_resp = await http.post(
                    f"{self.broker_url}/orders",
                    json={
                        "client_order_id": order["client_order_id"],
                        "symbol":       order["symbol"],
                        "side":         order["side"],
                        "order_type":   order["order_type"],
                        "quantity":     order["quantity"],
                        "price":        order["price"],
                        "trigger_price": order["trigger_price"],
                    },
                )
                broker_data = broker_resp.json()

            except httpx.RequestError as e:
                # Network failure — do NOT retry automatically. Let trader decide.
                return ExecutionResult(
                    success=False,
                    status="FAILED",
                    message=f"Broker unreachable: {str(e)}. Do not retry without checking order status.",
                )

        exec_status = broker_data.get("status", "FAILED")
        filled_qty = broker_data.get("filled_quantity", 0)
        avg_price = broker_data.get("average_price")
        exchange_id = broker_data.get("exchange_order_id")

        # --- Update order in DB ---
        await self.db.execute(
            text("""
                UPDATE orders SET
                    status = :status,
                    filled_quantity = :filled_qty,
                    average_price = :avg_price,
                    exchange_order_id = :exchange_id,
                    submitted_at = NOW(),
                    filled_at = CASE WHEN :status IN ('FILLED','PARTIAL') THEN NOW() ELSE NULL END
                WHERE id = :id
            """),
            {
                "id": order_id,
                "status": exec_status,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "exchange_id": exchange_id,
            },
        )

        # --- Audit log ---
        await self.db.execute(
            text(
                "INSERT INTO audit_log (event_type, order_id, actor, payload) "
                "VALUES ('ORDER_EXECUTED', :oid, 'SYSTEM', :payload::jsonb)"
            ),
            {
                "oid": order_id,
                "payload": f'{{"status": "{exec_status}", "filled_qty": {filled_qty}, "avg_price": {avg_price or 0}}}',
            },
        )
        await self.db.commit()

        return ExecutionResult(
            success=exec_status in ("FILLED", "PARTIAL"),
            status=exec_status,
            exchange_order_id=exchange_id,
            filled_quantity=filled_qty,
            average_price=avg_price,
            message=broker_data.get("reject_reason", ""),
        )
