from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from app.backtest.store import BacktestStore
from app.agents.technical import _compute_signal
from app.core.config import settings
from app.portfolio.exits import (
    Bar,
    PositionView,
    evaluate_exit,
    stop_pct,
    target_pct,
    update_trail,
)
from app.screener.filters import evaluate_candidate, regime_blocked
from app.utils.indicators import compute_indicators
from app.utils.scoring import compute_rules_confidence

logger = structlog.get_logger()


@dataclass
class Position:
    """An open position during a backtest run."""

    ticker: str
    entry_date: date
    entry_price: float
    stop_price: float
    target_price: float
    shares: int
    capital_used: float
    score: int = 0
    atr_pct: float = 0.0
    peak_price: float = 0.0
    trail_stop: float = 0.0
    hybrid_active: bool = False


@dataclass
class ClosedTrade:
    """A finished trade, as written to the trade log."""

    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    exit_reason: str  # "stop" | "target" | "timeout" | "trail" | "end_of_backtest"
    score: int = 0


def _check_exit(pos: Position, bar: pd.Series, today: date) -> tuple[float, str] | None:
    """Adapt a backtest position and a pandas bar to the shared exit rules.

    Keeps pandas out of `exits.py` so the same rules can serve the live path.
    """
    return evaluate_exit(
        PositionView(
            entry_date=pos.entry_date,
            stop_price=pos.stop_price,
            target_price=pos.target_price,
            trail_stop=pos.trail_stop,
            hybrid_active=pos.hybrid_active,
        ),
        Bar(
            open=float(bar["Open"]),
            high=float(bar["High"]),
            low=float(bar["Low"]),
            close=float(bar["Close"]),
        ),
        today,
    )


def _market_context(nifty: pd.DataFrame, vix: pd.DataFrame, ts: pd.Timestamp) -> dict:
    """Build the market context for one day from the index and VIX series.

    Sector fields are empty: the cache holds no sector data, so sector rules
    only take effect live.
    """
    try:
        n = nifty.loc[:ts]["Close"]
        vix_val = float(vix.at[ts, "Close"]) if ts in vix.index else 0.0
        nifty_day = (n.iloc[-1] - n.iloc[-2]) / n.iloc[-2] * 100 if len(n) >= 2 else 0.0
        nifty_10d = (
            (n.iloc[-1] - n.iloc[-11]) / n.iloc[-11] * 100 if len(n) >= 11 else 0.0
        )
        nifty_20d = (
            (n.iloc[-1] - n.iloc[-21]) / n.iloc[-21] * 100 if len(n) >= 21 else 0.0
        )
    except Exception:
        return {
            "nifty_day_pct": 0.0,
            "sector_day_pct": 0.0,
            "divergence_note": "",
            "india_vix": 0.0,
            "nifty_10d_pct": 0.0,
            "nifty_20d_pct": 0.0,
        }
    return {
        "nifty_day_pct": round(nifty_day, 2),
        "sector_day_pct": 0.0,
        "divergence_note": "",
        "india_vix": round(vix_val, 2),
        "nifty_10d_pct": round(nifty_10d, 2),
        "nifty_20d_pct": round(nifty_20d, 2),
    }


