from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    entry_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_value = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    status = Column(String(10), default="open")  # open | closed
    close_price = Column(Float)
    close_reason = Column(String(20))  # tp | sl | manual | review
    pnl = Column(Float)
    pnl_pct = Column(Float)
    confidence = Column(Float)
    reasoning = Column(Text)
    technical_summary = Column(Text)
    sentiment_summary = Column(Text)
    opened_at = Column(DateTime, server_default=func.now())
    closed_at = Column(DateTime)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True)
    total_value = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    invested = Column(Float, nullable=False)
    open_positions = Column(Integer, nullable=False)
    daily_pnl = Column(Float, default=0.0)
    cumulative_pnl = Column(Float, default=0.0)
    snapshot_at = Column(DateTime, server_default=func.now())


class WatchlistStock(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    ticker = Column(String[20], unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    added_reason = Column(Text)
    added_at = Column(DateTime, server_default=func.now())
    last_analysed_at = Column(DateTime)
