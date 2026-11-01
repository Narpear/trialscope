import os
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
    max_trials_cap: int = Field(default=10000, ge=1, le=10000, validation_alias="MAX_TRIALS_CAP")
    request_timeout_seconds: float = 30.0
    # ClinicalTrials.gov allows roughly 50 requests/minute per IP after a short burst.
    clinicaltrials_requests_per_second: float = 0.8
    clinicaltrials_request_burst: int = 8
    exact_count_query_budget: int = Field(
        default=40, ge=0, validation_alias="EXACT_COUNT_QUERY_BUDGET"
    )
    rate_limit_requests: int = 12
    rate_limit_window_seconds: int = 60
    # Number of reverse proxies in front of the app. The client IP is read from the
    # X-Forwarded-For entry appended by the outermost trusted proxy; earlier entries are
    # client-controlled. Railway runs one edge proxy, so it defaults to 1 there.
    trusted_proxy_hops: int = Field(
        default_factory=lambda: 1 if os.getenv("RAILWAY_ENVIRONMENT") else 0,
        ge=0,
        validation_alias="TRUSTED_PROXY_HOPS",
    )
    network_top_n: int = 30
    network_min_edge_weight: int = 2
    network_excluded_interventions: list[str] = Field(
        default_factory=lambda: ["placebo", "standard of care", "saline", "best supportive care"],
        validation_alias="NETWORK_EXCLUDED_INTERVENTIONS",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
