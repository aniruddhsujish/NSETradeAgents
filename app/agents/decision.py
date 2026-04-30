import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from app.core.config import settings
from app.utils.prompt_helpers import format_market_context

logger = structlog.get_logger()
llm = ChatAnthropic(model=settings.llm_model_smart, max_tokens=600, temperature=0, api_key=settings.anthropic_api_key)  # type: ignore


class DecisionSignal(BaseModel):
    action: str = Field(description="BUY, HOLD or SELL")
    confidence: int = Field(description="Confidence score 0-100")
    reasoning: str = Field(
        description="3-4 sentence reasoning synthesising all signals"
    )


chain = llm.with_structured_output(DecisionSignal)


def run_decision(
    ticker: str,
    current_price: float,
    technical: dict,
    sentiment: dict,
    risk: dict,
    market_context: dict | None = None,
    fundamental: dict | None = None,
) -> dict:
    logger.info("decision_start", ticker=ticker)

    mkt_block = format_market_context(market_context)

    fund = fundamental or {}
    fund_block = (
        f"""
    --- FUNDAMENTAL CHECK ---
    Approved: {fund.get('approved', True)} | {fund.get('notes', 'N/A')}
    Flags: {fund.get('block_reasons') or 'None'}
    """
        if fundamental
        else ""
    )

    prompt = f"""You are a senior portfolio manager at a quantitative hedge fund making a final swing trade decision for an NSE-listed smallcap/midcap stock. Two specialist Haiku models have completed
    technical and sentiment analysis. your role is NOT to repeat their findings - it is to add a layer of judgement they cannot: cross-signal consistency, entry timing, and risk-adjusted conviction.

    Ticker: {ticker} | Current price: Rs.{current_price}
    {mkt_block}
    --- TECHNICAL ANALYSIS ---
    Signal: {technical.get('signal')} | Strength: {technical.get('strength')}/100
    {technical.get('summary')}

    --- SENTIMENT ANALYSIS ---
    Signal: {sentiment.get('signal')} | Score: {sentiment.get('score')} (-100 to 100)
    {sentiment.get('summary')}

    --- RISK ASSESSMENT ---
    Approved: {risk.get('approved')} | {risk.get('notes')}
    Block reasons: {risk.get('block_reasons') or 'None'}
    {fund_block}

    Apply this decision framework in order:

    1. RISK GATE (hard rule) - if risk is NOT approved, output HOLD immediately. Risk gates are non-negotiable.

    2. SIGNAL ALIGNMENT - assess how well signals agree:
        - Both BUY -> string case, proceed to conviction scoring
        - Technical BUY + Sentiment HOLD -> acceptable, wight technical more (price action leads news in swing trade)
        - Technical BUY + Sentiment SELL -> high conflict, require strength > 75 to proceed, otherwise HOLD
        - Technical HOLd or SELL -> output HOLD regardless of sentiment
    
    3. ENTRY TIMING - even if signals align, ask: is this a good entry point RIGHT NOW?
        - Is the stock extended (up >5% today)? Poor entry - wait for pullback
        - Is it near a round number resistance (e.g Rs.500, Rs.1000, Rs.2000)? Reduce confidence
        - Has momentum been building (MACD expanding, RSI rising)? good entry
        - Is volume confirming the move? no volume = weak conviction
    
    4. MARKET CONTEXT ADJUSTMENT - adjust confidence, not signal:
        - Bearish Nifty (down >1%): reduce confidence by 15 points
        - Bearish sector: reduce confidence by 10 points
        - Stock showing relative strength against weak market: add 10 points (strong signal)

    5. CONVICTION THRESHOLD - only output BUY if final confidence >= {settings.min_confidence * 100:.0f}.
        A marginal BUY at 68% confidence is worse than a HOLD - missed trades cost nothing, bad trades cost capital.

    6. SKEPTICISM CHECK - if everything looks perfect (all BUY, high strength, positive sentiment), be slightly skeptical. Markets rarely offer free money. Ask: what could go wrong? Factor that into reasoning.

    CONFIDENCE scale: 85-100 = very high conviction, 70-84 = moderate, below 70 = do not trade.

    Your reasoning MUST cite: (a) which signal drove the decision, (b) what the key risk is, (c) why NOW is or isn't a good entry."""

    try:
        result: DecisionSignal = chain.invoke([HumanMessage(content=prompt)])  # type: ignore[assignment]
        action = result.action.upper()
        confidence = result.confidence
        reasoning = result.reasoning

        if action not in ("BUY", "HOLD", "SELL"):
            action = "HOLD"
        confidence = max(0, min(100, confidence))

        logger.info(
            "decision_done", ticker=ticker, action=action, confidence=confidence
        )
        return {"action": action, "confidence": confidence, "reasoning": reasoning}

    except Exception as e:
        logger.error("decision_failed", ticker=ticker, error=str(e))
        return {"action": "HOLD", "confidence": 0, "reasoning": f"Decision error: {e}"}
