"""
Syrus Backend — Configuration
Reads from environment variables / .env file
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google Gemini
    gemini_api_key: str

    # Security
    approval_token_secret: str
    approval_token_ttl_seconds: int = 60  # token expires in 60 seconds

    # Database
    database_url: str = "postgresql+asyncpg://syrus:syrus_secret@localhost:5432/syrus"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Mock API
    mock_api_url: str = "http://localhost:8001"

    # App
    app_name: str = "Syrus Trading Copilot"
    debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
