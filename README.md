# NSETradeAgents

Multi-agent AI system for swing trading NSE smallcap and midcap stocks. Targets 1-4 week holds with ATR-based stop losses and 18% take profit. Fully automated — morning discovery at 9:30 AM IST, 15-minute position monitoring during market hours.

---

## Architecture

```
NSE Universe (Smallcap 250 + Midcap 150 — 400 stocks)
        ↓
Regime Gate  (Nifty 50 vs SMA50 — skips all new entries if market in sustained downtrend)
        ↓
Math Screener  (7 filters: SMA trend, RSI 55-70, ATR >1.5%, volume >2×, liquidity >₹2Cr)
        ↓
fetch_data_node  (yfinance — single batch download before parallel fan-out)
        ↓
Fundamental Check  (deterministic — market cap, D/E ratio, ROE, no LLM)
        ↓  conditional: blocked if fails, else parallel fan-out
        ├── Technical Agent    Claude Haiku  — 20 indicators, structured output, temperature=0
        ├── Sentiment Agent    Claude Haiku  — ReAct loop → Tavily search → scoring, temperature=0
        │     └── Research Agent  create_agent + Tavily — sector-aware autonomous search
        └── Market Context     No LLM — Nifty 50 (day, 5d, SMA20 trend), sector index, 52w position, divergence
        ↓  fan-in
Risk Agent       Deterministic — 3 hard gates + ATR-based position sizing (max 3 positions × 25%)
        ↓  conditional routing
Decision Agent   Claude Sonnet — 5-dimension rubric → labels → computed confidence score, temperature=0
        ↓  conditional routing (≥65% confidence to execute)
Portfolio Simulator  SQLite — cash accounting, realised + unrealised P&L, snapshots every 15 min
```

**Single-process deployment:** FastAPI (async event loop) + APScheduler (BackgroundScheduler threads) run in one uvicorn process. The scheduler fires jobs in background threads; FastAPI serves the dashboard concurrently.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph — parallel fan-out, typed state, conditional routing |
| LLM | Anthropic Claude — Haiku (specialist agents), Sonnet (final decision), all at temperature=0 |
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
│   ├── fundamental.py      # Deterministic: market cap, D/E, ROE pre-filter
│   ├── market_context.py   # Nifty/sector/52w/SMA20 trend — no LLM
│   ├── technical.py        # 20 indicators + Claude Haiku
│   ├── sentiment.py        # ReAct research agent + Tavily + Claude Haiku
│   ├── risk.py             # Deterministic gates + ATR-based position sizing
│   └── decision.py         # Claude Sonnet 5-dimension rubric decision
├── screener/
│   ├── universe.py         # Fetch NSE CSV universe
│   └── filters.py          # Regime gate + 7 math filters + ranking score
├── graph/
│   ├── state.py            # LangGraph TypedDict state
│   └── graph.py            # LangGraph pipeline + confidence computation
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
│   ├── prompt_helpers.py   # Shared prompt formatting
│   └── scoring.py          # Dimension score map + confidence computation
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
caffeinate -i uvicorn app.api.routes:app --reload --reload-dir app
```
Open `http://localhost:8000`. The scheduler starts automatically — morning scan at 9:30 AM IST weekdays, position review every 15 minutes.

**Run tests:**
```bash
pytest tests/ -v
```

| File | Tests | Coverage |
|---|---|---|
| `test_risk.py` | 6 | All 3 hard gates, position sizing math, boundary conditions |
| `test_filters.py` | 6 | All 7 screener filters, ranking order, yfinance mocked |
| `test_fundamental.py` | 7 | Market cap, D/E, ROE, sector exemptions, flags vs blocks |
| `test_simulator.py` | 6 | Trade lifecycle, duplicate guard, cash check, P&L math |

---

**One-off scan** (testing only):
```bash
python main.py
```

---

## Trading Strategy

### Universe
NSE Nifty Smallcap 250 + Midcap 150. These indices are chosen deliberately — smallcap and midcap stocks offer higher volatility and momentum potential than large caps, making them better suited for 1-4 week swing trades. Large caps are excluded as they tend to move slowly and require more capital to generate meaningful returns.

---

### Stage 0 — Regime Gate

Before running any candidates through the pipeline, the screener checks whether Nifty 50 is trading above its 50-day SMA. If Nifty is below SMA50, all new entries are skipped for the day — existing positions continue to be monitored and closed normally.

