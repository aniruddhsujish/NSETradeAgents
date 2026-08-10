from typing import Any, TypedDict


class TradingState(TypedDict):
    # Input
    ticker: str
    portfolio_cash: float
    open_positions: int
    open_position_sectors: list[str]

    # Pre-fetched market data (loaded once before parallel agents)
    ticker_df: Any  # pd.DataFrame — 12mo price history
    ticker_info: dict | None  # yf.Ticker(ticker).info
    nifty_df: Any  # pd.DataFrame — Nifty 50 recent data
    vix_df: Any  # pd.DataFrame - India VIX recent data

    # Derived / computed
    current_price: float
    market_context: dict | None
    fundamental_result: dict | None

    # Agent outputs
    technical_signals: dict | None
    risk_result: dict | None

    # Final
    trade_result: dict | None
    rules_score: int | None
    rules_bands: dict | None
