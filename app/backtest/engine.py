from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from app.backtest.store import BacktestStore
from app.agents.technical import _compute_signal
from app.core.config import settings
from app.utils.indicators import compute_indicators
from app.utils.scoring import compute_rules_confidence

logger = structlog.get_logger()


@dataclass
class Position:
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
    open_p  = float(bar["Open"])
    high_p  = float(bar["High"])
    low_p   = float(bar["Low"])
    close_p = float(bar["Close"])

    effective_stop = pos.trail_stop if pos.trail_stop > 0 else pos.stop_price
    stop_hit   = low_p <= effective_stop
    target_hit = (not pos.hybrid_active) and high_p >= pos.target_price
    days_held  = (today - pos.entry_date).days

    if stop_hit and target_hit:
        return min(open_p, effective_stop), "stop"
    if stop_hit:
        return min(open_p, effective_stop), "trail" if pos.trail_stop > 0 else "stop"
    if target_hit:
        return max(open_p, pos.target_price), "target"
    if (not pos.hybrid_active) and days_held >= settings.max_hold_days:
        return close_p, "timeout"
    return None


def _market_context(nifty: pd.DataFrame, vix: pd.DataFrame, ts: pd.Timestamp) -> dict:
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


def _regime_blocked(nifty: pd.DataFrame, ts: pd.Timestamp) -> bool:
    if nifty.empty:
        return False
    try:
        n_close = nifty.loc[:ts, "Close"]
        if len(n_close) < settings.regime_sma_period:
            return False
        sma50 = float(n_close.tail(settings.regime_sma_period).mean())
        return float(n_close.iloc[-1]) < sma50
    except Exception:
        return False


def run_backtest(
    db_path: str = "backtest_data.db",
    start: date = date(2022, 1, 1),
    end: date = date(2025, 12, 31),
    hybrid_mode: bool = True,
) -> tuple[list[ClosedTrade], list[tuple[date, float]], list[int]]:
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
            if atr_pct > 0:
                stop_pct = min(max(2.5 * atr_pct / 100, 0.05), 0.10)
            else:
                stop_pct = settings.stop_loss_pct

            open_positions.append(
                Position(
                    ticker=p["ticker"],
                    entry_date=day,
                    entry_price=entry_price,
                    stop_price=entry_price * (1 - stop_pct),
                    target_price=entry_price * (1 + settings.take_profit_pct),
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

            new_peak = max(pos.peak_price, close_p)
            pos.peak_price = new_peak

            if close_p < pos.entry_price * (1 + settings.trail_activation_pct):
                continue

            trail_pct = (
                min(max(2.0 * pos.atr_pct / 100, settings.trail_min_pct), settings.trail_max_pct)
                if pos.atr_pct > 0
                else settings.trail_min_pct
            )
            new_trail = max(new_peak * (1 - trail_pct), pos.trail_stop)
            new_trail = max(new_trail, pos.stop_price)  # never trail below initial stop
            pos.trail_stop = new_trail

            if hybrid_mode and not pos.hybrid_active and hybrid_count < settings.max_hybrid_positions:
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
        if capacity > 0 and not _regime_blocked(nifty, ts):
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

                # Screener filters (mirrors filters.py)
                if ind["avg_daily_value"] < settings.min_avg_daily_value:
                    continue
                if ind["current_price"] < settings.min_price:
                    continue
                if ind["sma200"] is None:
                    continue
                if not (ind["current_price"] > ind["sma50"] > ind["sma200"]):
                    continue
                if ind["atr_pct"] < settings.min_atr_pct:
                    continue
                if ind["day_change_pct"] > settings.max_day_change_pct:
                    continue
                if ind["volume_ratio"] < settings.min_volume_ratio:
                    continue
                if ind["today_vol"] < settings.min_volume_shares:
                    continue
                if ind["day_change_pct"] <= 0.5:
                    continue
                if not (settings.rsi_min <= ind["rsi"] <= settings.rsi_max):
                    continue
                if ind["momentum_5d"] < 2.0:
                    continue

                est = ind["current_price"]
                try:
                    score = compute_rules_confidence(
                        {"signal": "BUY", "indicators": ind},
                        {"signal": "HOLD", "score": 0},
                        {
                            "stop_loss": est * (1 - settings.stop_loss_pct),
                            "take_profit": est * (1 + settings.take_profit_pct),
                        },
                        mkt_ctx,
                    )
                except Exception:
                    continue
                all_scores.append(score)

                if score >= settings.rules_confidence_threshold:
                    vol_norm      = min(ind["volume_ratio"] / 5.0, 1.0)
                    momentum_norm = min(max(ind["momentum_5d"], -15), 15) / 15
                    atr_norm      = min(ind["atr_pct"] / 5.0, 1.0)
                    screener_score = (vol_norm * 0.40) + (momentum_norm * 0.35) + (atr_norm * 0.25)
                    signal_candidates.append({
                        "ticker": ticker,
                        "score": score,
                        "screener_score": screener_score,
                        "atr_pct": ind["atr_pct"],
                    })

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
