import structlog
from app.core.logging import setup_logging
from app.core.database import init_db
from app.core.config import settings
from app.screener.universe import fetch_universe
from app.screener.filters import screen
from app.graph.graph import analyze_ticker
from app.portfolio.simulator import simulator

setup_logging()
logger = structlog.get_logger()


def run_scan():
    logger.info("scan_start")

    tickers = fetch_universe()

    candidates = screen(
        tickers,
        {
            "min_volume_ratio": settings.min_volume_ratio,
            "min_volume_shares": settings.min_volume_shares,
            "min_avg_daily_value": settings.min_avg_daily_value,
            "max_day_change_pct": settings.max_day_change_pct,
            "min_price": settings.min_price,
            "min_atr_pct": settings.min_atr_pct,
            "rsi_min": settings.rsi_min,
            "rsi_max": settings.rsi_max,
        },
    )

    if not candidates:
        logger.info("scan_no_candidates")
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

        try:
            final_state = analyze_ticker(
                ticker=ticker,
                portfolio_cash=portfolio["cash"],
                open_positions=portfolio["open_positions"],
            )
        except Exception as e:
            logger.error("scan_ticker_failed", ticker=ticker, error=str(e))
            continue

        trade_result = final_state.get("trade_result") or {}
        if trade_result.get("executed"):
            simulator.open_trade(
                trade_result=trade_result,
                technical=final_state.get("technical_signals") or {},
                sentiment=final_state.get("sentiment_data") or {},
            )
    simulator.save_snapshot()
    logger.info("scan_complete")


if __name__ == "__main__":
    init_db()
    run_scan()