This prevents deploying capital into sustained market downtrends. Backtesting showed that correction periods (Jan 2025: 14/14 stops, Jul 2025: 7/7 stops) were almost entirely avoided by this single gate, saving ~₹44,000 in losses over 3 years.

---

### Stage 1 — Math Screener (7 filters)

All 7 must pass. Candidates are then ranked by a composite score weighted 40% volume ratio, 35% 5-day momentum, 25% ATR%.

| Filter | Threshold | Rationale |
|---|---|---|
| Price > SMA50 > SMA200 | Must be true | Confirms the stock is in a structural uptrend at both medium and long-term timeframes. Avoids catching falling knives. |
| RSI (14) | 55 – 70 | The sweet spot for swing entry. Below 55 = weak momentum, not yet confirmed. Above 70 = overbought, late to the move, high reversion risk. |
| ATR% | > 1.5% | Average True Range as % of price. Ensures the stock has enough daily volatility to deliver meaningful returns in 1-4 weeks. Stocks with ATR% < 1.5% move too slowly. |
| Volume ratio | > 2× 20-day avg | Unusual volume signals institutional participation. A breakout or momentum move on thin volume is unreliable — operators can move small-caps on low volume. 2× filters for genuine conviction. |
| Volume shares | > 50,000 shares | Absolute floor to avoid illiquid stocks where even ₹25k positions move the price. |
| Avg daily traded value | > ₹2 crore | Liquidity floor. Ensures there's enough daily turnover to enter and exit without significant slippage. |
| Day change | < 8% | Avoids chasing stocks that have already made their move. Entering after an 8%+ day usually means buying the top of a spike. |

---

### Stage 2 — Fundamental Pre-Filter

Runs after data fetch, before expensive LLM agents. Rejects structurally broken companies to avoid wasting API credits on bad setups.

| Check | Threshold | Rationale |
|---|---|---|
| Market cap | > ₹500 crore | Below this on NSE you're in micro-cap territory: thin float, operator-driven price action, poor institutional coverage, high manipulation risk. |
| Debt/Equity | < 2.0× (non-financial) | Highly leveraged companies are vulnerable to rate hikes, credit tightening, and bad news. Skipped for banks/NBFCs where leverage is structural. |
| Return on Equity | > 0% | Companies with negative ROE are destroying shareholder value. A negative-ROE stock on a technical setup is often a dead-cat bounce. |
| Revenue growth | Flag if < -10% YoY | Soft flag only — not a hard block. Declining revenue is a risk factor the decision agent weighs, but a recovering business can still be a valid swing trade. |

---

### Stage 3 — Parallel Agent Analysis

Three agents run simultaneously after fundamental approval:

**Technical Agent (Claude Haiku, temperature=0)**
Interprets 20 computed indicators: RSI, MACD (line, signal, histogram trend), Bollinger Bands (position, width), SMA50/200, ATR%, volume ratio, 5-day and 20-day momentum, day change. Outputs BUY/HOLD/SELL signal with a strength score (0-100) and a 2-3 sentence reasoning. Temperature=0 ensures the same indicator readings produce the same interpretation on repeat runs.

**Sentiment Agent (Claude Haiku, temperature=0)**
Two-step process: (1) A ReAct research agent autonomously decides what to search — not just the company name, but sector-specific queries (e.g., for pharma: USFDA approvals, ANDA filings; for banking: NPA trends, RBI policy). Searches 10 curated Indian financial news domains plus Twitter and Reddit. (2) A separate scoring agent evaluates the findings on materiality, recency, and short-term relevance. Outputs BUY/HOLD/SELL signal with a score (-100 to +100). Research agent runs at default temperature for creative query generation; scoring runs at temperature=0.

**Market Context (no LLM)**
Deterministic computation: Nifty 50 day, 5-day, and SMA20 trend position (above/below SMA20 relative to SMA50 — early correction detection), sector index performance, stock's 52-week position (% from high/low), and a divergence note (stock rising while sector falls = relative strength, the most bullish signal).

---

### Stage 4 — Risk Gates (Deterministic)

Three non-negotiable hard blocks applied before the decision agent:

1. **Max positions** — blocks if 3 positions already open
2. **Dual SELL signal** — blocks if both technical AND sentiment signal SELL simultaneously
3. **Position affordability** — blocks if stock price × minimum lot exceeds available position budget, or if position would be below ₹5,000 (too small to be meaningful)

---

### Stage 5 — Decision Agent (Claude Sonnet, temperature=0)

