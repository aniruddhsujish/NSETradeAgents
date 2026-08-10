import structlog
import yfinance as yf
from langgraph.graph import StateGraph, START, END
from app.graph.state import TradingState
from app.agents.fundamental import run_fundamental_check
from app.agents.market_context import fetch_market_context
from app.agents.technical import run_technical_analysis
from app.agents.sentiment import run_sentiment_analysis
from app.agents.risk import run_risk_check
from app.core.config import settings
from app.utils.scoring import compute_rules_confidence
from app.utils.market_data import safe_yf_download

logger = structlog.get_logger()


def fetch_data_node(state: TradingState) -> dict:
    """Download all yfinance data once before parallel agents run."""
    ticker = state["ticker"]
    logger.info("fetch_data_start", ticker=ticker)

    # 12mo history covers both technical analysis and 52-week position needs
    ticker_df = safe_yf_download(ticker, period="12mo")

    try:
        ticker_info = yf.Ticker(ticker).info
    except Exception as e:
        logger.warning("ticker_info_failed", ticker=ticker, error=str(e))
        ticker_info = {}

    try:
        nifty_df = safe_yf_download("^NSEI", period="60d")
    except Exception as e:
        logger.warning("nifty_fetch_failed", error=str(e))
        nifty_df = None

    try:
        vix_df = safe_yf_download("^INDIAVIX", period="30d")
    except Exception as e:
        logger.warning("vix_fetch_failed", error=str(e))
        vix_df = None

    logger.info(
        "fetch_data_done",
        ticker=ticker,
        rows=len(ticker_df) if ticker_df is not None else 0,
        vix_rows=len(vix_df) if vix_df is not None else 0,
    )
    return {
        "ticker_df": ticker_df,
        "ticker_info": ticker_info,
        "nifty_df": nifty_df,
        "vix_df": vix_df,
    }


def fundamental_node(state: TradingState) -> dict:
    result = run_fundamental_check(state["ticker"], state.get("ticker_info"))
    return {"fundamental_result": result}


def market_context_node(state: TradingState) -> dict:
    ctx = fetch_market_context(
        state["ticker"],
        ticker_df=state.get("ticker_df"),
        ticker_info=state.get("ticker_info"),
        nifty_df=state.get("nifty_df"),
        vix_df=state.get("vix_df"),
    )
    return {"market_context": ctx}


def technical_node(state: TradingState) -> dict:
    signals = run_technical_analysis(
        state["ticker"],
        ticker_df=state.get("ticker_df"),
    )
    return {"technical_signals": signals}


def sentiment_node(state: TradingState) -> dict:
    ctx = state.get("market_context") or {}
    data = run_sentiment_analysis(
        state["ticker"],
        sector=ctx.get("sector", "Unknown"),
        ticker_info=state.get("ticker_info"),
    )
    return {"sentiment_data": data}


def risk_node(state: TradingState) -> dict:
    tech = state.get("technical_signals") or {}
    sent = state.get("sentiment_data") or {}
    ctx = state.get("market_context") or {}
    atr_pct = (tech.get("indicators") or {}).get("atr_pct")
    result = run_risk_check(
        ticker=state["ticker"],
        current_price=state["current_price"],
        portfolio_cash=state["portfolio_cash"],
        open_positions=state["open_positions"],
        technical_signal=tech.get("signal", "HOLD"),
        sentiment_signal=sent.get("signal", "HOLD"),
        atr_pct=atr_pct,
        ticker_sector=ctx.get("sector", "Unknown"),
        open_position_sectors=state.get("open_position_sectors") or [],
    )
    return {"risk_result": result}


def rules_gate_node(state: TradingState) -> dict:
    result = compute_rules_confidence(
        technical=state.get("technical_signals") or {},
        risk=state.get("risk_result") or {},
        market_context=state.get("market_context"),
    )
    score = result.pop("score")
    logger.info("rules_gate", ticker=state["ticker"], rules_score=score, **result)
    return {"rules_score": score, "rules_bands": result}


def blocked_node(state: TradingState) -> dict:
    fundamental = state.get("fundamental_result") or {}
    risk = state.get("risk_result") or {}
    score = state.get("rules_score")
    bands = state.get("rules_bands") or {}
    reasons = (
        fundamental.get("block_reasons")
        or risk.get("block_reasons")
        or [
            f"Rules score {score} < {settings.rules_confidence_threshold:g} "
            + ", ".join(f"{k}={v}" for k, v in bands.items())
        ]
    )
    logger.info("trade_blocked", ticker=state["ticker"], reasons=reasons)
    return {
        "trade_result": {"action": "BLOCKED", "executed": False, "reasons": reasons}
    }


