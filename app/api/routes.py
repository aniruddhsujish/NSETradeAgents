import structlog
import asyncio
import json
from fastapi import FastAPI, Request

from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from contextlib import asynccontextmanager

from app.core.logging import setup_logging, log_buffer

from app.core.database import get_db, init_db
from app.models.models import Trade, PortfolioSnapshot
from app.scheduler.scheduler import create_scheduler

setup_logging()

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("api_started")
    yield
    scheduler.shutdown()
    logger.info("api_stopped")


app = FastAPI(title="Swing Trade Bot", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    with get_db() as db:
        raw = (
            db.query(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.snapshot_at))
            .first()
        )
        open_count = db.query(Trade).filter(Trade.status == "open").count()
        snapshot = (
            {
                "total_value": raw.total_value,
                "cash": raw.cash,
                "invested": raw.invested,
                "open_positions": raw.open_positions,
                "daily_pnl": raw.daily_pnl,
                "cumulative_pnl": raw.cumulative_pnl,
                "unrealised_pnl": raw.unrealised_pnl,
                "snapshot_at": raw.snapshot_at,
            }
            if raw
            else None
        )

    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={"snapshot": snapshot, "open_count": open_count},
    )


@app.get("/positions", response_class=HTMLResponse)
def positions(request: Request):

    with get_db() as db:
        open_trades = (
            db.query(Trade)
            .filter(Trade.status == "open")
            .order_by(desc(Trade.opened_at))
            .all()
        )

        trades = [
            {
                "ticker": t.ticker,
                "entry_price": t.entry_price,
                "quantity": t.quantity,
                "entry_value": t.entry_value,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "confidence": t.confidence,
                "opened_at": t.opened_at,
                "reasoning": t.reasoning,
                "current_price": t.current_price or t.entry_price,
                "unrealised_pnl": round(
                    ((t.current_price or t.entry_price) - t.entry_price) * t.quantity, 2
                ),
                "unrealised_pct": round(
                    ((t.current_price or t.entry_price) - t.entry_price)
                    / t.entry_price
                    * 100,
                    2,
                ),
            }
            for t in open_trades
        ]
    return templates.TemplateResponse(
        request=request, name="positions.html", context={"trades": trades}
    )


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):

    with get_db() as db:
        closed_trades = (
            db.query(Trade)
            .filter(Trade.status == "closed")
            .order_by(desc(Trade.closed_at))
            .all()
        )
        trades = [
            {
                "ticker": t.ticker,
                "entry_price": t.entry_price,
                "close_price": t.close_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "close_reason": t.close_reason,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
            }
            for t in closed_trades
        ]

        wins = [t for t in trades if (t["pnl"] or 0) > 0]

        total_pnl = sum(t["pnl"] or 0 for t in trades)
        win_rate = round(len(wins) / len(trades) * 100) if trades else 0

    stats = {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(trades) - len(wins),
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
    }

    return templates.TemplateResponse(
        request=request, name="history.html", context={"trades": trades, "stats": stats}
    )


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request):
    entries = list(reversed(list(log_buffer)))[:200]
    return templates.TemplateResponse(
        request=request, name="logs.html", context={"entries": entries}
    )


@app.get("/api/logs/stream")
async def stream_logs():
    async def event_generator():
        sent = max(0, len(log_buffer) - 50)
        while True:
            current = len(log_buffer)
            if current > sent:
                for entry in list(log_buffer)[sent:current]:
                    yield f"data: {json.dumps(entry)}\n\n"
                sent = current
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/snapshots")
def api_snapshots():
    with get_db() as db:
        snapshots = (
            db.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.snapshot_at)
            .limit(200)
            .all()
        )
        return [
            {
                "time": s.snapshot_at.strftime("%d %b %H:%M") if s.snapshot_at else "",
                "total_value": s.total_value,
                "cumulative_pnl": s.cumulative_pnl,
                "unrealised_pnl": s.unrealised_pnl,
            }
            for s in snapshots
        ]
