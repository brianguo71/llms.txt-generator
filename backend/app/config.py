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
    
    # Firecrawl API
    firecrawl_api_key: str | None = None

    # Change detection
    default_check_interval_hours: int = 24
    min_check_interval_hours: int = 6
    max_check_interval_days: int = 7

    # Task queue backend (for future extensibility)
    task_queue_backend: Literal["celery", "sqs"] = "celery"

    # LLM API Keys
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = "gpt-4o-mini"

    # ChangeDetection.io integration
    changedetection_url: str = "http://changedetection:5000"
    changedetection_api_key: str | None = None
    
    # Webshare.io proxy configuration
    webshare_proxy_url: str | None = None  # Format: http://user:pass@proxy.webshare.io:80
    
    # Webhook configuration (for changedetection.io callbacks)
    webhook_base_url: str = "http://api:8000"  # Internal Docker network URL
    


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

