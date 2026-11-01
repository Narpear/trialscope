from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.4-mini", validation_alias="OPENAI_MODEL")
    clinicaltrials_base_url: str = Field(
        default="https://clinicaltrials.gov/api/v2", validation_alias="CLINICALTRIALS_BASE_URL"
    )
    max_trials_cap: int = Field(default=5000, ge=1, le=5000, validation_alias="MAX_TRIALS_CAP")
    request_timeout_seconds: float = 20.0
    rate_limit_requests: int = 12
    rate_limit_window_seconds: int = 60
    network_top_n: int = 30
    network_min_edge_weight: int = 2
    network_excluded_interventions: list[str] = Field(
        default_factory=lambda: ["placebo", "standard of care", "saline", "best supportive care"],
        validation_alias="NETWORK_EXCLUDED_INTERVENTIONS",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
