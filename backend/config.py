"""
Syrus Backend — Configuration
Reads from environment variables / .env file
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google Gemini
    gemini_api_key: str

    # 021 Trade API
    trade021_username: str = ""  # Your UCC (e.g., HACK1234)
    trade021_password: str = ""  # Your sign-up password
    trade021_base_url: str = "https://devapi.021.trade/api/developer-api/v1"
    use_real_api: bool = False  # Set to True to use real 021 API instead of mock

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
