import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from app.core.config import settings
from app.utils.prompt_helpers import format_market_context

logger = structlog.get_logger()


class DecisionSignal(BaseModel):
    action: str = Field(description="BUY, HOLD or SELL")
    kill_case: str | None = Field(
        default=None,
        description="Single strongest reason this trade fails - specific to this setup, not generic. Required for BUY only.",
    )
    strong_setup_conditions: str | None = Field(
        default=None,
        description="What would have to be true for this to score well across most dimensions. Required for BUY only.",
    )
    weak_setup_conditions: str | None = Field(
        default=None,
        description="What would have to be true for this to score poorly across most dimensions. Required for BUY only.",
    )
    signal_alignment: str | None = Field(
        default=None,
        description="STRONG, ACCEPTABLE, or CONFLICTED. Null if action is not BUY.",
    )
    entry_timing: str | None = Field(
        default=None,
        description="IDEAL, ACCEPTABLE, or POOR. Null if action is not BUY.",
    )
    momentum_quality: str | None = Field(
        default=None,
        description="STRONG, MODERATE, or WEAK. Null if action is not BUY.",
    )
    risk_reward_view: str | None = Field(
        default=None,
        description="FAVORABLE, UNFAVORABLE, or NEUTRAL. Null if action is not BUY.",
    )
    setup_concern: str | None = Field(
        default=None,
        description="NONE, MINOR, or SIGNIFICANT. Null if action is not BUY",
    )
    reasoning: str = Field(
        description="3-4 sentences citing which dimension(s) drove the decision, the key risk, and why now is or isn't a good entry."
    )


def run_decision(
    ticker: str,
    current_price: float,
    technical: dict,
    sentiment: dict,
    risk: dict,
    market_context: dict | None = None,
    fundamental: dict | None = None,
    model: str | None = None,
) -> dict:

    _llm = ChatAnthropic(
        model=model or settings.llm_model_smart,
        max_tokens=1200,
        temperature=0,
        api_key=settings.anthropic_api_key,
    )  # type: ignore
    chain = _llm.with_structured_output(DecisionSignal)
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

    prompt = f"""You are scoring a swing trade setup for an NSE-listed stock against a defined rubric. Be specific and falsifiable.

    Ticker: {ticker} | Current price: Rs.{current_price}
    {mkt_block}
    --- RAW SIGNALS --- 
    Technical: {technical.get('signal')} | Strength: {technical.get('strength')}/100
    Sentiment: {sentiment.get('signal')} | Score: {sentiment.get('score')} (-100 to 100)
    {fund_block}

    --- AGENT SUMMARIES ---
    Technical summary: {technical.get('summary')}
    Sentiment summary: {sentiment.get('summary')}

    --- RISK NOTES ---
    {risk.get('notes')}
    Block reasons: {risk.get('block_reasons') or 'None'}

    Step 1 - DEcide action: BUY, HOLD, or SELL.
    If HOLD or SELL: set all dimension fields to null and explain why in reasoning. Stop here.

    Step 2 - If BUY, write before scoring:
    - kill_case: the single most specific reason this trade fails (not "marlet could tunr", something falsifiable about this setup)
    - strong_setup_conditions: what would have to be true for this to score well across most dimensions
    - weak_setup_conditions: what would have to be true for this to score poorly across most dimensions

    Step 3 - Score each dimension using the rubric below. Every band must be falsifiable - if you cannot point to a specific data point justifying your choice, pick the weaker band.

    SIGNAL_ALIGNMENT - how well do technical, sentiment and fundamental signals agree?
    - STRONG: technical BUY + sentiment BUY, signals clearly reinforce each other
    - ACCEPTABLE: technical BUY + sentiment HOLD, or one signal notable stronger than the other (strength delta > 20 points)
    - CONFLICTED: technical BUY + sentiment SELL, or signals meaningfully contradict

    ENTRY_TIMING - is this a good entry point right now?
    - IDEAL: MACD historgram expanding 2+ consecutive bars, RSI rising and below 67, volume ratio > 2x, day change < 3%
    - ACCEPTABLE: 3 of the 4 IDEAL conditions met
    - POOR: stock up > 5% today, OR near round number resistance (Rs. 500/1000/2000/5000), OR volume ratio < 1.5x

    MOMENTUM_QUALITY - is momentum building or fading?
    - STRONG: RSI in 62-67 zone, MACD histogram expanding 2+ bars, 5d momentum 3-8%
    - MODERATE: RSI in 55-70 but outside ideal zone, mixed MACD, momentum outside 3-8% range
    - WEAK: RSI above 70 or below 55, MACD contracting, 5d momentum > 10% (overextended) or < 1%

    RISK_REWARD_VIEW - does this setup justify the capital at risk?
    - FAVORABLE: risk/reward ratio >= 2.5x
    - NEUTRAL: risk/reward ratio 1.5x to 2.5x
    - UNFAVORABLE: risk/reward ratio < 1.5x

    SETUP_CONCERN - what is the most significant thing could go wrong with this trade?
    - NONE: no notable red flags specific to this setup
    - MINOR: one identifiable concern but not a dealbreaker
    - SIGNIFICANT: multiple red flags, or one that materially undermines the thesis

    Accross all BUY setups reaching this stage: roughly 15% should score well across most dimensions, 60% mid-tier, 25% marginal. do not default to mid-tier on every dimension.

    Your reasoning must cite: (a) which dimension most influenced the action, (b) the key risk, (c) why now is or isn't a good entry.
    """

    try:
        result: DecisionSignal = chain.invoke([HumanMessage(content=prompt)])  # type: ignore[assignment]
        action = result.action.upper()

        if action not in ("BUY", "HOLD", "SELL"):
            action = "HOLD"

        logger.info("decision_done", ticker=ticker, action=action)

        if action != "BUY":
            return {
                "action": action,
                "signal_alignment": None,
                "entry_timing": None,
                "momentum_quality": None,
                "risk_reward_view": None,
                "setup_concern": None,
                "kill_case": None,
                "strong_setup_conditions": None,
                "weak_setup_conditions": None,
                "reasoning": result.reasoning,
            }

        return {
            "action": action,
            "signal_alignment": result.signal_alignment,
            "entry_timing": result.entry_timing,
            "momentum_quality": result.momentum_quality,
            "risk_reward_view": result.risk_reward_view,
            "setup_concern": result.setup_concern,
            "kill_case": result.kill_case,
            "strong_setup_conditions": result.strong_setup_conditions,
            "weak_setup_conditions": result.weak_setup_conditions,
            "reasoning": result.reasoning,
        }

    except Exception as e:
        logger.error("decision_failed", ticker=ticker, error=str(e))
        return {
            "action": "HOLD",
            "signal_alignment": None,
            "entry_timing": None,
            "momentum_quality": None,
            "risk_reward_view": None,
            "setup_concern": None,
            "kill_case": None,
            "strong_setup_conditions": None,
            "weak_setup_conditions": None,
            "reasoning": f"Decision error: {e}",
        }
