# Swing Trade Bot

Multi-agent AI system for swing trading NSE smallcap and midcap stocks. Targets 1-4 week holds with a 2.57× risk/reward ratio (7% stop, 18% target).

---

## Architecture

```
NSE Universe (Smallcap 250 + Midcap 150 — 400 stocks)
        ↓
Math Screener  (7 filters: SMA trend, RSI 55-70, ATR >1.5%, volume >2×, liquidity >₹2Cr)
        ↓
fetch_data_node  (yfinance — single batch download before parallel fan-out)
        ↓  parallel fan-out
        ├── Technical Agent    Claude Haiku  — 20 indicators, structured output
        ├── Sentiment Agent    Claude Haiku  — ReAct loop → Tavily search → scoring
        │     └── Research Agent  create_agent + Tavily — sector-aware autonomous search
        └── Market Context     No LLM — Nifty 50, sector index, 52w position, divergence
        ↓  fan-in
Risk Agent       Deterministic — 3 hard gates + position sizing (25% of capital)
        ↓  conditional routing
Decision Agent   Claude Sonnet — 6-step framework → BUY / HOLD / SELL + confidence score
        ↓  conditional routing (≥70% confidence to execute)
Portfolio Simulator  SQLite — cash accounting, realised + unrealised P&L, snapshots
```

**Single-process deployment:** FastAPI (async event loop) + APScheduler (BackgroundScheduler threads) run in one uvicorn process. The scheduler fires jobs in background threads; FastAPI serves the dashboard concurrently.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph — parallel fan-out, typed state, conditional routing |
| LLM | Anthropic Claude — Haiku (specialist agents), Sonnet (final decision) |
| Structured output | LangChain `with_structured_output` + Pydantic |
| Agentic search | `langchain.agents.create_agent` ReAct loop + Tavily |
| Market data | yfinance (NSE via Yahoo Finance) |
| Scheduling | APScheduler `BackgroundScheduler` — NSE holiday-aware via official NSE API |
| Database | SQLAlchemy 2.0 (`Mapped` annotations) + SQLite |
| API | FastAPI + Jinja2 |
| Frontend | Tailwind CSS + Chart.js + Alpine.js (all via CDN) |
| Config | Pydantic Settings (`.env`) |
| Logging | structlog — timestamped console + in-memory deque → SSE stream |

---

## Project Structure

```
app/
├── agents/
│   ├── market_context.py   # Nifty/sector/52w — no LLM
│   ├── technical.py        # 20 indicators + Claude Haiku
│   ├── sentiment.py        # ReAct research agent + Tavily + Claude Haiku
│   ├── risk.py             # Deterministic gates + position sizing
│   └── decision.py         # Claude Sonnet 6-step decision
├── screener/
│   ├── universe.py         # Fetch NSE CSV universe
│   └── filters.py          # 7 math filters + ranking score
├── graph/
│   ├── state.py            # LangGraph TypedDict state
│   └── graph.py            # LangGraph pipeline
├── portfolio/
│   └── simulator.py        # Cash, trades, P&L snapshots
├── scheduler/
│   └── scheduler.py        # APScheduler — morning scan + 15-min position review
├── api/
│   └── routes.py           # FastAPI app + all routes
├── templates/              # Jinja2 HTML templates
│   ├── base.html
│   ├── overview.html       # Portfolio value + P&L chart
│   ├── positions.html      # Open trades, live prices, progress bar
│   ├── history.html        # Closed trades + win rate stats
│   └── logs.html           # Real-time SSE log stream
├── utils/
│   ├── indicators.py       # RSI, MACD, BB, ATR, SMA, momentum
│   └── prompt_helpers.py   # Shared prompt formatting
└── core/
    ├── config.py           # Pydantic settings
    ├── database.py         # SQLAlchemy engine + session
    └── logging.py          # structlog + in-memory log buffer
main.py                     # One-off scan entry point
```

---

## Setup

**Requirements:** Python 3.10+, Anthropic API key, Tavily API key.

```bash
git clone <repo>
cd swing-trade-bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add ANTHROPIC_API_KEY and TAVILY_API_KEY
```

**Run the full app** (dashboard + scheduler):
```bash
uvicorn app.api.routes:app --reload
```
Open `http://localhost:8000`. The scheduler starts automatically — morning scan at 9:30 AM IST weekdays, position review every 15 minutes.

**One-off scan** (no dashboard):
```bash
python main.py
```

---

## Strategy

**Universe:** NSE Nifty Smallcap 250 + Midcap 150

**Screener filters (all must pass):**
1. Price > SMA50 > SMA200 — confirmed uptrend
2. RSI 55-70 — momentum without being overbought
3. ATR% > 1.5% — enough daily range to deliver swing returns
4. Volume > 2× 20-day average — institutional conviction behind the move
5. Today's volume > 50,000 shares — minimum liquidity floor
6. Avg daily traded value > ₹2 crore — prevents illiquid traps
7. Day change < 8% — avoids chasing stocks that already ran

**Position sizing:** ₹1,00,000 starting capital → max 4 positions × 25% = ₹25,000 each. Stop loss 7%, take profit 18% → 2.57× risk/reward.

**Decision framework (Claude Sonnet):**
1. Risk gate — non-negotiable hard block
2. Signal alignment — technical vs sentiment agreement
3. Entry timing — extended moves, round-number resistance, volume confirmation
4. Market context adjustment — bearish Nifty/sector reduces confidence
5. Conviction threshold — minimum 70% confidence to execute
6. Skepticism check — if everything looks perfect, question it

---

## Technical Highlights

**yfinance 401 fix** — Yahoo Finance rate-limits concurrent requests. `fetch_data_node` downloads all ticker data once before the parallel fan-out. The three parallel agents read from LangGraph state instead of making independent HTTP calls.

**Single-process architecture** — `BackgroundScheduler` (APScheduler) runs trading jobs in threads alongside FastAPI's async event loop in one uvicorn process. No separate scheduler process or message broker needed.

**Real-time log streaming** — structlog writes every log entry to an in-memory `deque(maxlen=500)`. The `/logs` SSE endpoint polls the deque every 500ms and streams new entries to the browser via `EventSource`. No WebSocket or Redis needed.

**Mark-to-market P&L** — the 15-minute position review fetches live prices via yfinance intraday (5-min bars), updates `current_price` on each open `Trade` row, and saves a `PortfolioSnapshot` with unrealised P&L. The dashboard reads from DB — no live price fetch on page load.

**NSE holiday awareness** — `_load_nse_holidays(year)` fetches the official NSE holiday list from `nseindia.com/api/holiday-master?type=trading` on first call and caches via `@lru_cache`. Position reviews skip cleanly on market holidays.

**SQLAlchemy 2.0** — all models use `Mapped[T]` annotations and `mapped_column()`. Pylance resolves column types correctly without stubs or `# type: ignore`.
