"""Central runtime settings. Implements docs/DESIGN.md section 4 (config via pydantic-settings)."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_async_driver(url: str) -> str:
    """Rewrite a plain `postgresql://` URL to the asyncpg driver scheme.

    Managed Postgres providers (Render among them) hand out bare
    `postgresql://` connection strings; SQLAlchemy's async engine then
    defaults to the sync psycopg dialect and fails at startup. Every other
    scheme (sqlite+aiosqlite, already-qualified postgresql+asyncpg, ...)
    passes through unchanged.
    """
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    database_url_readonly: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url", "database_url_readonly")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        return _to_async_driver(v)

    llm_provider: str = "stub"
    anthropic_api_key: str = ""

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    seed: int = 42


@lru_cache
def get_settings() -> Settings:
    return Settings()
