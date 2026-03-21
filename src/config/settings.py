"""
Application settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Google Gemini API
    gemini_api_key: str
    gemini_strategist_model: str = "gemini-flash-latest"
    gemini_generator_model: str = "gemini-flash-latest"
    gemini_model: str = "gemini-flash-latest" # Default/Fallback

    # Replicate API
    replicate_api_token: str = ""
    replicate_model: str = "ideogram-ai/ideogram-v2"
    replicate_llm_model: str = "meta/meta-llama-3-70b-instruct"

    # Groq API
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-70b-versatile"

    # Content Generation
    image_provider: str = "replicate"  # 'gemini' or 'replicate'
    llm_provider: str = "groq"         # 'gemini', 'replicate', or 'groq'

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
