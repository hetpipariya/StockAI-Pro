from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
import uuid

from app.connectors import SmartAPIConnector, get_symbol_token, get_tradingsymbol
from app.config import SMARTAPI_EXCHANGE
from app.services.db import async_session, OrderModel

router = APIRouter(prefix="/api/v1", tags=["order"])

_connector: SmartAPIConnector | None = None


def get_connector() -> SmartAPIConnector:
    global _connector
    if _connector is None:
        _connector = SmartAPIConnector()
        _connector.login()
    return _connector


class OrderRequest(BaseModel):
    symbol: str
    transactiontype: Literal["BUY", "SELL"]
    quantity: int
    ordertype: Literal["MARKET", "LIMIT"] = "MARKET"
    price: Optional[float] = None
    producttype: str = "INTRADAY"
    variety: str = "NORMAL"
    duration: str = "DAY"
    mode: Literal["paper", "live"] = "paper"


@router.post("/order")
async def place_order(req: OrderRequest):
    """Place order. mode=paper simulates fill; mode=live forwards to SmartAPI."""
    order_id = ""
    status = ""
    resp_data = None
    
    if req.mode == "paper":
        order_id = f"PAPER_{req.symbol}_{req.transactiontype}_{req.quantity}_{uuid.uuid4().hex[:6]}"
        status = "COMPLETED"
        resp_data = {
            "status": True,
            "message": "PAPER_ORDER_SIMULATED",
            "orderid": order_id,
            "mode": "paper",
        }
    else:
        token = get_symbol_token(req.symbol)
        ts = get_tradingsymbol(req.symbol)
        payload = {
            "variety": req.variety,
            "tradingsymbol": ts,
            "symboltoken": token,
            "transactiontype": req.transactiontype,
            "exchange": SMARTAPI_EXCHANGE,
            "ordertype": req.ordertype,
            "producttype": req.producttype,
            "duration": req.duration,
            "quantity": str(req.quantity),
            "price": str(req.price or "0"),
            "squareoff": "0",
            "stoploss": "0",
        }
        try:
            conn = get_connector()
            resp = conn.place_order(payload)
            if resp and resp.get("status"):
                order_id = resp.get("data", {}).get("orderid", f"LIVE_{uuid.uuid4().hex[:8]}")
                status = "OPEN"
                resp_data = resp
            else:
                raise HTTPException(500, f"SmartAPI error: {resp}")
        except Exception as e:
            raise HTTPException(500, str(e))
            
    # Save to DB
    if async_session:
        try:
            async with async_session() as session:
                order_record = OrderModel(
                    order_id=order_id,
                    symbol=req.symbol,
                    transaction_type=req.transactiontype,
                    quantity=req.quantity,
                    price=req.price or 0.0,
                    status=status,
                    mode=req.mode
                )
                session.add(order_record)
                await session.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save order to DB: %s", e)

    return resp_data
