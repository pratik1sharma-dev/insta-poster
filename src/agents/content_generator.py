"""
Content Generator Agent - Creates captions, hashtags, and slide text.
"""
import json
import logging
from typing import List
from google import genai
from src.models import (
    ChannelConfig,
    ContentStrategy,
    GeneratedContent,
    CarouselSlide,
    SlidePurpose,
)
from src.config import settings


logger = logging.getLogger(__name__)


class ContentGenerator:
    """AI agent that generates text content for Instagram posts."""

    def __init__(self):
        """Initialize the Content Generator with Gemini API."""
        self.client = genai.Client()

    def _build_session_brief(
        self, strategy: ContentStrategy, channel_config: ChannelConfig
    ) -> str:
        """
        Shared high-level brief for this specific Instagram carousel post.
        """
        return f"""You are helping create a single Instagram carousel post.

Channel:
- Theme: {channel_config.theme}
- Target audience: {channel_config.target_audience}
- Tone: {channel_config.tone}

Post:
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Hook type: {strategy.hook_type}
- Color Palette: {strategy.color_palette}
- Typography Style: {strategy.typography_style}
- Carousel length: {strategy.carousel_length} slides

Goal:
- Create engaging, saveable content that grows followers and encourages interactions (saves, shares, comments, follows).

Global rules:
- All slides must clearly look like one cohesive series.
- Use a consistent color palette and typography across slides.
- Keep overall layout structure broadly consistent across slides.
"""

    def generate_content(
        self, strategy: ContentStrategy, channel_config: ChannelConfig
    ) -> GeneratedContent:
        """
        Generate all text content for a post.

        Args:
            strategy: Content strategy from ContentStrategist
            channel_config: Channel configuration

        Returns:
            GeneratedContent with caption, hashtags, and slides
        """
        # Generate slides with text overlays
        slides = self._generate_slides(strategy, channel_config)

        # Generate caption
        caption = self._generate_caption(strategy, channel_config, slides)

        # Generate hashtags
        hashtags = self._generate_hashtags(strategy, channel_config)

        # Generate call-to-action
        cta = self._generate_smart_cta(strategy, channel_config, slides)

        return GeneratedContent(
            caption=caption,
            hashtags=hashtags,
            call_to_action=cta,
            slides=slides,
        )

    def _generate_slides(
        self, strategy: ContentStrategy, channel_config: ChannelConfig
    ) -> List[CarouselSlide]:
        """
        Generate text and image prompts for each slide.

        Args:
            strategy: Content strategy
            channel_config: Channel configuration

        Returns:
            List of CarouselSlide objects
        """
        session_brief = self._build_session_brief(strategy, channel_config)

        prompt = f"""{session_brief}

You are creating an Instagram carousel post.

**Core Idea:**
- Topic: {strategy.topic}
- Angle: {strategy.angle}

**Strategy:**
- Hook Type: {strategy.hook_type}
- Carousel Length: {strategy.carousel_length}
- Color Palette: {strategy.color_palette}
- Typography Style: {strategy.typography_style}
- Audience Insight: {strategy.target_audience_insight}

**Your Task:**
Create {strategy.carousel_length} slides with text overlays and image prompts that argue for the post's unique **Angle**.

**Slide Breakdown:**
- Slide 1: HOOK - Introduce the Angle using a {strategy.hook_type} approach.
- Slides 2-{strategy.carousel_length - 1}: CONTENT - Each slide must provide a point, fact, or example that supports the Angle.
- Slide {strategy.carousel_length}: CTA - A call-to-action related to the Angle.

**Guidelines:**
1. Text overlays should be SHORT and PUNCHY (max 10-15 words).
2. Every slide MUST relate back to and reinforce the core **Angle**.
3. Use emojis sparingly (only where they add value).
4. Image prompts should describe the visual style in detail.
5. Maintain a consistent visual theme across all slides.

**Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "text_overlay": "The hook text here, introducing the angle.",
      "image_prompt": "Detailed description for image generation that matches the angle and hook.",
      "design_notes": "Optional notes about design choices"
    }},
    ...
  ]
}}

Respond with ONLY the JSON, no other text.
"""

        logger.debug("Slides prompt:\n%s", prompt)
        response = self.client.models.generate_content(model=settings.gemini_model, contents=prompt)
        logger.debug("Slides raw response:\n%s", getattr(response, "text", response))
        slides_data = self._parse_json_response(response.text)

        purpose_map = {
            "call-to-action": "cta",
            "call_to_action": "cta",
            "cta": "cta",
            "hook": "hook",
            "content": "content",
        }

        slides = []
        for slide_data in slides_data.get("slides", []):
            purpose_raw = str(slide_data.get("purpose", "")).strip().lower()

            # Normalize common variants
            if purpose_raw in purpose_map:
                purpose = purpose_map[purpose_raw]
            elif purpose_raw.startswith("content"):
                purpose = "content"
            elif purpose_raw.startswith("hook"):
                purpose = "hook"
            elif "call" in purpose_raw and ("action" in purpose_raw or "cta" in purpose_raw):
                purpose = "cta"
            else:
                purpose = purpose_raw
            slides.append(
                CarouselSlide(
                    slide_number=slide_data["slide_number"],
                    purpose=SlidePurpose(purpose),
                    text_overlay=slide_data["text_overlay"],
                    image_prompt=slide_data["image_prompt"],
                    design_notes=slide_data.get("design_notes"),
                )
            )

        return slides

    def _generate_caption(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
    ) -> str:
        """
        Generate Instagram caption.

        Args:
            strategy: Content strategy
            channel_config: Channel configuration
            slides: Generated slides for context

        Returns:
            Instagram caption
        """
        session_brief = self._build_session_brief(strategy, channel_config)

        slides_summary = "\n".join(
            f"Slide {s.slide_number}: {s.text_overlay}" for s in slides[:3]
        )

        prompt = f"""{session_brief}

You are writing an Instagram caption. Your goal is to be engaging and spark conversation.

**Post Context:**
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- First 3 Slides: {slides_summary}

**Channel Context:**
- Target Audience: {channel_config.target_audience}
- Tone: {channel_config.tone}

**Caption Requirements:**
1. **Hook (first 125 characters)**: Grab attention by introducing the post's unique **Angle**.
2. **Value**: Briefly explain the value of understanding this angle.
3. **Engagement**: End with a specific, open-ended question related to the Angle (this will be added later, so you don't need to write it).
4. **Length**: 150-300 characters.
5. **Readability**: Use line breaks to make it easy to read.
6. **Emojis**: Use 1-3 relevant emojis.
7. **No Hashtags**: Do not include hashtags in the caption.

**Style:**
- Conversational and authentic.
- Opinionated, reflecting the post's Angle.
- Benefit-focused.

Write the caption now (no JSON, just the caption text):
"""

        logger.debug("Caption prompt:\n%s", prompt)
        response = self.client.models.generate_content(model=settings.gemini_model, contents=prompt)
        logger.debug("Caption raw response:\n%s", getattr(response, "text", response))
        return response.text.strip()

    def _generate_hashtags(
        self, strategy: ContentStrategy, channel_config: ChannelConfig
    ) -> List[str]:
        """
        Generate relevant hashtags.

        Args:
            strategy: Content strategy
            channel_config: Channel configuration

        Returns:
            List of hashtags
        """
        session_brief = self._build_session_brief(strategy, channel_config)

        prompt = f"""{session_brief}

Generate Instagram hashtags for a post about: {strategy.topic}

**Channel Theme:** {channel_config.theme}
**Target Audience:** {channel_config.target_audience}

**Requirements:**
1. 20-25 hashtags total
2. Mix of sizes:
   - 3-5 large hashtags (500k+ posts): broad reach
   - 8-10 medium hashtags (50k-500k): targeted reach
   - 7-10 niche hashtags (<50k): highly targeted
3. All hashtags must be relevant to the topic and theme
4. Include trending hashtags when applicable
5. No banned or spam hashtags

**Output Format (JSON):**
{{
  "hashtags": ["hashtag1", "hashtag2", ...]
}}

Note: Include hashtags WITHOUT the # symbol.

Respond with ONLY the JSON, no other text.
"""

        logger.debug("Hashtags prompt:\n%s", prompt)
        response = self.client.models.generate_content(model=settings.gemini_model, contents=prompt)
        logger.debug("Hashtags raw response:\n%s", getattr(response, "text", response))
        hashtags_data = self._parse_json_response(response.text)

        return ["#" + tag.lstrip("#") for tag in hashtags_data.get("hashtags", [])]

    def _generate_smart_cta(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
    ) -> str:
        """Generate a content-specific, engaging CTA."""

        slides_summary = "\n".join(
            f"Slide {s.slide_number}: {s.text_overlay}" for s in slides
        )

        prompt = f"""You are an expert Instagram copywriter. Your goal is to write a Call-to-Action (CTA) that sparks conversation and builds community.

**Channel Context:**
- Tone: {channel_config.tone}
- Audience: {channel_config.target_audience}

**Post Context:**
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Post Summary: {slides_summary}

**The WORST CTAs are generic (e.g., "like this post," "follow for more"). DO NOT use them.**

**Your Task:**
Write a single, compelling, open-ended question that directly relates to the post's content. The question should encourage users to share their own experiences, opinions, or plans in the comments.

**Examples of GOOD CTAs:**
- For a post on productivity: "What's one productivity hack you swear by? Share it below!"
- For a post on a travel destination: "If you could go tomorrow, what's the first thing you would do in Tokyo? 🗼"
- For a post on a book summary: "What was your biggest takeaway from this book? Did you agree with the author's main point?"

Now, write the perfect CTA for THIS post. Respond with ONLY the CTA text.
"""
        response = self.client.models.generate_content(model=settings.gemini_model, contents=prompt)
        return response.text.strip()

    def _parse_json_response(self, response_text: str) -> dict:
        """
        Parse JSON from Gemini response.

        Args:
            response_text: Raw response text

        Returns:
            Parsed JSON dictionary
        """
        # Clean response (remove markdown code blocks if present)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}
