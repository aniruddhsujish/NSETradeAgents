from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Float, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    entry_price: Mapped[float]
    quantity: Mapped[int]
    entry_value: Mapped[float]
    stop_loss: Mapped[float]
    take_profit: Mapped[float]
    current_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    close_price: Mapped[Optional[float]]
    close_reason: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # tp | sl | manual | review | timeout
    pnl: Mapped[Optional[float]]
    pnl_pct: Mapped[Optional[float]]
    confidence: Mapped[Optional[float]]
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    technical_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]]


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    total_value: Mapped[float]
    cash: Mapped[float]
    invested: Mapped[float]
    open_positions: Mapped[int]
    daily_pnl: Mapped[float] = mapped_column(default=0.0)
    cumulative_pnl: Mapped[float] = mapped_column(default=0.0)
    unrealised_pnl: Mapped[float] = mapped_column(default=0.0)
    snapshot_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )


class WatchlistStock(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_analysed_at: Mapped[Optional[datetime]]
