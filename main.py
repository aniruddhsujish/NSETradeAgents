from datetime import date

import structlog
from app.core.logging import setup_logging
from app.core.database import init_db, get_db
from app.models.models import DecisionRecord
from app.core.config import settings
from app.screener.universe import fetch_universe
from app.screener.filters import screen
from app.graph.graph import analyze_ticker
from app.portfolio.simulator import simulator

import subprocess

setup_logging()
logger = structlog.get_logger()


def _git_sha() -> str | None:
    """Short commit hash, recorded on decisions so results trace to code."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return None


GIT_SHA = _git_sha()


def run_scan():
    """Run the daily scan: screen the universe, analyse candidates, open trades.

    Writes a decision record for every candidate it evaluates, bought or not,
    which is what makes rejected trades measurable later. Stops early if the
    circuit breaker is active or the portfolio is full; a failure on one
    ticker never abandons the rest.
    """
    logger.info("scan_start")

    tickers = fetch_universe()

    candidates = screen(tickers)

    if not candidates:
        logger.info("scan_no_candidates")
        return

    # Circuit breaker - pause new entires if portfolio down >8% from 30-day peak
    if simulator.is_circuit_breaker_active():
        logger.info("scan_circuit_breaker_triggered")
        return

    logger.info("scan_candidates_found", count=len(candidates))

    for candidate in candidates:
        ticker = candidate["ticker"]

        portfolio = simulator.get_portfolio_state()

        if portfolio["open_positions"] >= settings.max_positions:
            logger.info("scan_max_positions_reached", open=portfolio["open_positions"])
            break

        open_tickers = {position["ticker"] for position in portfolio["positions"]}
        if ticker in open_tickers:
            logger.info("scan_already_holding", ticker=ticker)
            continue

        logger.info("scan_analysing", ticker=ticker, score=candidate["score"])

        open_position_sectors = [p["sector"] for p in portfolio["positions"]]
        try:
            final_state = analyze_ticker(
                ticker=ticker,
                portfolio_cash=portfolio["cash"],
                open_positions=portfolio["open_positions"],
                open_position_sectors=open_position_sectors,
            )
        except Exception as e:
            logger.error("scan_ticker_failed", ticker=ticker, error=str(e))
            continue

        trade_result = final_state.get("trade_result") or {}
        executed = trade_result.get("executed", False)
        rules_score = final_state.get("rules_score")

        block_reasons = trade_result.get("reasons")
        block_reason = ", ".join(block_reasons) if block_reasons else None

        ind = (final_state.get("technical_signals") or {}).get("indicators") or {}
        bands = final_state.get("rules_bands") or {}

        with get_db() as db:
            db.add(
                DecisionRecord(
                    as_of=date.today(),
                    ticker=ticker,
                    git_sha=GIT_SHA,
                    score=rules_score,
                    entry_timing=bands.get("entry_timing"),
                    momentum_quality=bands.get("momentum_quality"),
                    risk_reward_view=bands.get("risk_reward_view"),
                    market_regime=bands.get("market_regime"),
                    price=ind.get("current_price"),
                    rsi=ind.get("rsi"),
                    atr_pct=ind.get("atr_pct"),
                    volume_ratio=ind.get("volume_ratio"),
                    momentum_5d=ind.get("momentum_5d"),
                    day_change_pct=ind.get("day_change_pct"),
                    entered=executed,
                    block_reason=block_reason,
                )
            )
        if executed:
            simulator.open_trade(
                trade_result=trade_result,
                technical=final_state.get("technical_signals") or {},
            )

    simulator.save_snapshot()
    logger.info("scan_complete")


if __name__ == "__main__":
    init_db()
    run_scan()
