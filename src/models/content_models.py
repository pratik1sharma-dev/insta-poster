"""
Pydantic models for content generation and publishing.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Union, Dict
from pydantic import BaseModel, Field


class HookType(str, Enum):
    """Types of hooks for carousel posts."""
    CURIOSITY = "curiosity"
    VALUE_PROPOSITION = "value_proposition"
    CONTROVERSY = "controversy"
    RELATABILITY = "relatability"
    QUESTION = "question"
    STAT_SHOCK = "stat_shock"
    PATTERN_INTERRUPT = "pattern_interrupt"
    VALUE_REVELATION = "value_revelation"


class SlidePurpose(str, Enum):
    """Purpose of each slide in the carousel."""
    HOOK = "hook"
    INTRO = "intro"
    CONTENT = "content"
    JOURNEY = "journey"
    CLIMAX = "climax"
    RESOLUTION = "resolution"
    CONCLUSION = "conclusion"
    CTA = "cta"


class ChannelConfig(BaseModel):
    """Configuration for an Instagram channel."""
    name: str
    theme: str
    brand_mission: Optional[str] = None
    target_audience: str
    cultural_context: Optional[str] = None
    posting_schedule: str
    curated_topics: List[str]
    allow_ai_discovery: bool = True
    style_guidelines: str
    visual_preferences: Optional[List[str]] = None
    tone: str = "engaging"
    strategist_persona: Optional[str] = None   # Lead strategist role for this channel
    content_team_persona: Optional[str] = None
    copy_voice_examples: Optional[str] = None
    localization_type: str = "global"
    voice_id: Optional[str] = None  # Per-channel Edge-TTS voice ID
    cinematic_hook_examples: Optional[str] = None  # Channel-specific hook examples for cinematic reels
    cinematic_story_example: Optional[str] = None  # Channel-specific story example for cinematic reels
    strategic_core: Optional[str] = None           # Strategic principles injected into cinematic system prompt

    # Character-driven storytelling (LoRA-based consistent character)
    character_lora: Optional[str] = None          # e.g. "Indian-v2:0.8"
    character_description: Optional[str] = None   # e.g. "Indian woman, dark hair, brown eyes"
    character_trigger_words: Optional[str] = None # LoRA trigger words from CivitAI

    # Publishing — override which Instagram account to post to
    # Allows multiple channel configs (e.g. storycapsules) to share one account (e.g. pagecapsules)
    instagram_account: Optional[str] = None

    # Scheduler — automated posting times (local HH:MM, 24h) and post type
    post_times: Optional[List[str]] = None        # e.g. ["08:00", "20:00"]
    default_post_type: str = "cinematic"           # cinematic | carousel | reel

    class Config:
        frozen = False


class ContentStrategy(BaseModel):
    """Strategy for a single post, determined by AI."""
    topic: str
    angle: str  # The "spiky" angle or big idea for the post
    character_persona: Optional[str] = None # Optional hero for the story
    hook_type: HookType
    carousel_length: int = Field(ge=3, le=10)
    visual_metaphor: str  # The unifying visual theme for the carousel
    color_palette: Union[str, Dict[str, str]]
    typography_style: Union[str, Dict[str, str]]
    target_audience_insight: str
    verified_data: Optional[str] = None  # NEW: Real-world research extracted in Strategy phase
    reasoning: Optional[str] = None  # Why this strategy was chosen

    class Config:
        frozen = False


class CarouselSlide(BaseModel):
    """Individual slide in the carousel."""
    slide_number: int
    purpose: SlidePurpose
    text_overlay: str
    image_prompt: str
    template_name: str = "standard"  # e.g., standard, big_fact, split_comparison, cta
    background_style: str = "solid"  # e.g., solid, gradient, blurred_hook
    headline: Optional[str] = None
    subtext: Optional[str] = None
    pre_label: Optional[str] = None
    left_content: Optional[str] = None
    right_content: Optional[str] = None
    action_text: Optional[str] = None
    design_notes: Optional[str] = None

    class Config:
        frozen = False


class GeneratedContent(BaseModel):
    """Content generated for a post."""
    caption: str
    hashtags: List[str]
    call_to_action: str
    slides: List[CarouselSlide]
    estimated_engagement_score: Optional[float] = None

    class Config:
        frozen = False


class PostResult(BaseModel):
    """Result of publishing a post."""
    post_id: Optional[str]
    timestamp: datetime
    channel: str
    content: GeneratedContent
    strategy: ContentStrategy
    performance_tracking_url: Optional[str] = None
    status: str  # 'success', 'failed', 'dry_run'
    error_message: Optional[str] = None
    image_paths: List[str] = []

    class Config:
        frozen = False
