"""
Story structure models for narrative-driven content generation.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class CinematicSpecs(BaseModel):
    """Visual/cinematographic specifications for a beat."""
    shot_type: str = "medium"  # close-up, medium, wide, extreme-close-up
    camera_angle: str = "eye-level"  # eye-level, low-angle, high-angle
    lighting_mood: str = "natural"  # dramatic, soft, harsh, natural, golden-hour
    color_temperature: str = "neutral"  # warm, cool, neutral
    emotional_tone: str = "neutral"  # tense, hopeful, shocking, calm, urgent
    composition_notes: Optional[str] = None  # Specific framing guidance

    class Config:
        frozen = False


class NarrativeBeat(BaseModel):
    """A single beat in the story progression."""
    beat_number: int
    purpose: str  # hook, context, development, climax, resolution, cta
    emotional_goal: str  # What emotion/realization this beat should create
    key_message: str  # The core insight this beat delivers
    data_to_use: List[str] = Field(default_factory=list)  # Which verified data points to reference
    transition_to_next: Optional[str] = None  # How this beat leads to the next one
    why_this_matters: Optional[str] = None  # Human stake in this beat
    cinematic_specs: Optional[CinematicSpecs] = None  # Visual direction for this beat

    class Config:
        frozen = False


class StoryOutline(BaseModel):
    """Complete narrative structure for a carousel."""
    story_spine: str  # One-sentence summary of the story arc
    throughline: str  # The connecting thread between all beats
    narrative_beats: List[NarrativeBeat]
    resolution_payoff: str  # What makes the ending satisfying
    audience_takeaway: str  # What the reader walks away understanding

    class Config:
        frozen = False


class StoryValidation(BaseModel):
    """Validation result for story coherence."""
    is_coherent: bool
    issues: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    score: float  # 0-10 narrative quality score

    class Config:
        frozen = False
