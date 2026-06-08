from __future__ import annotations
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    # App
    APP_NAME: str = "QAptain"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/qaptain"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # ChromaDB
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_COLLECTION_PREFIX: str = "qaptain"

    # AI Providers
    AI_PROVIDER: Literal["anthropic", "openai", "azure_openai", "gemini"] = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4o"
    AZURE_OPENAI_API_VERSION: str = "2025-01-01-preview"

    # AI Models
    PRIMARY_MODEL: str = "claude-opus-4-7"
    FAST_MODEL: str = "claude-haiku-4-5-20251001"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_FAST_MODEL: str = "gemini-2.0-flash"

    # Security
    SECRET_KEY: str = "change-this-in-production-minimum-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Encryption (for stored credentials)
    ENCRYPTION_KEY: str = ""

    # Selenium
    SELENIUM_HEADLESS: bool = True
    SELENIUM_WINDOW_WIDTH: int = 1920
    SELENIUM_WINDOW_HEIGHT: int = 1080
    SELENIUM_PAGE_LOAD_TIMEOUT: int = 60
    SELENIUM_IMPLICIT_WAIT: int = 10

    # Execution
    MAX_CONCURRENT_EXECUTIONS: int = 5
    EXECUTION_TIMEOUT_SECONDS: int = 1800  # 30 minutes

    # Screenshots & Videos
    ARTIFACTS_DIR: str = "./artifacts"
    SCREENSHOTS_DIR: str = "./artifacts/screenshots"
    VIDEOS_DIR: str = "./artifacts/videos"

    # Explore Engine
    MAX_EXPLORE_DEPTH: int = 4
    MAX_EXPLORE_PAGES: int = 50
    EXPLORE_TIMEOUT_SECONDS: int = 3600  # 1 hour

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # .env is shared with the frontend — ignore unknown fields


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
