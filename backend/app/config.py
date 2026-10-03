from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./netdoctor.db"
    agent_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b-q4_K_M"
    rules_path: str = "backend/app/rules.yaml"
    health_score_path: str | None = str(Path(__file__).with_name("health_score_v1_1.yaml"))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
