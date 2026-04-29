import warnings
import requests
import pandas as pd
import pytz
import yfinance as yf
import structlog
from datetime import datetime
from functools import lru_cache
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import setup_logging
from app.core.database import init_db
from app.portfolio.simulator import simulator

setup_logging()
logger = structlog.get_logger()

IST = pytz.timezone("Asia/Kolkata")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com",
}


@lru_cache(maxsize=1)
def _load_nse_holidays(year: int) -> set[str]:
    resp = requests.get(
        "https://www.nseindia.com/api/holiday-master?type=trading",
        headers=NSE_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    holidays = {entry["tradingDate"] for entry in resp.json().get("CM", [])}
    logger.info("nse_holidays_loaded", count=len(holidays), year=year)
    return holidays


def _is_market_open() -> bool:
    now = datetime.now(IST)

    if now.weekday() >= 5:
        return False

    try:
        holidays = _load_nse_holidays(now.year)
        if now.strftime("%d-%b-%Y") in holidays:
            logger.info(
                "market_closed", reason="NSE holiday", date=now.strftime("%d-%b-%Y")
            )
            return False
    except Exception as e:
        logger.warning("holiday_check_failed", error=str(e))

    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def review_positions() -> None:
    if not _is_market_open():
        logger.info("position_review_skipped", reason="market closed")
        return

    portfolio = simulator.get_portfolio_state()
    positions = portfolio["positions"]

    if not positions:
        logger.info("position_review_no_open_positions")
        return

    tickers = [position["ticker"] for position in positions]
    logger.info("position_review_start", tickers=tickers)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(
                tickers,
                period="1d",
                interval="5m",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
            )
    except Exception as e:
        logger.error("position_review_fetch_failed", error=str(e))
        return

    if raw is None or raw.empty:
        logger.warning("position_review_no_data")
        return

    live_prices: dict[str, float] = {}

    for position in positions:
        ticker = position["ticker"]
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close_series = raw[ticker]["Close"]
            else:
                close_series = raw["Close"]

            current_price = float(close_series.dropna().iloc[-1])
            live_prices[ticker] = current_price
        except Exception as e:
            logger.error("position_review_fetch_failed", ticker=ticker, error=str(e))
            continue

        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        if current_price <= stop_loss:
            logger.info(
                "position_review_stop_hit",
                ticker=ticker,
                price=current_price,
                stop_loss=stop_loss,
            )
            simulator.close_trade(ticker, current_price, reason="sl")
        elif current_price >= take_profit:
            logger.info(
                "position_review_target_hit",
                ticker=ticker,
                price=current_price,
                reason="tp",
            )
            simulator.close_trade(ticker, current_price, reason="tp")
        else:
            logger.info(
                "position_review_hold",
                ticker=ticker,
                price=current_price,
                pct_to_stop=round((current_price - stop_loss) / current_price * 100, 2),
                pct_to_target=round(
                    (take_profit - current_price) / current_price * 100, 2
                ),
            )
    simulator.save_snapshot(open_prices=live_prices if live_prices else None)


def start() -> None:
    init_db()
    logger.info("scheduler_starting")

    from main import run_scan

    sched = BlockingScheduler(timezone=IST)

    sched.add_job(
        run_scan,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone=IST),
        name="morning_scan",
    )

    sched.add_job(review_positions, IntervalTrigger(minutes=15), name="position_review")

    logger.info(
        "scheduler_ready",
        morning_scan="09:30 IST Mon-Fri",
        review_position="Every 15 mins",
    )

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler_stopped")


if __name__ == "__main__":
    start()
