from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """All tunable parameters, with the values the backtest was measured on.

    Any field can be overridden from .env. Defaults here are the source of
    truth — .env.example deliberately does not repeat them.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # LLM — unused while the pipeline is fully deterministic; the veto agent
    # will need these again. Optional so the app starts without them.
    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_model_smart: str = "claude-sonnet-4-6"
    llm_model_veto: str = "claude-opus-5"

    # Portfolio
    starting_capital: float = 200000
    simulation_mode: bool = True

    # Database
    database_url: str = "sqlite:///swing_bot.db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Risk
    max_positions: int = 5
    max_position_pct: float = 0.20
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.18
    max_hold_days: int = 21
    rules_confidence_threshold: float = 65

    # Screener
    min_volume_ratio: float = 2.0
    min_volume_shares: int = 50000
    min_avg_daily_value: float = 2_00_00_000
    max_day_change_pct: float = 8.0
    min_price: float = 100.0
    min_atr_pct: float = 1.5
    rsi_min: float = 55.0
    rsi_max: float = 70.0
    regime_sma_period: int = 50

    # Fundamental filters
    min_market_cap: float = 5_00_00_00_000  # ₹500 Crore
    max_debt_to_equity: float = 200.0  # yfinance returns as %, 200 = 2.0x
    min_roe: float = 0.05
    max_revenue_decline_pct: float = -0.10
    max_pe_ratio: float = 100.0

    # Scoring adjustments
    vix_high_fear_level: float = 22.0
    vix_medium_fear_level: float = 18.0
    vix_high_fear_penalty: int = 20
    vix_medium_fear_penalty: int = 10
    nifty_20d_decline_threshold: float = -3.0
    nifty_10d_decline_threshold: float = -2.0
    round_number_levels: list[float] = Field(default=[500.0, 1000.0, 2000.0, 5000.0])
    resistance_proximity_pct: float = 0.02

    # Trailing stop
    trail_activation_pct: float = 0.12
    trail_min_pct: float = 0.05  # floor for ATR-based trail
    trail_max_pct: float = 0.08  # cap for ATR-based trail
    max_hybrid_positions: int = 3

    # Veto config
    veto_mode: str = "shadow"  # off | shadow | acting


settings: Settings = Settings()
