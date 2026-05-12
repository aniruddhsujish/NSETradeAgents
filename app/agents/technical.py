import warnings
import yfinance as yf
import pandas as pd
import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from app.core.config import settings
from app.utils.indicators import compute_indicators
from app.utils.prompt_helpers import format_market_context

logger = structlog.get_logger()
llm = ChatAnthropic(model=settings.llm_model_fast, max_tokens=500, temperature=0, api_key=settings.anthropic_api_key)  # type: ignore


class TechnicalSignal(BaseModel):
    signal: str = Field(description="BUY, HOLD or SELL")
    strength: int = Field(description="Conviction score 0-100")
    summary: str = Field(description="2-3 sentence reasoning")


chain = llm.with_structured_output(TechnicalSignal)


def run_technical_analysis(
    ticker: str,
    market_context: dict | None = None,
    ticker_df=None,
) -> dict:
    logger.info("technical_start", ticker=ticker)

    if ticker_df is not None:
        df = ticker_df
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(
                ticker, period="12mo", interval="1d", progress=False, auto_adjust=True
            )

    if df is None or len(df) < 50:
        logger.warning("technical_no_data", ticker=ticker)
        return {
            "signal": "HOLD",
            "strength": 0,
            "summary": "Insufficient price data",
            "indicators": {},
        }

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna(subset=["Close", "Volume"])
    ind = compute_indicators(df)

    mkt_block = format_market_context(market_context)

    sma200_str = f"Rs.{ind['sma200']}" if ind["sma200"] else "N/A (< 200 days data)"

    prompt = f"""You are a technical analyst evaluating an NSE-listed stock for a swing trade (hold 1-4 weeks).

Ticker: {ticker}
{mkt_block}
Technical indicators:
- Price: Rs.{ind['current_price']} | Day change: {ind['day_change_pct']}%
- SMA50: Rs.{ind['sma50']} | SMA200: {sma200_str}
- RSI(14): {ind['rsi']}
- MACD line: {ind['macd']} | Signal: {ind['macd_signal']} | Histogram: {ind['macd_hist']} (prev: {ind['macd_hist_prev']}) | Trend: {ind['macd_hist_trend']}
- Bollinger Bands -- Upper: Rs.{ind['bb_upper']}  Mid: Rs.{ind['bb_mid']}  Lower: Rs.{ind['bb_lower']}
- ATR%: {ind['atr_pct']}%
- Volume ratio (today vs 20d avg): {ind['volume_ratio']}x
- Momentum 5d: {ind['momentum_5d']}% | 20d: {ind['momentum_20d']}%

Analyse these indicators for a swing trade. Follow this priority order:
1. TREND (primary gate) -- if price is NOT above both SMA50 and SMA200, signal HOLD regardless of other indicators
2. MOMENTUM -- RSI 55-70 is the ideal swing zone; MACD histogram expanding means momentum is accelerating
3. VOLATILITY -- ATR% should be > 1.5% to deliver meaningful returns in 1-4 weeks
4. VOLUME -- volume ratio > 2x confirms conviction behind the move
5. MARKET CONTEXT -- bearish Nifty or weak sector reduces conviction; factor into STRENGTH, not necessarily SIGNAL

STRENGTH reflects how cleanly the setup meets swing trade criteria —
consider RSI position within the ideal zone, MACD momentum direction,
volume conviction, and how extended the move already is.
90-100: textbook setup, 70-89: solid with minor reservations,
50-69: marginal, below 50: weak (prefer HOLD)."""

    try:
        result: TechnicalSignal = chain.invoke([HumanMessage(content=prompt)])  # type: ignore[assignment]
        signal = result.signal.upper()
        strength = result.strength
        summary = result.summary

        logger.info("technical_done", ticker=ticker, signal=signal, strength=strength)
        return {
            "signal": signal,
            "strength": strength,
            "summary": summary,
            "indicators": ind,
        }
    except Exception as e:
        logger.error("technical_llm_failed", ticker=ticker, error=str(e))
        return {
            "signal": "HOLD",
            "strength": 0,
            "summary": f"LLM error: {e}",
            "indicators": ind,
        }
