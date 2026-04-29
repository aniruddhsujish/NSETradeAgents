from typing import Any, TypedDict


class TradingState(TypedDict):
    # Input
    ticker: str
    portfolio_cash: float
    open_positions: int

    # Pre-fetched market data (loaded once before parallel agents)
    ticker_df: Any          # pd.DataFrame — 12mo price history
    ticker_info: dict | None  # yf.Ticker(ticker).info
    nifty_df: Any           # pd.DataFrame — Nifty 50 recent data

    # Derived / computed
    current_price: float
    market_context: dict | None

    # Agent outputs
    technical_signals: dict | None
    sentiment_data: dict | None
    risk_result: dict | None
    decision: dict | None

    # Final
    trade_result: dict | None