The decision agent scores the setup across 5 independent dimensions and outputs a categorical label for each. Confidence is computed deterministically in Python from these labels — the model never outputs a number directly, eliminating anchoring bias.

**Pre-scoring:** Before evaluating dimensions, the model writes:
- `kill_case` — the single most specific falsifiable reason this trade fails
- `strong_setup_conditions` — what would make this score well across most dimensions
- `weak_setup_conditions` — what would make this score poorly

**Dimensions and point values:**

| Dimension | STRONG/IDEAL/FAVORABLE | MODERATE/ACCEPTABLE/NEUTRAL | WEAK/POOR/UNFAVORABLE/CONFLICTED |
|---|---|---|---|
| Signal alignment | 30 | 18 | 0 |
| Entry timing | 25 | 15 | 0 |
| Momentum quality | 20 | 12 | 0 |
| Risk/reward view | 15 | 8 | 0 |
| Setup concern | 10 (NONE) | 5 (MINOR) | 0 (SIGNIFICANT) |

**Market context adjustments** (applied in code after LLM output):
- Bearish Nifty (>1% down): −15 points
- Bearish sector (>0.5% down): −10 points
- Relative strength vs sector: +10 points

**Confidence threshold:** ≥65 to execute. Max possible score is 100.

---

### Position Sizing & Risk Management

**Entry:** ₹1,00,000 starting capital. Max 3 positions × 25% = ₹25,000 per position. The 3-position cap keeps 25% capital in reserve, reducing worst-case simultaneous stop-out from 28% to 21% of total capital.

**Stop loss:** ATR-based — `2.5 × ATR%` of entry price, with a 5% floor and 10% cap. Calibrates the stop to each stock's actual volatility rather than applying a fixed rule. A stock with ATR% 2.0% gets a ~5% stop (tight, low-volatility); ATR% 3.5% gets an 8.75% stop (room to breathe).

**Take profit:** Fixed 18% above entry price.

**Holding period:** 1-4 weeks. The 15-minute position monitor auto-closes positions when stop or target is hit intraday. Positions held beyond 21 days are closed at market price — the swing trade thesis is no longer valid after 3 weeks.

**Known limitations:**
- Regime gate uses SMA50 (slow-moving) — fast 3-5 week corrections that don't push Nifty below SMA50 are not fully filtered. SMA20 context is passed to the decision agent but is not a hard gate.
- No sector concentration limit — all 3 positions could theoretically be in the same sector. Sector exposure capping is a planned improvement.
- Sentiment backtesting is not reproducible — Tavily fetches live news, so historical sentiment cannot be replayed. Backtest results reflect technical and structural signals only.

---

## Technical Highlights

**yfinance 401 fix** — Yahoo Finance rate-limits concurrent requests. `fetch_data_node` downloads all ticker data once before the parallel fan-out. The three parallel agents read from LangGraph state instead of making independent HTTP calls.

**Determinism by design** — technical, sentiment scoring, and decision agents all run at `temperature=0`. The research agent (creative query generation) runs at default temperature. Consistent inputs produce consistent outputs across runs, preventing borderline decisions from flipping between runs of the same day's data.

**Anchoring-free confidence scoring** — the decision agent outputs categorical labels (STRONG/ACCEPTABLE/CONFLICTED etc.) rather than a single integer. A deterministic scoring map in `utils/scoring.py` converts labels to points and applies market context adjustments. This prevents LLMs from anchoring to minimum-passing values (a known failure mode of single-number structured outputs).

**Single-process architecture** — `BackgroundScheduler` (APScheduler) runs trading jobs in threads alongside FastAPI's async event loop in one uvicorn process. No separate scheduler process or message broker needed.

**Real-time log streaming** — structlog writes every log entry to an in-memory `deque(maxlen=500)`. The `/logs` SSE endpoint polls the deque every 500ms and streams new entries to the browser via `EventSource`. No WebSocket or Redis needed.

**Mark-to-market P&L** — the 15-minute position review fetches live prices via yfinance intraday (5-min bars), updates `current_price` on each open `Trade` row, and saves a `PortfolioSnapshot` with unrealised P&L. The dashboard reads from DB — no live price fetch on page load.

**NSE holiday awareness** — `_load_nse_holidays(year)` fetches the official NSE holiday list from `nseindia.com/api/holiday-master?type=trading` on first call and caches via `@lru_cache`. Position reviews skip cleanly on market holidays.

**SQLAlchemy 2.0** — all models use `Mapped[T]` annotations and `mapped_column()`. Pylance resolves column types correctly without stubs or `# type: ignore`.
