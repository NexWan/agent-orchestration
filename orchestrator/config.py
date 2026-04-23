from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    codex_model: str = "gpt-5.3-codex"
    claude_permission_mode: str = "acceptEdits"
    codex_repo_dir: Path = Path("./codex")
    codex_bin: Path | None = None
    generated_projects_dir: Path = Path("./generated-projects")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