def fetch_price_node(state: TradingState) -> dict:
    """Extract current price from technical indicators after analysis"""
    tech = state.get("technical_signals") or {}
    ind = tech.get("indicators") or {}
    price = ind.get("current_price", 0.0)
    return {"current_price": price}


def execute_node(state: TradingState) -> dict:
    risk = state.get("risk_result") or {}
    market_ctx = state.get("market_context") or {}
    ticker = state["ticker"]
    tech = state.get("technical_signals") or {}
    atr_pct = (tech.get("indicators") or {}).get("atr_pct")
    score = state.get("rules_score")

    logger.info(
        "trade_execute",
        ticker=ticker,
        action="BUY",
        quantity=risk.get("quantity"),
        price=state["current_price"],
        rules_score=score,
        simulation=settings.simulation_mode,
    )

    if not settings.simulation_mode:
        # Phase 2: Kite API order placement goes here
        raise NotImplementedError("Live trading via Kite API not yet implemented")

    return {
        "trade_result": {
            "action": "BUY",
            "executed": True,
            "ticker": ticker,
            "sector": market_ctx.get("sector", "Unknown"),
            "price": state["current_price"],
            "quantity": risk.get("quantity"),
            "position_size_inr": risk.get("position_size_inr"),
            "stop_loss": risk.get("stop_loss"),
            "take_profit": risk.get("take_profit"),
            "atr_pct": atr_pct,
            "confidence": score,
            "reasoning": (tech.get("summary") or ""),
        }
    }


def route_after_fundamental(state: TradingState) -> list[str]:
    result = state.get("fundamental_result") or {}
    if not result.get("approved", True):
        return ["blocked"]
    return ["market_context", "technical", "sentiment"]


def route_after_risk(state: TradingState) -> str:
    """If risk blocked, skip scoring entirely"""
    risk = state.get("risk_result") or {}
    if not risk.get("approved"):
        return "blocked"
    return "rules_gate"


def route_after_rules_gate(state: TradingState) -> str:
    if (state.get("rules_score") or 0) < settings.rules_confidence_threshold:
        return "blocked"
    return "execute"


def build_graph():
    graph = StateGraph(TradingState)

    # Register nodes
    graph.add_node("fetch_data", fetch_data_node)
    graph.add_node("fundamental", fundamental_node)
    graph.add_node("market_context", market_context_node)
    graph.add_node("technical", technical_node)
    graph.add_node("sentiment", sentiment_node)
    graph.add_node("fetch_price", fetch_price_node)
    graph.add_node("risk", risk_node)
    graph.add_node("rules_gate", rules_gate_node)
    graph.add_node("blocked", blocked_node)
    graph.add_node("execute", execute_node)

    # Fetch all market data once
    graph.add_edge(START, "fetch_data")

    # Fan-out: fundamental conditionally fans out or blocks
    graph.add_edge("fetch_data", "fundamental")
    graph.add_conditional_edges("fundamental", route_after_fundamental)

    # Fan-in: all three -> fetch_price
    graph.add_edge("market_context", "fetch_price")
    graph.add_edge("technical", "fetch_price")
    graph.add_edge("sentiment", "fetch_price")

    # Sequential from here
    graph.add_edge("fetch_price", "risk")

    graph.add_conditional_edges(
        "risk", route_after_risk, {"blocked": "blocked", "rules_gate": "rules_gate"}
    )

    graph.add_conditional_edges(
        "rules_gate",
        route_after_rules_gate,
        {"blocked": "blocked", "execute": "execute"},
    )

    graph.add_edge("blocked", END)
    graph.add_edge("execute", END)

    return graph.compile()


trading_graph = build_graph()


def analyze_ticker(
    ticker: str,
    portfolio_cash: float,
    open_positions: int,
    open_position_sectors: list[str],
) -> dict:
    """Entry point - run the full pipeline for a single ticker"""
    initial_state: TradingState = {
        "ticker": ticker,
        "portfolio_cash": portfolio_cash,
        "open_positions": open_positions,
        "ticker_df": None,
        "ticker_info": None,
        "nifty_df": None,
        "vix_df": None,
        "current_price": 0.0,
        "market_context": None,
        "fundamental_result": None,
        "technical_signals": None,
        "sentiment_data": None,
        "risk_result": None,
        "trade_result": None,
        "open_position_sectors": open_position_sectors,
        "rules_score": None,
        "rules_bands": None,
    }
    return trading_graph.invoke(initial_state)
