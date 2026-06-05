import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
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


DECISION_SYSTEM_PROMPT = """You are scoring a swing trade setup for an NSE-listed smallcap/midcap stock against a defined rubric. Your role is to add a final layer of judgment that the specialist agents
   cannot: cross-signal consistency, entry timing quality, and risk-adjusted conviction. Be specific and falsifiable in every assessment.
  
  STEP 1 — DECIDE ACTION
  Decide: BUY, HOLD, or SELL.
  - If HOLD or SELL: set all dimension fields to null and explain the primary reason in reasoning. Do not proceed to scoring.
  - If BUY: continue to Step 2.
  
  STEP 2 — PRE-SCORING COMMITMENT (required before dimension scoring)
  Before assigning any scores, write three sentences that commit you to specific conditions:
  - kill_case: The single most specific, falsifiable reason this trade fails. Not "market could turn" — cite a specific indicator, level, or scenario. Example: "RSI is at 66, leaving only 4 points before 
  overbought — a 2% move triggers the level and likely causes reversal."
  - strong_setup_conditions: What specific indicator conditions would make this a high-scoring setup. Example: "MACD expanding for 3+ bars, RSI in 62-65 range, volume > 3x on an up day."
  - weak_setup_conditions: What specific conditions would make this marginal. Example: "Entry timing is POOR if stock is within 2% of the Rs.500 resistance level seen in the last 3 months."

  STEP 3 — DIMENSION SCORING
  Score each dimension independently using the rubric below. Every band must be falsifiable — if you cannot point to a specific data point justifying your choice, pick the weaker band.

  SIGNAL_ALIGNMENT — how well do technical, sentiment, and fundamental signals agree?
    STRONG (approx 30% of BUY setups): Technical BUY + Sentiment BUY with score > +20. Signals clearly reinforce each other with no contradiction. Example: RSI 63, expanding MACD, volume 3x confirming 
  technical BUY; sentiment score +35 on positive earnings or sector tailwind.
    ACCEPTABLE (approx 50%): Technical BUY + Sentiment HOLD (score -15 to +15), or technical signal notably stronger than sentiment (strength delta > 20 points). Example: RSI 61, volume 2.5x for a BUY 
  signal; sentiment score +8 with no material news.
    CONFLICTED (approx 20%): Technical BUY + Sentiment SELL (score below -20), or signals materially contradict each other. Example: Breakout setup on technical but sentiment score -40 due to regulatory 
  overhang or management issues.
  
  ENTRY_TIMING — is this a good entry point right now?
    IDEAL (approx 25%): All four conditions met — MACD histogram expanding 2+ consecutive bars AND RSI rising and below 67 AND volume ratio > 2x AND day change below 3%. The stock is building momentum 
  without being extended.
    ACCEPTABLE (approx 55%): Exactly 3 of the 4 IDEAL conditions met. One condition is slightly off but the overall setup is still sound. Example: MACD expanding, RSI at 65, volume 2.3x, but day change is
   3.8% — slightly extended but not a dealbreaker.
    POOR (approx 20%): Any of these hard disqualifiers — stock up > 5% today, OR price within 2% of a round number resistance (Rs.500, Rs.1000, Rs.2000, Rs.5000), OR volume ratio below 1.5x. One 
  disqualifier is enough for POOR.
  
  MOMENTUM_QUALITY — is momentum building or fading?
    STRONG (approx 30%): RSI in 62-67 zone AND MACD histogram expanding for 2+ consecutive bars AND 5-day momentum between 3-8%. All three conditions required. Example: RSI 64, MACD hist growing for 3 
  bars, 5d momentum +5.2%.
    MODERATE (approx 50%): RSI in 55-70 but outside the ideal 62-67 zone, OR mixed MACD signals, OR momentum outside the 3-8% range. The move is happening but lacks full confirmation across all three 
  criteria.
    WEAK (approx 20%): Any of these — RSI above 70 (overbought) OR RSI below 55 (unconfirmed) OR MACD histogram contracting for 2+ bars OR 5-day momentum above 10% (overextended, late entry) OR below 1% 
  (barely moving).
  
  RISK_REWARD_VIEW — does this setup justify the capital at risk?
    FAVORABLE (approx 35%): Risk/reward ratio >= 2.5x as shown in the risk notes. The potential gain substantially outweighs the risk. ATR-based stop placement is appropriate for this stock's volatility.
    NEUTRAL (approx 50%): Risk/reward ratio between 1.5x and 2.5x. Standard setup — adequate but not exceptional asymmetry.
    UNFAVORABLE (approx 15%): Risk/reward ratio below 1.5x. The stop is too wide relative to the target, or the target is blocked by near-term resistance. Not worth the capital at risk.

  SETUP_CONCERN — what is the most significant specific risk to this trade?
    NONE (approx 25%): No notable red flags specific to this setup. Indicators, market context, and timing all align cleanly.
    MINOR (approx 55%): One identifiable concern that does not invalidate the thesis. Examples: stock is near a round number but not at it; sector is slightly weak but stock showing relative strength; 
  MACD is mixed but RSI is strong.
    SIGNIFICANT (approx 20%): Multiple red flags converging, OR one serious issue that materially threatens the thesis. Examples: elevated VIX combined with deteriorating market trend and late entry; or a
   major resistance level directly overhead with prior rejection history.
  
  DISTRIBUTION NOTE: Roughly 15% of BUY setups should score well across most dimensions, 60% mid-tier, 25% marginal. Do not default to mid-tier on every dimension — score STRONG when the data clearly 
  supports it, score WEAK when it clearly does not.
  
  Your reasoning must cite: (a) which dimension most influenced the decision, (b) the key risk specific to this setup, (c) why now is or is not a good entry point."""


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

    promptOld = f"""You are scoring a swing trade setup for an NSE-listed stock against a defined rubric. Be specific and falsifiable.

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

    system_msg = SystemMessage(
        content=[
            {
                "type": "text",
                "text": DECISION_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )

    human_msg = HumanMessage(
        content=f"""Ticker: {ticker} | Current price: Rs.{current_price}                    
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
    Block reasons: {risk.get('block_reasons') or 'None'}"""
    )
    try:
        result: DecisionSignal = chain.invoke([system_msg, human_msg])  # type: ignore[assignment]
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
