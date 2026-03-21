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

    class Config:
        frozen = False


class ContentStrategy(BaseModel):
    """Strategy for a single post, determined by AI."""
    topic: str
    angle: str  # The "spiky" angle or big idea for the post
    hook_type: HookType
    carousel_length: int = Field(ge=3, le=10)
    visual_metaphor: str  # The unifying visual theme for the carousel
    color_palette: Union[str, Dict[str, str]]
    typography_style: Union[str, Dict[str, str]]
    target_audience_insight: str
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
