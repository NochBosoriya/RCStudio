import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    DB_URL: str = os.getenv("DB_URL", "sqlite:///./storage/khmerdub.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    STORAGE_PATH: str = os.getenv("STORAGE_PATH", "./storage")

    class Config:
        env_file = ".env"
        extra = "allow"  # Allow extra env vars for compatibility


settings = Settings()
