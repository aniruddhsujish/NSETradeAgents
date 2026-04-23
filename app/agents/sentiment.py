import structlog
import yfinance as yf
from datetime import date
from tavily import TavilyClient
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from app.core.config import settings

logger = structlog.get_logger()
tavily = TavilyClient(api_key=settings.tavily_api_key)
llm = ChatAnthropic(
    model=settings.llm_model_fast, max_tokens=600, api_key=settings.anthropic_api_key
)


class SentimentSignal(BaseModel):
    signal: str = Field(description="BUY, HOLD or SELL")
    score: int = Field(
        description="Sentiment score -100 (very negative) to +100 (very positive)"
    )
    summary: str = Field(description="2-3 sentence reasoning citing specific news")


chain = llm.with_structured_output(SentimentSignal)


def run_sentiment_analysis(ticker: str) -> dict:
    logger.info("sentiment_start", ticker=ticker)

    # Strip .NS suffix for readable search query
    symbol = ticker.replace(".NS", "")

    try:
        info = yf.Ticker(ticker).info
        company_name = info.get("longName") or info.get("shortName") or symbol
    except Exception:
        company_name = symbol

    try:
        results = tavily.search(
            query=f"{company_name} ({symbol}) earnings results news announcement {date.today().year}",
            max_results=5,
            search_depth="advanced",
            include_domains=[
                "economictimes.indiatimes.com",
                "moneycontrol.com",
                "livemint.com",
                "business-standard.com",
                "financialexpress.com",
                "thehindubusinessline.com",
                "bq-prime.com",
                "reuters.com",
                "bseindia.com",
                "nseindia.com",
            ],
        )
        articles = [
            a for a in results.get("results", [])
            if a.get("title") and a.get("content")
        ]
    except Exception as e:
        logger.warning("tavily_fetch_failed", ticker=ticker, error=str(e))
        return {"signal": "HOLD", "score": 0, "summary": f"News fetch failed: {e}"}

    if not articles:
        logger.warning("sentiment_no_news", ticker=ticker)
        return {"signal": "HOLD", "score": 0, "summary": "No recent news found"}

    # Format articles for the prompt
    news_block = ""
    for i, a in enumerate(articles, 1):
        pub_date = a.get("published_date", "date unknown")
        news_block += f"{i}. [{pub_date}] {a.get('title')}\n"
        news_block += f"   {a.get('content', '')[:500]}\n\n"

    prompt = f"""You are a buy-side equity analyst specialising in NSE-listed smallcap and midcap stocks.
Your job is to assess whether recent news supports or undermines a 1-4 week swing trade in {company_name} ({symbol}).

Today's date: {date.today().strftime("%B %d, %Y")}

Recent news:
{news_block}
Evaluate the news on these dimensions:

1. MATERIALITY - Does this news actually affect the business (earnings, contracts, management, regulations, debt)?
   Ignore: generic market commentary, index movements, broker price target changes without rationale
   Weight heavily: earnings beats/misses, large order wins, promoter buying/selling, regulatory action, debt restructuring

2. RECENCY - News older than 2 weeks has likely been priced in. Discount it accordingly.

3. CREDIBILITY - Prefer news from established outlets. Treat single-source unverified reports with caution.

4. DIRECTION FOR SWING TRADE - You are evaluating for a SHORT-TERM trade (1-4 weeks), not a long-term investment.
   Positive long-term news (new factory, 3-year order book) has limited short-term impact unless it surprises the market.
   Short-term catalysts (quarterly results, contract announcements, management guidance) matter more.

5. SENTIMENT CONTRADICTION - If news is mixed, note which side dominates and by how much.

SCORE scale: +100 = very bullish catalyst, +30 to +70 = mildly positive, 0 = neutral/no catalyst,
             -30 to -70 = mildly negative, -100 = severe negative catalyst (fraud, loss, regulatory ban)
SIGNAL: BUY if score > 30, SELL if score < -30, HOLD otherwise.
Cite the specific headline driving your score in the summary."""

    try:
        result = chain.invoke([HumanMessage(content=prompt)])
        signal = result.signal.upper()
        if signal not in ("BUY", "HOLD", "SELL"):
            signal = "HOLD"
        score   = max(-100, min(100, result.score))
        summary = result.summary

        logger.info("sentiment_done", ticker=ticker, signal=signal, score=score)
        return {"signal": signal, "score": score, "summary": summary}
    except Exception as e:
        logger.error("sentiment_llm_failed", ticker=ticker, error=str(e))
        return {"signal": "HOLD", "score": 0, "summary": f"LLM error: {e}"}
