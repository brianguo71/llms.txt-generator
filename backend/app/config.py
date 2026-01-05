"""Application configuration via environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "llms.txt Generator"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llmstxt"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24 * 7  # 1 week
    algorithm: str = "HS256"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # Crawler settings
    max_pages_per_crawl: int = 100  # Maximum pages to crawl per site
    crawler_backend: Literal["firecrawl", "scrapy"] = "firecrawl"
    
    # Firecrawl API
    firecrawl_api_key: str | None = None
    firecrawl_wait_for_ms: int = 3000  # Wait time in ms for JS rendering (essential for SPAs)

    # Change detection (full rescrape)
    default_check_interval_hours: int = 24
    min_check_interval_hours: int = 6
    max_check_interval_days: int = 7
    full_rescrape_interval_hours: int = 24
    full_rescrape_backoff_enabled: bool = True

    # Lightweight change detection
    lightweight_check_enabled: bool = True
    lightweight_check_interval_minutes: int = 5  # Check each project every 5 min
    lightweight_concurrent_requests: int = 20  # Max concurrent HEAD requests per project
    lightweight_request_delay_ms: int = 50  # Delay between requests (politeness)
    lightweight_change_threshold_percent: int = 20  # % of pages with ETag changes to auto-trigger rescrape
    lightweight_significance_threshold: int = 30  # Heuristic score threshold for cumulative drift

    # Task queue backend (for future extensibility)
    task_queue_backend: Literal["celery", "sqs"] = "celery"

    # LLM API Keys
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = "gpt-4o-mini"
    


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

