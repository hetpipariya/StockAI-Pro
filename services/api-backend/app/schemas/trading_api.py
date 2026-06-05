from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PositionDTO(BaseModel):
    id: int
    symbol: str
    direction: str
    quantity: int
    entry_price: float
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    mode: Optional[str] = None
    opened_at: Optional[str] = None
    updated_at: Optional[str] = None


class PendingOrderDTO(BaseModel):
    order_id: str
    symbol: str
    direction: str
    quantity: int
    filled_quantity: int
    price: float
    status: str
    mode: Optional[str] = None
    timestamp: Optional[str] = None


class ActiveTradesPayload(BaseModel):
    user_id: int
    positions: list[PositionDTO] = Field(default_factory=list)
    pending_orders: list[PendingOrderDTO] = Field(default_factory=list)
    positions_count: int
    pending_orders_count: int
    as_of: str


class TradesActiveResponse(BaseModel):
    status: str
    message: str
    data: ActiveTradesPayload


class PortfolioBalancePayload(BaseModel):
    user_id: int
    available_balance: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    gross_exposure: float
    open_positions: int
    can_trade: bool
    can_trade_reason: str
    trading_halted: bool
    as_of: str


class PortfolioBalanceResponse(BaseModel):
    status: str
    message: str
    data: PortfolioBalancePayload


class SignalDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    signal: str
    confidence: float
    confidence_pct: int
    prediction: float
    target: float
    stop_loss: float
    horizon: Optional[str] = None
    timestamp: Optional[str] = None
    source: Optional[str] = None


class SignalsPayload(BaseModel):
    signals: list[SignalDTO] = Field(default_factory=list)
    count: int
    as_of: str


class SignalsResponse(BaseModel):
    status: str
    message: str
    data: SignalsPayload
