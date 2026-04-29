# Swing Trading Bot

A multi-agent AI system for swing trading NSE-listed smallcap and midcap stocks. Built with LangGraph, Claude (Anthropic), and FastAPI.

## Architecture

```
Universe (NSE Smallcap 250 + Midcap 150)
        ↓
   Math Screener (7 filters: RSI, SMA, ATR, volume, liquidity)
        ↓
   LangGraph Pipeline (per candidate)
        ↓
   Fetch Data Node    (yfinance — ticker history, ticker info, Nifty — single download)
        ↓  (fan-out — parallel)
        ├── Technical Agent    (Claude Haiku — 20 indicators + structured interpretation)
        ├── Sentiment Agent    (ReAct research agent → Claude Haiku scoring)
        │     └── Research Agent (create_agent + Tavily — sector-aware autonomous search)
        └── Market Context     (Nifty 50, sector index, 52w position — no LLM)
              ↓  (fan-in — all three must complete)
         Risk Agent            (deterministic — 3 trade gates + position sizing)
              ↓  (conditional routing)
        Decision Agent         (Claude Sonnet — 6-step framework, final BUY/HOLD/SELL)
              ↓  (conditional routing)
       Portfolio Simulator     (cash accounting, realised + unrealised P&L, DB persistence)
```

A `fetch_data_node` runs before the parallel fan-out, downloading all yfinance data once. The three parallel agents read from LangGraph state instead of making concurrent requests (prevents Yahoo Finance 401 rate-limit errors). Risk and decision run sequentially after all three complete.

## Tech Stack

- **Orchestration**: LangGraph (parallel fan-out, conditional routing, typed state)
- **LLM**: Anthropic Claude (Haiku for specialist agents, Sonnet for final decision)
- **Structured output**: LangChain `with_structured_output` + Pydantic (function calling)
- **Agentic search**: `langchain.agents.create_agent` ReAct loop with Tavily tool
- **News**: Tavily API (domain-filtered, advanced search depth)
- **Market data**: yfinance (NSE via Yahoo Finance)
- **Scheduling**: APScheduler (morning scan + 15-min position review, NSE holiday-aware)
- **Database**: SQLAlchemy 2.0 + SQLite (PostgreSQL-ready)
- **API / Dashboard**: FastAPI + Jinja2
- **Config**: Pydantic Settings
- **Logging**: structlog (timestamped)

## Project Structure

```
app/
├── agents/
│   ├── market_context.py   # Nifty/sector/52w data — no LLM
│   ├── technical.py        # 20 indicators + Claude Haiku
│   ├── sentiment.py        # ReAct research agent + Tavily + Claude Haiku scoring
│   ├── risk.py             # Deterministic position sizing + 3 trade gates
│   └── decision.py         # Claude Sonnet 6-step final decision
├── screener/
│   ├── universe.py         # Fetch NSE smallcap/midcap universe
│   └── filters.py          # 7 math filters + ranking score
├── utils/
│   ├── indicators.py       # RSI, MACD, BB, ATR, SMA, momentum
│   └── prompt_helpers.py   # Shared prompt formatting utilities
├── graph/
│   ├── state.py            # LangGraph TypedDict state
│   └── graph.py            # LangGraph pipeline
├── portfolio/
│   └── simulator.py        # Cash accounting, open/close trades, P&L snapshots
├── scheduler/
│   └── scheduler.py        # APScheduler — morning scan + 15-min position review
├── models/
│   └── models.py           # SQLAlchemy 2.0 ORM models
├── api/
│   └── routes.py           # FastAPI routes (in progress)
└── core/
    ├── config.py           # Pydantic settings
    ├── database.py         # DB engine + session
    └── logging.py          # structlog setup
main.py                     # Entry point — full scan loop
```

## Setup

```bash
# Clone and create virtual environment
git clone <repo>
cd swing-trade-bot
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your API keys

# Run a one-off scan
python main.py

# Run the scheduler (morning scan + position review)
python app/scheduler/scheduler.py
```

## API Keys Required

- **Anthropic API** — [console.anthropic.com](https://console.anthropic.com)
- **Tavily API** — [tavily.com](https://tavily.com)

## Strategy

Targets NSE smallcap and midcap stocks for swing trades (1-4 week hold).

**Screener filters:**
- Price above SMA50 and SMA200 (uptrend confirmation)
- RSI 55-70 (momentum without being overbought)
- ATR% > 1.5% (enough volatility to deliver returns in 1-4 weeks)
- Volume > 2x 20-day average (institutional conviction behind the move)
- Liquidity > ₹2 crore avg daily traded value
- No stocks that surged > 8% today (avoid chasing)

**Position sizing:**
- Max 4 open positions
- Max 25% of starting capital per position (minimum ₹5,000 position value)
- 7% stop loss, 18% take profit → 2.57x risk/reward ratio

**Decision pipeline:**
- Technical and sentiment agents run in parallel (LangGraph fan-out)
- Risk gates are deterministic and non-negotiable
- Decision agent (Sonnet) applies a 6-step framework: risk gate → signal alignment → entry timing → market context → conviction threshold → skepticism check
- Minimum 70% confidence to enter

**Scheduler:**
- Morning scan at 9:30 AM IST (Mon-Fri) — lets first 15 min volatility settle
- Position review every 15 minutes during market hours — auto-closes on stop-loss or take-profit hit
- NSE holiday-aware via official NSE API (`holiday-master` endpoint)

## Status

- [x] Screener — universe fetch + math filters
- [x] Market context agent
- [x] Technical analysis agent (20 indicators, structured output)
- [x] Sentiment agent — ReAct research agent + Haiku scoring
- [x] Risk agent — deterministic gates + position sizing
- [x] Decision agent — Claude Sonnet 6-step framework
- [x] Shared utilities — indicators, prompt helpers
- [x] LangGraph orchestrator — parallel fan-out, typed state, conditional routing, tested end-to-end
- [x] Portfolio simulator — realised + unrealised P&L, cash accounting, duplicate guard
- [x] `main.py` — end-to-end scan loop wiring screener → graph → simulator
- [x] Scheduler — morning scan + 15-min position review, NSE holiday-aware
- [ ] FastAPI dashboard — portfolio overview, open positions, trade history
