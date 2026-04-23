# Swing Trading Bot

A multi-agent AI system for swing trading NSE-listed smallcap and midcap stocks. Built with LangGraph, Claude (Anthropic), and FastAPI.

## Architecture

```
Universe (NSE Smallcap 250 + Midcap 150)
        ↓
   Math Screener (7 filters: RSI, SMA, ATR, volume, liquidity)
        ↓
   LangGraph Pipeline (per candidate)
        ├── Technical Agent (Claude Haiku — indicators + pattern interpretation)
        ├── Sentiment Agent (Tavily news + Claude Haiku scoring)
        └── Market Context (Nifty 50, sector index, 52w position — no LLM)
              ↓
         Risk Agent (deterministic — position sizing, trade gates)
              ↓
        Decision Agent (Claude Sonnet — final BUY/HOLD/SELL)
              ↓
       Portfolio Simulator (cash, positions, P&L)
```

Technical and sentiment agents run in **parallel** via LangGraph fan-out. Risk and decision run sequentially after both complete.

## Tech Stack

- **Orchestration**: LangGraph
- **LLM**: Anthropic Claude (Haiku for analysis agents, Sonnet for final decision)
- **News**: Tavily API
- **Market data**: yfinance (NSE via Yahoo Finance)
- **Database**: SQLAlchemy + SQLite (PostgreSQL-ready)
- **API / Dashboard**: FastAPI + Jinja2
- **Config**: Pydantic Settings
- **Logging**: structlog

## Project Structure

```
app/
├── agents/
│   ├── market_context.py   # Nifty/sector/52w data — no LLM
│   ├── technical.py        # Indicators + Claude Haiku
│   ├── sentiment.py        # Tavily news + Claude Haiku
│   ├── risk.py             # Deterministic position sizing
│   └── decision.py         # Claude Sonnet final decision
├── screener/
│   ├── universe.py         # Fetch NSE smallcap/midcap universe
│   └── filters.py          # Math filters
├── utils/
│   └── indicators.py       # Shared technical indicator computations
├── graph/
│   ├── state.py            # LangGraph state definition
│   └── graph.py            # LangGraph pipeline
├── portfolio/
│   └── simulator.py        # Cash, positions, P&L tracking
├── models/
│   └── models.py           # SQLAlchemy ORM models
├── api/
│   └── routes.py           # FastAPI routes
└── core/
    ├── config.py           # Pydantic settings
    ├── database.py         # DB engine + session
    └── logging.py          # structlog setup
```

## Setup

```bash
# Clone and create virtual environment
git clone <repo>
cd swingTradingbot
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your API keys

# Run
python main.py
```

## API Keys Required

- **Anthropic API** — [console.anthropic.com](https://console.anthropic.com)
- **Tavily API** — [tavily.com](https://tavily.com)

## Strategy

Targets NSE smallcap and midcap stocks for swing trades (1-4 week hold).

**Screener filters:**
- Price above SMA50 and SMA200 (uptrend)
- RSI 55-70 (momentum without being overbought)
- ATR% > 1.5% (enough volatility to deliver returns)
- Volume > 2x 20-day average (conviction behind the move)
- Liquidity > ₹2 crore avg daily traded value

**Position sizing:**
- Max 4 open positions
- Max 25% portfolio per position
- 7% stop loss, 18% take profit

## Status

- [x] Screener — universe fetch + math filters
- [x] Market context agent
- [x] Technical analysis agent
- [x] Sentiment analysis agent
- [ ] Risk agent
- [ ] Decision agent
- [ ] LangGraph orchestrator
- [ ] Portfolio simulator
- [ ] FastAPI dashboard
