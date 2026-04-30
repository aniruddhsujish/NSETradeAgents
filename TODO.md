# TODO — Swing Bot

---

## V1 — Complete

- [x] Screener — NSE universe fetch + 7 math filters (SMA trend, RSI 55-70, ATR, volume, liquidity)
- [x] Config — pydantic-settings, type-safe, environment-driven
- [x] Database — SQLAlchemy 2.0 (`Mapped` annotations), SQLite, PostgreSQL-ready
- [x] Logging — structlog with timestamps + in-memory circular buffer (SSE streaming to dashboard)
- [x] Market context agent — Nifty day/5d change, sector index, 52w position, divergence (no LLM)
- [x] Technical agent — 20 indicators + Claude Haiku structured interpretation, temperature=0
- [x] Sentiment agent — ReAct research agent (Tavily) + Claude Haiku scoring at temperature=0; research agent at default temperature for creative query generation
- [x] Fundamental agent — deterministic pre-filter: market cap (>₹500Cr), D/E ratio, ROE, revenue growth flag; runs before LLM pipeline to save API credits
- [x] Risk agent — deterministic 3 trade gates + position sizing (25% of starting capital per position)
- [x] Decision agent — Claude Sonnet 6-step framework at temperature=0, BUY/HOLD/SELL with confidence score
- [x] LangGraph orchestrator — parallel fan-out, typed state, conditional routing, tested end-to-end
- [x] yfinance 401 fix — `fetch_data_node` pre-fetches all data once before parallel agents run
- [x] Portfolio simulator — cash accounting, open/close trades, realised + unrealised P&L
- [x] `main.py` — one-off scan: universe → screener → graph → simulator → snapshot
- [x] Scheduler — single-process (BackgroundScheduler + FastAPI lifespan); morning scan 9:30 AM IST Mon-Fri; 15-min position review; NSE holiday-aware via official NSE API
- [x] FastAPI dashboard — overview (P&L chart), positions (live prices + progress bar), history (win rate), logs (SSE real-time stream)
- [x] Determinism — temperature=0 on technical, sentiment scoring, and decision agents; min_confidence raised to 75%

---

## V2 — Agents

- [ ] **Deferred reflection system** — after each trade closes, fetch actual return, run LLM reflection comparing entry thesis to outcome, persist lesson to a per-ticker memory file; inject last 5 same-ticker lessons + 3 cross-ticker lessons into future decision agent context. Inspired by TradingAgents (56.5k ⭐). Structured path to prompt fine-tuning from real outcomes.
- [ ] **Bull/Bear debate architecture** — replace single decision agent with Bull Researcher + Bear Researcher arguing opposing cases, then a judge agent synthesising. Reduces groupthink, more robust than one-shot decision. Currently decision agent has a built-in skepticism step but no adversarial counterweight.
- [ ] Position review agent — LLM re-checks open position thesis daily, flags early exit signals
- [ ] Macro agent — dedicated Nifty/VIX/FII flow check before any trade (currently embedded in risk agent)
- [ ] Portfolio optimisation agent — rank multiple BUY signals by conviction when cash is limited
- [ ] Earnings calendar agent — tighten stops / block entries 2 days before results

## V2 — Risk & Sizing

- [ ] ATR-based stop loss — `price - 2×ATR` replaces fixed 7%; adapts to each stock's volatility; prevents normal daily range from triggering stop-outs on volatile stocks
- [ ] Cash buffer — enforce 20-30% uninvested at all times; currently 4×25% = 100% deployed with no buffer for adverse market events
- [ ] Sector exposure limit — block new trade if >40% of portfolio already in same sector
- [ ] Time-based exit — close if no meaningful move after N days
- [ ] Trailing stop — activate once position is up X%, ratchet stop to lock in gains

## V2 — Analysis

- [ ] Pass earnings date to decision agent — avoid entering within 2 days of results
- [ ] Fine-tune prompts with real trade outcomes after 3-6 months of data
- [ ] Add social media domains to Tavily search (twitter.com, reddit.com already added to include_domains)

## V2 — Screener

- [ ] Store sector from NSE CSV — use for sector exposure tracking and macro filtering
- [ ] Fundamental pre-filter — add P/E, revenue growth to fundamental agent (currently only market cap, D/E, ROE)
- [ ] Minimum market cap filter in screener (currently applied in fundamental agent post-fetch)

## V2 — Dashboard

- [ ] Sector exposure bar chart
- [ ] Unrealised P&L over time chart (data already captured in snapshots)
- [ ] EOD portfolio snapshot chart

## V2 — Infrastructure

- [ ] Telegram / email alerts on trade open/close
- [ ] Backtesting module — screener + deterministic technical rules on historical OHLCV (LLM layer not backtestable)
- [ ] Kite API integration — live order placement (`simulation_mode=False`)
- [ ] Swap SQLite → PostgreSQL for production
- [ ] Structured JSON logging (swap `ConsoleRenderer` → `JSONRenderer`)