def run_backtest(
    db_path: str = "backtest_data.db",
    start: date = date(2022, 1, 1),
    end: date = date(2025, 12, 31),
    hybrid_mode: bool = True,
) -> tuple[list[ClosedTrade], list[tuple[date, float]], list[int]]:
    """Replay the strategy day by day over historical bars.

    Each day, in order: fill yesterday's signals at today's open, check exits
    against today's bar, update trailing stops on the close, then score new
    candidates for tomorrow. Signals are always acted on the following day, so
    no decision uses a price it could not have known.

    Returns (closed_trades, equity_curve, all_candidate_scores).
    """
    store = BacktestStore(db_path)
    trading_days = store.get_trading_days(start, end)
    warmup_start = date(start.year - 1, start.month, start.day)
    all_bars = store.preload(warmup_start, end)
    store.close()

    if not trading_days or not all_bars:
        logger.error("backtest_no_data", db=db_path)
        return [], [], []

    nifty = all_bars.get("^NSEI", pd.DataFrame())
    vix = all_bars.get("^INDIAVIX", pd.DataFrame())
    nifty_close = nifty["Close"] if not nifty.empty else None
    universe = sorted(t for t in all_bars if not t.startswith("^"))

    logger.info("backtest_init", trading_days=len(trading_days), universe=len(universe))

    cash: float = settings.starting_capital
    open_positions: list[Position] = []
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[tuple[date, float]] = []
    pending_entries: list[dict] = []
    all_scores: list[int] = []

    for idx, day in enumerate(trading_days):
        ts = pd.Timestamp(day)

        # 1. Execute yesterday's signals at today's open
        for p in pending_entries:
            if len(open_positions) >= settings.max_positions:
                break
            bars = all_bars.get(p["ticker"])
            if bars is None or ts not in bars.index:
                continue
            entry_price = float(bars.at[ts, "Open"])
            if entry_price <= 0:
                continue
            position_budget = min(
                cash, settings.starting_capital * settings.max_position_pct
            )
            shares = int(position_budget / entry_price)
            if shares <= 0:
                continue
            capital_used = shares * entry_price
            cash -= capital_used

            atr_pct = p.get("atr_pct", 0.0)
            stop = stop_pct(atr_pct)

            open_positions.append(
                Position(
                    ticker=p["ticker"],
                    entry_date=day,
                    entry_price=entry_price,
                    stop_price=entry_price * (1 - stop),
                    target_price=entry_price * (1 + target_pct(atr_pct)),
                    shares=shares,
                    capital_used=capital_used,
                    score=p["score"],
                    atr_pct=atr_pct,
                    peak_price=entry_price,
                )
            )
        pending_entries = []

        # 2. Check exits on today's bar (using EOD trail stop from yesterday)
        for pos in list(open_positions):
            bars = all_bars.get(pos.ticker)
            if bars is None or ts not in bars.index:
                continue
            result = _check_exit(pos, bars.loc[ts], day)
            if result is None:
                continue
            exit_price, reason = result
            proceeds = pos.shares * exit_price
            pnl = proceeds - pos.capital_used
            cash += proceeds
            closed_trades.append(
                ClosedTrade(
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    exit_date=day,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=pnl / pos.capital_used * 100,
                    exit_reason=reason,
                    score=pos.score,
                )
            )
            open_positions.remove(pos)

        # 2.5. EOD trailing stop update
        eod_exits: list[tuple[Position, float]] = []
        hybrid_count = sum(1 for p in open_positions if p.hybrid_active)
        for pos in open_positions:
            bars = all_bars.get(pos.ticker)
            if bars is None or ts not in bars.index:
                continue
            close_p = float(bars.at[ts, "Close"])

            was_trailing = pos.trail_stop > 0

            pos.peak_price, new_trail, active = update_trail(
                close=close_p,
                entry_price=pos.entry_price,
                atr_pct=pos.atr_pct,
                peak_price=pos.peak_price,
                trail_stop=pos.trail_stop,
                stop_price=pos.stop_price,
            )
            if not active and not was_trailing:
                continue
            pos.trail_stop = new_trail

            if (
                active
                and hybrid_mode
                and not pos.hybrid_active
                and hybrid_count < settings.max_hybrid_positions
            ):
                pos.hybrid_active = True
                hybrid_count += 1

            if close_p <= pos.trail_stop:
                eod_exits.append((pos, close_p))

        for pos, close_p in eod_exits:
            if pos not in open_positions:
                continue
            proceeds = pos.shares * close_p
            pnl = proceeds - pos.capital_used
            cash += proceeds
            closed_trades.append(
                ClosedTrade(
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    exit_date=day,
                    entry_price=pos.entry_price,
                    exit_price=close_p,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=pnl / pos.capital_used * 100,
                    exit_reason="trail",
                    score=pos.score,
                )
            )
            open_positions.remove(pos)

        # 3. Generate new signals from today's close
        capacity = settings.max_positions - len(open_positions)
        asof_close = nifty_close.loc[:ts] if nifty_close is not None else None
        if capacity > 0 and not regime_blocked(asof_close):
            held = {p.ticker for p in open_positions}
            mkt_ctx = _market_context(nifty, vix, ts)
            signal_candidates: list[dict] = []

            for ticker in universe:
                if ticker in held:
                    continue
                bars = all_bars.get(ticker)
                if bars is None:
                    continue
                bars_asof = bars.loc[:ts]
                if len(bars_asof) < 50:
                    continue
                try:
                    ind = compute_indicators(bars_asof)
                except Exception:
                    continue

                if _compute_signal(ind) != "BUY":
                    continue

                candidate, _ = evaluate_candidate(ind)
                if candidate is None:
                    continue

                est = ind["current_price"]
                try:
                    score = compute_rules_confidence(
                        {"signal": "BUY", "indicators": ind},
                        {
                            "stop_loss": est * (1 - stop_pct(ind.get("atr_pct", 0.0))),
                            "take_profit": est
                            * (1 + target_pct(ind.get("atr_pct", 0.0))),
                        },
                        mkt_ctx,
                    )["score"]
                except Exception as e:
                    logger.warning("score_failed", ticker=ticker, day=day, error=str(e))
                    continue
                all_scores.append(score)

                if score >= settings.rules_confidence_threshold:
                    signal_candidates.append(
                        {
                            "ticker": ticker,
                            "score": score,
                            "screener_score": candidate["screener_score"],
                            "atr_pct": ind["atr_pct"],
                        }
                    )

            signal_candidates.sort(key=lambda x: x["screener_score"], reverse=True)
            pending_entries = signal_candidates[:capacity]

        # 4. Daily equity snapshot
        equity = cash
        for pos in open_positions:
            bars = all_bars.get(pos.ticker)
            price = (
                float(bars.at[ts, "Close"])
                if bars is not None and ts in bars.index
                else pos.entry_price
            )
            equity += pos.shares * price
        equity_curve.append((day, equity))

        if idx % 50 == 0:
            logger.info(
                "backtest_progress",
                day=day,
                equity=round(equity),
                open=len(open_positions),
                trades=len(closed_trades),
            )

    # Force-close any surviving positions at final day's close
    if trading_days:
        last_ts = pd.Timestamp(trading_days[-1])
        for pos in list(open_positions):
            bars = all_bars.get(pos.ticker)
            price = (
                float(bars.at[last_ts, "Close"])
                if bars is not None and last_ts in bars.index
                else pos.entry_price
            )
            proceeds = pos.shares * price
            pnl = proceeds - pos.capital_used
            cash += proceeds
            closed_trades.append(
                ClosedTrade(
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    exit_date=trading_days[-1],
                    entry_price=pos.entry_price,
                    exit_price=price,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=pnl / pos.capital_used * 100,
                    exit_reason="end_of_backtest",
                )
            )

    final_equity = equity_curve[-1][1] if equity_curve else settings.starting_capital
    logger.info(
        "backtest_done", trades=len(closed_trades), final_equity=round(final_equity)
    )
    return closed_trades, equity_curve, all_scores
