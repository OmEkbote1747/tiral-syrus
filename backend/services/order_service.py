"""
Order Service — DB operations for orders (create draft, approve, reject, fetch).
"""
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.approval_token import ApprovalTokenService


token_service = ApprovalTokenService()


@dataclass
class OrderRow:
    id: uuid.UUID
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: Optional[float]
    quoted_price: Optional[float]
    status: str
    risk_score: Optional[int]
    approval_token: Optional[str]
    token_expires_at: Optional[float]
    raw_user_message: Optional[str]


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_draft(self, raw_message: str, draft_data: dict) -> OrderRow:
        """Save a new order draft to the DB. Returns the created order."""
        order_id = uuid.uuid4()
        client_order_id = f"SYR-{uuid.uuid4().hex[:12].upper()}"

        quoted_price = draft_data.get("quoted_price") or draft_data.get("price")

        await self.db.execute(
            text("""
                INSERT INTO orders (
                    id, client_order_id, symbol, side, order_type,
                    quantity, price, trigger_price, quoted_price,
                    status, risk_score, injection_flagged, risk_check_passed,
                    raw_user_message
                ) VALUES (
                    :id, :coid, :symbol, :side, :order_type,
                    :qty, :price, :trigger_price, :quoted_price,
                    'DRAFT', :risk_score, FALSE, :risk_passed,
                    :raw_msg
                )
            """),
            {
                "id":           str(order_id),
                "coid":         client_order_id,
                "symbol":       draft_data["symbol"],
                "side":         draft_data["side"],
                "order_type":   draft_data["order_type"],
                "qty":          draft_data["quantity"],
                "price":        draft_data.get("price"),
                "trigger_price":draft_data.get("trigger_price"),
                "quoted_price": quoted_price,
                "risk_score":   draft_data.get("risk_score", 80),
                "risk_passed":  draft_data.get("risk_check_passed", True),
                "raw_msg":      raw_message,
            },
        )

        return OrderRow(
            id=order_id,
            client_order_id=client_order_id,
            symbol=draft_data["symbol"],
            side=draft_data["side"],
            order_type=draft_data["order_type"],
            quantity=draft_data["quantity"],
            price=draft_data.get("price"),
            quoted_price=quoted_price,
            status="DRAFT",
            risk_score=draft_data.get("risk_score", 80),
            approval_token=None,
            token_expires_at=None,
            raw_user_message=raw_message,
        )

    async def approve(self, order_id: str) -> dict:
        """
        Approve an order: generate a hash-bound token and mark as APPROVED.
        Returns the token and expiry for the executor.
        """
        result = await self.db.execute(
            text("SELECT * FROM orders WHERE id = :id AND status = 'DRAFT'"),
            {"id": order_id},
        )
        order = result.mappings().fetchone()
        if not order:
            raise ValueError(f"Order {order_id} not found or not in DRAFT status")

        token, expires_at = token_service.generate(dict(order))

        await self.db.execute(
            text("""
                UPDATE orders SET
                    status = 'APPROVED',
                    approval_token = :token,
                    token_expires_at = TO_TIMESTAMP(:expires_at),
                    approved_at = NOW()
                WHERE id = :id
            """),
            {"id": order_id, "token": token, "expires_at": expires_at},
        )
        await self.db.commit()

        return {"order_id": order_id, "token": token, "expires_at": expires_at}

    async def reject(self, order_id: str) -> None:
        """Reject (discard) a draft order."""
        await self.db.execute(
            text("UPDATE orders SET status = 'REJECTED', rejected_at = NOW() WHERE id = :id"),
            {"id": order_id},
        )
        await self.db.commit()

    async def get(self, order_id: str) -> Optional[dict]:
        result = await self.db.execute(
            text("SELECT * FROM orders WHERE id = :id"),
            {"id": order_id},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None
