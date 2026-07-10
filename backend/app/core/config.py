from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    github_token: str = ""
    model_name: str = "gpt-4o-mini"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    db_path: str = "maestro.db"
    lab_config_path: str = "lab_config.json"
    lab_docs_dir: str = "lab_documents"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Prevents infinite BO loops when sample failure rate is high.
    max_total_attempts_factor: int = 3


_settings = Settings()

# Expose as module-level constants for backward compatibility
GITHUB_TOKEN              = _settings.github_token
MODEL_NAME                = _settings.model_name
BACKEND_HOST              = _settings.backend_host
BACKEND_PORT              = _settings.backend_port
DB_PATH                   = _settings.db_path
MAX_TOTAL_ATTEMPTS_FACTOR = _settings.max_total_attempts_factor