from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import Date, String, Text, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


def utcnow() -> datetime:
    """Naive UTC, set by Python rather than the database.

    server_default=func.now() is UTC on SQLite but server-local time on
    Postgres — this keeps the value identical on both.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Trade(Base):
    """A position, open or closed. The authoritative record of what was traded."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    entry_price: Mapped[float]
    quantity: Mapped[int]
    entry_value: Mapped[float]
    stop_loss: Mapped[float]
    take_profit: Mapped[float]
    current_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    atr_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
    peak_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    trail_stop: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    close_price: Mapped[Optional[float]]
    close_reason: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # stop | trail | target | timeout | manual — see app/portfolio/exits.py
    pnl: Mapped[Optional[float]]
    pnl_pct: Mapped[Optional[float]]
    confidence: Mapped[Optional[float]]
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    technical_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]]


class PortfolioSnapshot(Base):
    """Portfolio value at a point in time.

    Drives the equity chart and the circuit breaker's drawdown check.
    """

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


class DecisionRecord(Base):
    """One row per candidate the scan evaluated, whether it was bought or not.

    Holds the score and the band each dimension landed in, the indicators at
    the time, and space for the veto's verdict. `outcome_*` is filled in later
    by the post-mortem, so passed-over candidates can be judged alongside
    the ones that were traded.
    """

    __tablename__ = "decision_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    ticker: Mapped[str] = mapped_column(String(20))
    git_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # scoring — null if blocked before we got this far
    score: Mapped[Optional[int]] = mapped_column(nullable=True)
    entry_timing: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    momentum_quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    risk_reward_view: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    market_regime: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # what the stock looked like that day
    price: Mapped[Optional[float]] = mapped_column(nullable=True)
    rsi: Mapped[Optional[float]] = mapped_column(nullable=True)
    atr_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    momentum_5d: Mapped[Optional[float]] = mapped_column(nullable=True)
    day_change_pct: Mapped[Optional[float]] = mapped_column(nullable=True)

    # what we did
    entered: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # veto — null for candidates that never reached it
    veto_verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    veto_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    veto_cited_fact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    veto_source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    veto_checked: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    veto_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    veto_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    veto_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # outcome — empty until the post-mortem fills it
    outcome_pnl_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
    outcome_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    outcome_filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )


class ScanRun(Base):
    """One row per scan attempt, written whether or not it found anything.

    Separates "ran and found nothing" from "never ran", which is the only
    thing a health check actually needs to know.
    """

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    candidates_found: Mapped[int] = mapped_column(default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
