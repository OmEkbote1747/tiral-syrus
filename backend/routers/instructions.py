"""
Standing Instructions Router — CRUD for standing rules.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from db import get_db

router = APIRouter()


class CreateInstructionRequest(BaseModel):
    name: str
    symbol: str
    condition_type: str    # PRICE_ABOVE | PRICE_BELOW | PERCENT_CHANGE
    condition_value: float
    action_side: str       # BUY | SELL
    action_quantity: int
    action_order_type: str = "MARKET"
    expires_in_hours: Optional[float] = None
    raw_instruction: str = ""


@router.post("/")
async def create_instruction(req: CreateInstructionRequest, db: AsyncSession = Depends(get_db)):
    """Create a new standing instruction (pre-approved by trader in the chat flow)."""
    import uuid
    from datetime import datetime, timezone, timedelta

    expires_at = None
    if req.expires_in_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=req.expires_in_hours)

    inst_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO standing_instructions (
                id, name, raw_instruction, symbol,
                condition_type, condition_value,
                action_side, action_order_type, action_quantity,
                status, expires_at, approved_at
            ) VALUES (
                :id, :name, :raw, :symbol,
                :ctype, :cval,
                :aside, :aotype, :aqty,
                'ACTIVE', :expires_at, NOW()
            )
        """),
        {
            "id": str(inst_id),
            "name": req.name,
            "raw": req.raw_instruction or req.name,
            "symbol": req.symbol,
            "ctype": req.condition_type,
            "cval": req.condition_value,
            "aside": req.action_side,
            "aotype": req.action_order_type,
            "aqty": req.action_quantity,
            "expires_at": expires_at,
        },
    )
    await db.commit()
    return {"id": str(inst_id), "status": "ACTIVE", "message": "Standing instruction created and active."}


@router.get("/")
async def list_instructions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM standing_instructions ORDER BY created_at DESC LIMIT 50")
    )
    return {"instructions": [dict(r) for r in result.mappings()]}


@router.delete("/{instruction_id}")
async def cancel_instruction(instruction_id: str, db: AsyncSession = Depends(get_db)):
    """Trader cancels an active standing instruction."""
    result = await db.execute(
        text("""
            UPDATE standing_instructions
            SET status = 'CANCELLED', cancelled_at = NOW()
            WHERE id = :id AND status = 'ACTIVE'
            RETURNING id
        """),
        {"id": instruction_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Instruction not found or not active")
    await db.commit()
    return {"success": True, "message": "Instruction cancelled."}
