import structlog
import asyncio
import json
from fastapi import FastAPI, Request

from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func
from contextlib import asynccontextmanager

from app.core.logging import setup_logging, log_buffer

from app.core.database import get_db, init_db
from app.core.health import MAX_SCAN_AGE_HOURS, last_scan_at
from app.models.models import Trade, PortfolioSnapshot, DecisionRecord, utcnow
from app.scheduler.scheduler import create_scheduler

setup_logging()

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database and start the scheduler alongside the API."""
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
    """Dashboard home: portfolio value, P&L and the equity chart."""
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
    """Open positions with live prices and progress toward stop and target."""
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
    """Closed trades with win rate and profit statistics."""
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


DECISIONS_PAGE_SIZE = 200


@app.get("/decisions", response_class=HTMLResponse)
def decisions(request: Request):
    """Every candidate the scan evaluated, bought or not, with the veto's verdict.

    This is the shadow-mode view: the veto records a verdict but never blocks,
    so the summary compares what the killed set went on to do against what the
    passed set did.
    """
    with get_db() as db:
        rows = (
            db.query(DecisionRecord)
            .order_by(desc(DecisionRecord.as_of), desc(DecisionRecord.id))
            .limit(DECISIONS_PAGE_SIZE)
            .all()
        )
        records = [
            {
                "as_of": r.as_of,
                "ticker": r.ticker,
                "score": r.score,
                "bands": [
                    b
                    for b in (
                        r.entry_timing,
                        r.momentum_quality,
                        r.risk_reward_view,
                        r.market_regime,
                    )
                    if b
                ],
                "entered": r.entered,
                "block_reason": r.block_reason,
                "veto_verdict": r.veto_verdict,
                "veto_reason": r.veto_reason,
                "veto_cited_fact": r.veto_cited_fact,
                "veto_source_url": r.veto_source_url,
                "veto_checked": r.veto_checked,
                "veto_errored": (r.veto_checked or "").startswith("error:"),
                "outcome_pnl_pct": r.outcome_pnl_pct,
                "outcome_reason": r.outcome_reason,
            }
            for r in rows
        ]

        # Summary over every record ever, not just this page.
        judged = db.query(DecisionRecord).filter(
            DecisionRecord.veto_verdict.isnot(None)
        )
        seen = judged.count()
        killed = judged.filter(DecisionRecord.veto_verdict == "KILL").count()
        errored = judged.filter(DecisionRecord.veto_checked.like("error:%")).count()

        reason_counts = (
            db.query(DecisionRecord.veto_reason, func.count())
            .filter(
                DecisionRecord.veto_verdict == "KILL",
                DecisionRecord.veto_reason.isnot(None),
            )
            .group_by(DecisionRecord.veto_reason)
            .order_by(desc(func.count()))
            .all()
        )

        def mean_outcome(verdict: str) -> float | None:
            vals = [
                v
                for (v,) in db.query(DecisionRecord.outcome_pnl_pct)
                .filter(
                    DecisionRecord.veto_verdict == verdict,
                    DecisionRecord.outcome_pnl_pct.isnot(None),
                )
                .all()
            ]
            return round(sum(vals) / len(vals), 2) if vals else None

        killed_outcome = mean_outcome("KILL")
        passed_outcome = mean_outcome("PASS")
        total = db.query(DecisionRecord).count()

    stats = {
        "total": total,
        "veto_seen": seen,
        "veto_killed": killed,
        "kill_rate": round(killed / seen * 100) if seen else 0,
        "veto_errored": errored,
        "killed_outcome": killed_outcome,
        "passed_outcome": passed_outcome,
        # The experiment, in one number: negative means the veto killed trades
        # that went on to do worse than the ones it let through.
        "edge": (
            round(killed_outcome - passed_outcome, 2)
            if killed_outcome is not None and passed_outcome is not None
            else None
        ),
        "kill_reasons": (
            [
                {"reason": r, "count": n, "pct": round(n / killed * 100)}
                for r, n in reason_counts
            ]
            if killed
            else []
        ),
    }

    return templates.TemplateResponse(
        request=request,
        name="decisions.html",
        context={"records": records, "stats": stats, "limit": DECISIONS_PAGE_SIZE},
    )


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request):
    """Live log viewer page."""
    entries = list(reversed(list(log_buffer)))[:200]
    return templates.TemplateResponse(
        request=request, name="logs.html", context={"entries": entries}
    )


@app.get("/api/logs/stream")
async def stream_logs():
    """Server-sent events stream of new log lines for the live log page."""

    async def event_generator():
        """Yield log lines as they appear, polling the in-memory buffer."""
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
    """Portfolio snapshots as JSON, for the equity chart."""
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


@app.get("/health")
def health():
    """Liveness for an external monitor, as JSON plus a meaningful status code.

    Returns 503 once the scan has gone stale rather than 200 with a flag, so a
    plain uptime monitor catches a stopped scheduler as well as a dead host.
    """
    last = last_scan_at()

    if last is None:
        return JSONResponse(status_code=503, content={"status": "never_ran"})

    age = (utcnow() - last).total_seconds() / 3600
    ok = age < MAX_SCAN_AGE_HOURS
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "stale",
            "last_scan": last.isoformat(),
            "age_hours": round(age, 1),
        },
    )
