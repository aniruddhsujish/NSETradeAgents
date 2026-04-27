import structlog
import yfinance as yf
from datetime import date
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_tavily import TavilySearch
from langchain.agents import create_agent
from pydantic import BaseModel, Field
from app.core.config import settings

logger = structlog.get_logger()

# ── LLMs ─────────────────────────────────────────────────────────────────────
research_llm = ChatAnthropic(
    model=settings.llm_model_fast, max_tokens=1000, api_key=settings.anthropic_api_key
)
scoring_llm = ChatAnthropic(
    model=settings.llm_model_fast, max_tokens=600, api_key=settings.anthropic_api_key
)

# ── Tavily search tool ────────────────────────────────────────────────────────
search_tool = TavilySearch(
    max_results=4,
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
    tavily_api_key=settings.tavily_api_key,
)

# ── Research agent (reasons about what to search, calls Tavily in a loop) ────
research_agent = create_agent(research_llm, [search_tool])


# ── Sentiment scorer ──────────────────────────────────────────────────────────
class SentimentSignal(BaseModel):
    signal: str = Field(description="BUY, HOLD or SELL")
    score: int = Field(
        description="Sentiment score -100 (very negative) to +100 (very positive)"
    )
    summary: str = Field(description="2-3 sentence reasoning citing specific news")


scoring_chain = scoring_llm.with_structured_output(SentimentSignal)


def run_sentiment_analysis(ticker: str, sector: str = "Unknown") -> dict:
    """
    Two-step sentiment analysis:
    1. Research agent autonomously decides what to search and fetches relevant news
    2. Scoring agent evaluates the findings and returns BUY/HOLD/SELL + score
    """
    logger.info("sentiment_start", ticker=ticker)

    symbol = ticker.replace(".NS", "")

    # Get company name from yfinance
    try:
        info = yf.Ticker(ticker).info
        company_name = info.get("longName") or info.get("shortName") or symbol
        if sector == "Unknown":
            sector = info.get("sector") or info.get("industry") or "Unknown"
    except Exception:
        company_name = symbol

    # ── Step 1: Research agent ────────────────────────────────────────────────
    research_prompt = f"""You are a financial research analyst preparing news briefing for a swing trade decision on {company_name} ({symbol}), an NSE-listed stock in the {sector} sector.

Today's date: {date.today().strftime("%B %d, %Y")}

Your job: search for the most relevant recent news that would affect a 1-4 week swing trade. Use the search tool intelligently — don't just search the company name. Think about what matters for THIS sector and THIS company type.

Sector-specific guidance:
- Technology/IT: search for deal wins, client additions, revenue guidance, visa policy impacts
- Pharma/Healthcare: search for USFDA approvals, drug launches, clinical trial results, ANDA filings
- Banking/Financial: search for NPA levels, credit growth, RBI policy impacts, earnings
- Auto: search for volume data, EV transition news, raw material costs
- FMCG: search for volume growth, rural demand, margin trends
- Real Estate: search for pre-sales, launches, debt levels
- Energy/Metal: search for commodity prices, order wins, capacity expansion

Make 2-3 targeted searches. Focus on news from the last 4 weeks. After searching, summarise the key findings as a structured news briefing."""

    try:
        research_result = research_agent.invoke(
            {"messages": [HumanMessage(content=research_prompt)]}
        )
        # The last message is the agent's final summary
        research_findings = research_result["messages"][-1].content
        logger.info(
            "research_done",
            ticker=ticker,
            searches=sum(
                1
                for m in research_result["messages"]
                if hasattr(m, "type") and m.type == "tool"
            ),
        )
    except Exception as e:
        logger.warning("research_failed", ticker=ticker, error=str(e))
        research_findings = f"Research unavailable: {e}"

    # ── Step 2: Sentiment scoring ─────────────────────────────────────────────
    scoring_prompt = f"""You are a buy-side equity analyst scoring sentiment for a swing trade in {company_name} ({symbol}).

Today's date: {date.today().strftime("%B %d, %Y")}

Research findings:
{research_findings}

Evaluate the findings on these dimensions:

1. MATERIALITY - Does this news actually affect the business (earnings, contracts, management, regulations, debt)?
   Ignore: generic commentary, index movements, price target changes without rationale
   Weight heavily: earnings beats/misses, large order wins, promoter buying/selling, regulatory action

2. RECENCY - News older than 2 weeks is likely priced in. Discount accordingly.

3. DIRECTION FOR SWING TRADE - You are evaluating for a SHORT-TERM trade (1-4 weeks), not long-term.
   Short-term catalysts (quarterly results, contract wins, guidance) matter more than long-term ones.

4. SENTIMENT CONTRADICTION - If news is mixed, note which side dominates.

SCORE scale: +100 = very bullish, +30 to +70 = mildly positive, 0 = neutral,
             -30 to -70 = mildly negative, -100 = severe negative catalyst
SIGNAL: BUY if score > 30, SELL if score < -30, HOLD otherwise.
Cite the specific finding driving your score in the summary."""

    try:
        result = scoring_chain.invoke([HumanMessage(content=scoring_prompt)])
        signal = result.signal.upper()
        if signal not in ("BUY", "HOLD", "SELL"):
            signal = "HOLD"
        score = max(-100, min(100, result.score))
        summary = result.summary

        logger.info("sentiment_done", ticker=ticker, signal=signal, score=score)
        return {"signal": signal, "score": score, "summary": summary}

    except Exception as e:
        logger.error("sentiment_scoring_failed", ticker=ticker, error=str(e))
        return {"signal": "HOLD", "score": 0, "summary": f"Scoring error: {e}"}
