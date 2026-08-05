import pandas as pd
import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from app.core.config import settings
from app.utils.indicators import compute_indicators
from app.utils.market_data import safe_yf_download, extract_ticker_df
from app.utils.prompt_helpers import format_market_context

logger = structlog.get_logger()
llm = ChatAnthropic(model=settings.llm_model_fast, max_tokens=500, temperature=0, api_key=settings.anthropic_api_key)  # type: ignore


class TechnicalSignal(BaseModel):
    signal: str = Field(description="BUY, HOLD or SELL")
    strength: int = Field(description="Conviction score 0-100")
    summary: str = Field(description="2-3 sentence reasoning")


chain = llm.with_structured_output(TechnicalSignal)


def _compute_signal(ind: dict) -> str:
    current_price = ind.get("current_price", 0)
    sma50 = ind.get("sma50") or 0
    sma200 = ind.get("sma200") or 0
    rsi = ind.get("rsi", 50)

    if sma200 and current_price < sma200:
        return "HOLD"
    if current_price < sma50:
        return "HOLD"
    if rsi > settings.rsi_max:
        return "SELL"
    if settings.rsi_min <= rsi <= settings.rsi_max:
        return "BUY"
    return "HOLD"


def _compute_strength(ind: dict) -> int:
    rsi = ind.get("rsi", 50)
    macd_hist_trend = ind.get("macd_hist_trend", "mixed")
    volume_ratio = ind.get("volume_ratio", 0)
    momentum_5d = ind.get("momentum_5d", 0)

    score = 0

    if 62 <= rsi <= 67:
        score += 30
    elif 55 <= rsi <= 70:
        score += 20
    else:
        score += 5

    if macd_hist_trend == "expanding":
        score += 25
    elif macd_hist_trend == "mixed":
        score += 15

    if volume_ratio >= 2.0:
        score += 25
    elif volume_ratio >= 1.5:
        score += 15

    if momentum_5d <= 8:
        score += 20
    elif momentum_5d <= 10:
        score += 10

    return min(score, 100)


def _compute_summary(ind: dict, signal: str, strength: int) -> str:
    rsi = ind.get("rsi", 0)
    macd_trend = ind.get("macd_hist_trend", "mixed")
    volume_ratio = ind.get("volume_ratio", 0)
    momentum_5d = ind.get("momentum_5d", 0)
    return (
        f"{signal} (strength {strength}): RSI {rsi:.1f}, MACD {macd_trend}, "
        f"volume {volume_ratio:.1f}x, 5d momentum {momentum_5d:.1f}%"
    )


def run_technical_analysis(
    ticker: str,
    market_context: dict | None = None,
    ticker_df=None,
) -> dict:
    logger.info("technical_start", ticker=ticker)

    if ticker_df is not None:
        df = ticker_df
    else:
        df = safe_yf_download(ticker, period="12mo")

    if df is None or len(df) < 50:
        logger.warning("technical_no_data", ticker=ticker)
        return {
            "signal": "HOLD",
            "strength": 0,
            "summary": "Insufficient price data",
            "indicators": {},
        }

    extracted = extract_ticker_df(df, ticker)
    if extracted is not None:
        df = extracted
    df = df.dropna(subset=["Close", "Volume"])
    ind = compute_indicators(df)

    if settings.use_llm_technical:
        mkt_block = format_market_context(market_context)
        sma200_str = f"Rs.{ind['sma200']}" if ind["sma200"] else "N/A (<200 days data)"
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

        except Exception as e:
            logger.error("technical_llm_failed", ticker=ticker, error=str(e))
            signal = _compute_signal(ind)
            strength = _compute_strength(ind)
            summary = _compute_summary(ind, signal, strength)
    else:
        signal = _compute_signal(ind)
        strength = _compute_strength(ind)
        summary = _compute_summary(ind, signal, strength)

    logger.info("technical_done", ticker=ticker, signal=signal, strength=strength)
    return {
        "signal": signal,
        "strength": strength,
        "summary": summary,
        "indicators": ind,
    }
