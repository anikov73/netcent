from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://finapp:finapp@localhost:5433/finapp"
    upload_dir: str = "uploads"
    timezone: str = "Europe/Zurich"
    large_transaction_threshold: float = 500.0
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"


settings = Settings()
