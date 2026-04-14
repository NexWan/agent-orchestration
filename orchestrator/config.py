from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings): 
    anthropic_api_key: str
    openai_api_key: str
    codex_model: str = "gpt-5.3-codex"
    output_dir: Path = Path("./output")

    model_config = {"env_file": ".env"}

settings = Settings()