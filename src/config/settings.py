"""
Application settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Google Gemini API
    gemini_api_key: str
    gemini_model: str = "gemini-2.0-flash"

    # Replicate API
    replicate_api_token: str = ""
    replicate_model: str = "black-forest-labs/flux-schnell"
    replicate_llm_model: str = "meta/meta-llama-3.1-405b-instruct"

    # Content Generation
    image_provider: str = "gemini"  # 'gemini' or 'replicate'
    llm_provider: str = "gemini"    # 'gemini' or 'replicate'

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
