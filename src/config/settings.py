"""
Application settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Google Gemini API
    gemini_api_key: str

    # Postiz Configuration
    postiz_api_url: str = "http://localhost:3000/api"
    postiz_api_key: str

    # Logging
    log_level: str = "INFO"

    # Output directory
    output_dir: str = "output"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Global settings instance
settings = Settings()
