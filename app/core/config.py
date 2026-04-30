from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # LLM
    anthropic_api_key: str
    tavily_api_key: str
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_model_smart: str = "claude-sonnet-4-6"

    # Portfolio
    starting_capital: float = 100000
    simulation_mode: bool = True

    # Database
    database_url: str = "sqlite:///swing_bot.db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Risk
    max_positions: int = 4
    max_position_pct: float = 0.25
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.18
    min_confidence: float = 0.75

    # Screener
    min_volume_ratio: float = 2.0
    min_volume_shares: int = 50000
    min_avg_daily_value: float = 2_00_00_000
    max_day_change_pct: float = 8.0
    min_price: float = 100.0
    min_atr_pct: float = 1.5
    rsi_min: float = 55.0
    rsi_max: float = 70.0


settings: Settings = Settings()
