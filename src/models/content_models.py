"""
Pydantic models for content generation and publishing.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class HookType(str, Enum):
    """Types of hooks for carousel posts."""
    CURIOSITY = "curiosity"
    VALUE_PROPOSITION = "value_proposition"
    CONTROVERSY = "controversy"
    RELATABILITY = "relatability"
    QUESTION = "question"
    STAT_SHOCK = "stat_shock"


class VisualStyle(str, Enum):
    """Visual styles for carousel images."""
    QUOTE_BASED = "quote_based"
    INFOGRAPHIC = "infographic"
    MIXED = "mixed"
    MINIMALIST = "minimalist"
    BOLD_TEXT = "bold_text"


class SlidePurpose(str, Enum):
    """Purpose of each slide in the carousel."""
    HOOK = "hook"
    CONTENT = "content"
    CTA = "cta"


class ChannelConfig(BaseModel):
    """Configuration for an Instagram channel."""
    name: str
    theme: str
    target_audience: str
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
    visual_style: VisualStyle
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
