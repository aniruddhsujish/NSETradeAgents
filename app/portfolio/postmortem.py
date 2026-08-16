from datetime import date, datetime, timedelta
from dataclasses import replace

import structlog

from app.core.config import settings
from app.core.database import get_db
from app.models.models import DecisionRecord
from app.portfolio.exits import Bar, PositionView, evaluate_exit, update_trail
from app.utils.market_data import safe_yf_download, extract_ticker_df

logger = structlog.get_logger()


def _simulate(record, bars) -> tuple[float, str] | None:
    """Replay what a decision would have returned, had it been traded.

    Buys at the open of the day after the decision and runs the same exit
    rules as a real position. Returns (pnl_pct, reason), or None when the
    trade hasn't resolved yet and should be retried later.
    """

    after = bars.loc[bars.index.date > record.as_of]
    if len(after) < 2:
        return None

    entry_price = float(after.iloc[0]["Open"])
    if entry_price <= 0:
        return None

    atr = record.atr_pct or 0
    stop_pct = (
        min(max(2.5 * atr / 100, 0.05), 0.10) if atr > 0 else settings.stop_loss_pct
    )

    pos = PositionView(
        entry_date=after.index[0].date(),
        stop_price=entry_price * (1 - stop_pct),
        target_price=entry_price * (1 + settings.take_profit_pct),
    )
    peak = entry_price

    for ts, row in after.iloc[1:].iterrows():
        bar = Bar(
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
        )
        result = evaluate_exit(pos, bar, ts.date())
        peak, new_trail, active = update_trail(
            close=bar.close,
            entry_price=entry_price,
            atr_pct=atr,
            peak_price=peak,
            trail_stop=pos.trail_stop,
            stop_price=pos.stop_price,
        )
        if active:
            pos = replace(pos, trail_stop=new_trail)

        if result:
            exit_price, reason = result
            return round((exit_price - entry_price) / entry_price * 100, 2), reason

    return None


def fill_outcomes() -> int:
    """Work out what happened to decisions that are old enough to judge.

    Covers stocks that were bought and stocks that were passed over, so both
    are measured the same way. Records that haven't resolved stay pending.

    Returns how many were filled in.
    """
    cutoff = date.today() - timedelta(days=settings.max_hold_days + 5)

    with get_db() as db:
        pending = (
            db.query(DecisionRecord)
            .filter(
                DecisionRecord.outcome_pnl_pct.is_(None), DecisionRecord.as_of <= cutoff
            )
            .all()
        )

        if not pending:
            logger.info("postmortem_nothing_pending")
            return 0

        tickers = sorted({r.ticker for r in pending})
        logger.info("postmortem_start", records=len(pending), tickers=len(tickers))

        raw = safe_yf_download(tickers, period="6mo", group_by="ticker")
        filled = 0
        for record in pending:
            try:
                bars = extract_ticker_df(raw, record.ticker)
                if bars is None:
                    continue
                result = _simulate(record, bars.dropna(subset=["Close"]))
                if result is None:
                    continue
                record.outcome_pnl_pct, record.outcome_reason = result
                record.outcome_filled_at = datetime.now()
                filled += 1
            except Exception as e:
                logger.warning("postmortem_failed", ticker=record.ticker, error=str(e))

        logger.info("postmortem_done", filled=filled, pending=len(pending))
        return filled
