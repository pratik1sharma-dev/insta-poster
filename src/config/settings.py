"""
Application settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # ── Google Gemini ──────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_strategist_model: str = "gemini-2.0-flash"
    gemini_generator_model: str = "gemini-2.0-flash"
    gemini_image_model: str = "gemini-2.0-flash-exp-image-generation"
    gemini_model: str = "gemini-2.0-flash"          # fallback

    # ── Replicate ──────────────────────────────────────────────────────
    replicate_api_token: str = ""
    replicate_model: str = "ideogram-ai/ideogram-v2"
    replicate_llm_model: str = "meta/meta-llama-3-70b-instruct"

    # ── Groq ───────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3-32b"              # was qwen-2.5-32b — fixed

    # ── Tavily search ──────────────────────────────────────────────────
    tavily_api_key: str = ""

    # ── LLM provider ──────────────────────────────────────────────────
    # Options: 'gemini' | 'replicate' | 'groq'
    llm_provider: str = "groq"

    # ── Image provider ────────────────────────────────────────────────
    # Options: 'gemini' | 'replicate' | 'sd'
    image_provider: str = "sd"

    # ── Stable Diffusion WebUI (via Tailscale) ────────────────────────
    sd_api_url: str = "http://100.67.231.93:7860/sdapi/v1/txt2img"
    sd_steps: int = 20                              # 20 steps at 640x1120 ≈ same time as 15 at 768x1344
    sd_timeout: int = 600                           # 10 minutes for high-res portrait
    sd_width: int = 1080
    sd_height: int = 1080
    # Negative prompt applied to every SD generation
    sd_negative_prompt: str = (
        "text, watermark, logo, caption, letters, words, typography, "
        "signature, username, blurry, low quality, distorted, ugly, "
        "multiple panels, collage, split screen, grid, "
        "lowres, bad anatomy, worst quality, jpeg artifacts, "
        "deformed, disfigured, bad proportions, extra limbs, "
        "flat lighting, overexposed, underexposed"
    )

    # ── TTS / Voice ───────────────────────────────────────────────────
    # Options: 'gtts' | 'edge' | 'elevenlabs'
    tts_provider: str = "edge"
    edge_tts_voice: str = "en-IN-PrabhatNeural"     # Professional Indian Male
    # Alternative Indian voices:
    #   en-IN-NeerjaNeural      — Indian Female
    #   en-IN-PrabhatNeural     — Indian Male (default)
    #   en-IN-AnanyaNeural      — Indian Female (newer)
    #   en-IN-MadhurNeural      — Indian Male (newer)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel — change to Indian voice
    bark_speaker: str = "v2/en_speaker_9"           # deprecated, kept for compatibility

    # ── Reel settings ─────────────────────────────────────────────────
    reel_max_slides: int = 5                        # max slides per Reel
    reel_max_duration: int = 60                     # target max seconds
    reel_transition_duration: float = 0.4           # cross-fade seconds
    reel_slide_tail: float = 0.3                    # pause after narration ends
    reel_music_volume: float = 0.10                 # background music level
    reel_fps: int = 25

    # ── Cinematic Reel settings ───────────────────────────────────────
    cinematic_text_animation_enabled: bool = True
    cinematic_animation_speed: str = "medium"  # Options: 'slow', 'medium', 'fast'
    cinematic_slide_duration: float = 4.0
    cinematic_transition_duration: float = 0.6
    cinematic_music_volume: float = 0.15
    cinematic_font_path: str = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    cinematic_font_bold_path: str = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"

    # ── Postiz publishing ─────────────────────────────────────────────
    postiz_api_url: str = "http://localhost:3000/api"
    postiz_api_key: str = ""

    # ── Logging & output ──────────────────────────────────────────────
    log_level: str = "INFO"
    output_dir: str = "output"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Global settings instance
settings = Settings()