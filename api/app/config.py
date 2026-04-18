from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from dotenv import load_dotenv
import os

# Load .env file explicitly to ensure it works across different environments
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/postgres"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.4-mini"
    GEMINI_API_KEY: str = ""
    GOOGLE_VISION_API_KEY: str = ""
    GOOGLE_SEARCH_API_KEY: str = ""
    GOOGLE_SEARCH_CX: str = ""
    GOOGLE_SEARCH_MAX_RESULTS: int = 5
    BRIGHT_DATA_API_KEY: str = ""
    BRIGHT_DATA_DATASET_ID: str = "gd_m7re62tb1w88ymy86r"
    BRIGHT_DATA_MAX_URLS_PER_QUERY: int = 12
    BRIGHT_DATA_BATCH_SIZE: int = 12
    BRIGHT_DATA_POLL_SECONDS: int = 4
    BRIGHT_DATA_MAX_WAIT_SECONDS: int = 120
    BRIGHT_DATA_ONLY_MODE: bool = False
    KIMI_API_KEY: str = ""
    KIMI_BASE_URL: str = "https://api.moonshot.ai/v1"
    KIMI_MODEL: str = "moonshot-v1-32k"
    FIRECRAWL_URL: str = "http://localhost:3002"
    ML_CLIENT_ID: str = ""
    ML_CLIENT_SECRET: str = ""
    ML_REDIRECT_URI: str = "http://localhost:8000/api/integrations/mercadolivre/callback"
    ML_OAUTH_STATE_SECRET: str = ""
    ML_ACCESS_TOKEN: str = ""
    ML_REFRESH_TOKEN: str = ""
    ML_TOKEN_EXPIRES_AT: float = 0
    ML_TOKEN_SCOPE: str = ""
    ML_TOKEN_USER_ID: int = 0
    ML_OFFICIAL_ONLY: bool = True
    ML_MAX_REQUESTS_PER_SEARCH: int = 50
    APIFY_API_KEY: str = ""
    APIFY_ML_ACTOR_ID: str = "saswave/mercadolibre-product-scraper"
    APIFY_PREFERRED_ENDPOINT: str = "run-sync-get-dataset-items"

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="allow"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()
