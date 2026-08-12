import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    ai_api_key: str = ""
    ai_base_url: str = "https://api.anthropic.com"
    ai_provider: str = "claude"  # one of: glm | gemini | codex | claude — selects request protocol
    ai_model: str = "claude-sonnet-5"
    ai_timeout_seconds: int = 60
    ai_max_retries: int = 2
    ai_min_confidence: float = 0.80

    database_url: str = "sqlite:///data/bestai.db"
    sources_file: str = "config/sources.json"
    model_aliases_file: str = "config/model_aliases.json"
    payment_methods_file: str = "config/payment_methods.json"
    official_prices_file: str = "config/official_prices.json"
    extraction_prompt_file: str = "config/extraction_prompt.txt"
    fx_rates_file: str = "config/fx_rates.json"

    frontend_json_path: str = "public/data/providers.json"
    review_csv_path: str = "exports/review_prices.csv"
    snapshots_dir: str = "snapshots"
    log_dir: str = "logs"

    http_timeout_seconds: int = 15
    http_max_retries: int = 3
    playwright_timeout_seconds: int = 30
    rdap_timeout_seconds: int = 10

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        directories = [
            Path("data"),
            Path(self.snapshots_dir),
            Path(self.log_dir),
            Path(self.review_csv_path).parent,
            Path(self.frontend_json_path).parent,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
