from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    github_token:              str = ""
    model_name:                str = "gpt-4o-mini"
    backend_host:              str = "127.0.0.1"
    backend_port:              int = 8000
    db_path:                   str = ""
    lab_config_path:           str = "lab_config.json"
    lab_docs_dir:              str = "lab_documents"
    cors_origins:              str = "http://localhost:3000,http://127.0.0.1:3000"
    max_total_attempts_factor: int = 3


settings = Settings()

# Anchor DB to the backend/ directory regardless of working directory.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
DB_PATH      = settings.db_path or str(_BACKEND_DIR / "maestro.db")

GITHUB_TOKEN              = settings.github_token
MODEL_NAME                = settings.model_name
MAX_TOTAL_ATTEMPTS_FACTOR = settings.max_total_attempts_factor