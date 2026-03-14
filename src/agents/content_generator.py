"""
Content Generator Agent - Creates captions, hashtags, and slide text.
"""
import json
import logging
from typing import List
import google.generativeai as genai
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
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)

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
- Hook type: {strategy.hook_type}
- Visual style: {strategy.visual_style}
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
        cta = self._generate_cta(strategy, channel_config)

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

You are creating an Instagram carousel post about: {strategy.topic}

**Strategy:**
- Hook Type: {strategy.hook_type}
- Carousel Length: {strategy.carousel_length} slides
- Visual Style: {strategy.visual_style}
- Audience Insight: {strategy.target_audience_insight}

**Channel Context:**
- Theme: {channel_config.theme}
- Target Audience: {channel_config.target_audience}
- Tone: {channel_config.tone}

**Your Task:**
Create {strategy.carousel_length} slides with text overlays and image prompts.

**Slide Breakdown:**
- Slide 1: HOOK - Must stop the scroll using {strategy.hook_type} approach
- Slides 2-{strategy.carousel_length - 1}: CONTENT - Key insights, one per slide
- Slide {strategy.carousel_length}: CTA - Call-to-action, encourage engagement

**Guidelines:**
1. Text overlays should be SHORT and PUNCHY (max 10-15 words)
2. Each slide should be self-contained but build on previous ones
3. Use emojis sparingly (only where they add value)
4. Image prompts should describe the visual style in detail
5. Maintain consistent visual theme across all slides

**Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "text_overlay": "The hook text here",
      "image_prompt": "Detailed description for image generation: style, colors, layout, mood",
      "design_notes": "Optional notes about design choices"
    }},
    ...
  ]
}}

Respond with ONLY the JSON, no other text.
"""

        logger.debug("Slides prompt:\n%s", prompt)
        response = self.model.generate_content(prompt)
        logger.debug("Slides raw response:\n%s", getattr(response, "text", response))
        slides_data = self._parse_json_response(response.text)

        purpose_map = {"call-to-action": "cta", "call_to_action": "cta"}

        slides = []
        for slide_data in slides_data.get("slides", []):
            purpose = slide_data["purpose"]
            purpose = purpose_map.get(purpose.lower(), purpose)
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

You are writing an Instagram caption for a carousel post about: {strategy.topic}

**First 3 Slides:**
{slides_summary}

**Channel Context:**
- Target Audience: {channel_config.target_audience}
- Tone: {channel_config.tone}
- Theme: {channel_config.theme}

**Caption Requirements:**
1. **Hook (first 125 characters)**: Must stop the scroll - use {strategy.hook_type} approach
2. **Value**: Clearly state what they'll learn/gain
3. **Engagement**: End with a question or prompt to engage
4. **Length**: 150-300 characters (Instagram favors concise captions)
5. **Line breaks**: Use for readability (double line break between sections)
6. **Emojis**: Use 1-3 relevant emojis maximum
7. **No hashtags**: Those go separately

**Style:**
- Conversational but professional
- Action-oriented
- Benefit-focused

Write the caption now (no JSON, just the caption text):
"""

        logger.debug("Caption prompt:\n%s", prompt)
        response = self.model.generate_content(prompt)
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
        response = self.model.generate_content(prompt)
        logger.debug("Hashtags raw response:\n%s", getattr(response, "text", response))
        hashtags_data = self._parse_json_response(response.text)

        return ["#" + tag.lstrip("#") for tag in hashtags_data.get("hashtags", [])]

    def _generate_cta(
        self, strategy: ContentStrategy, channel_config: ChannelConfig
    ) -> str:
        """
        Generate call-to-action.

        Args:
            strategy: Content strategy
            channel_config: Channel configuration

        Returns:
            Call-to-action text
        """
        cta_options = [
            "Save this for later!",
            "Share with someone who needs this",
            "Double tap if you agree",
            "Follow for more insights",
            "What's your take? Comment below",
            "Tag someone who should see this",
        ]

        # For now, use a random CTA - could be made smarter with AI
        import random

        return random.choice(cta_options)

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
