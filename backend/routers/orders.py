"""
Orders Router — approve, reject, execute, and fetch orders.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from services.order_service import OrderService
from services.executor import ExecutorService
from services.audit_logger import AuditLogger

router = APIRouter()


class ApproveRequest(BaseModel):
    order_id: str


class RejectRequest(BaseModel):
    order_id: str
    reason: str = "Trader rejected"


@router.post("/approve")
async def approve_order(req: ApproveRequest, db: AsyncSession = Depends(get_db)):
    """
    Trader approves a draft order.
    Generates a hash-bound token and immediately executes via the Executor.
    """
    order_service = OrderService(db)
    executor = ExecutorService(db)
    audit = AuditLogger(db)

    try:
        # Generate token + mark APPROVED
        approval = await order_service.approve(req.order_id)

        await audit.log(
            event_type="ORDER_APPROVED",
            order_id=req.order_id,
            actor="TRADER",
            payload={"token_expires_at": approval["expires_at"]},
        )

        # Execute immediately
        result = await executor.execute(req.order_id, approval["token"])

        await audit.log(
            event_type="ORDER_SUBMITTED",
            order_id=req.order_id,
            actor="SYSTEM",
            payload={
                "status": result.status,
                "filled_quantity": result.filled_quantity,
                "average_price": result.average_price,
            },
        )

        return {
            "success": result.success,
            "status": result.status,
            "exchange_order_id": result.exchange_order_id,
            "filled_quantity": result.filled_quantity,
            "average_price": result.average_price,
            "message": result.message,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reject")
async def reject_order(req: RejectRequest, db: AsyncSession = Depends(get_db)):
    """Trader rejects a draft — draft is discarded, no order placed."""
    order_service = OrderService(db)
    audit = AuditLogger(db)

    await order_service.reject(req.order_id)
    await audit.log(
        event_type="ORDER_REJECTED",
        order_id=req.order_id,
        actor="TRADER",
        payload={"reason": req.reason},
    )
    await db.commit()

    return {"success": True, "message": "Order draft rejected and discarded."}


@router.get("/{order_id}")
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    order_service = OrderService(db)
    order = await order_service.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/")
async def list_orders(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT * FROM orders ORDER BY created_at DESC LIMIT 50")
    )
    return {"orders": [dict(r) for r in result.mappings()]}
