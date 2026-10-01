"""Central runtime settings. Implements docs/DESIGN.md section 4 (config via pydantic-settings)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    database_url_readonly: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"

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
