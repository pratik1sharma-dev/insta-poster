"""
Content Strategist Agent - Determines topic, hook strategy, and carousel structure.
"""
import json
import random
from typing import Optional
import google.generativeai as genai
from src.models import ChannelConfig, ContentStrategy, HookType, VisualStyle
from src.config import settings


class ContentStrategist:
    """AI agent that plans content strategy for Instagram posts."""

    def __init__(self):
        """Initialize the Content Strategist with Gemini API."""
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)

    def plan_content(
        self, channel_config: ChannelConfig, topic_hint: Optional[str] = None
    ) -> ContentStrategy:
        """
        Plan content strategy for a post.

        Args:
            channel_config: Channel configuration
            topic_hint: Optional specific topic to use (overrides AI selection)

        Returns:
            ContentStrategy with all decisions
        """
        # If topic hint provided, use it; otherwise let AI decide
        if topic_hint:
            topic = topic_hint
        elif channel_config.allow_ai_discovery and random.random() < 0.3:
            # 30% chance to discover new topic
            topic = self._discover_topic(channel_config)
        else:
            # Select from curated list
            topic = random.choice(channel_config.curated_topics)

        # Use Gemini to determine optimal strategy
        prompt = self._build_strategy_prompt(channel_config, topic)
        response = self.model.generate_content(prompt)

        # Parse strategy from response
        strategy = self._parse_strategy_response(response.text, topic)

        return strategy

    def _discover_topic(self, channel_config: ChannelConfig) -> str:
        """
        Use AI to discover a new trending topic.

        Args:
            channel_config: Channel configuration

        Returns:
            New topic suggestion
        """
        prompt = f"""You are a content strategist for an Instagram channel about:
{channel_config.theme}

Target audience: {channel_config.target_audience}

Current curated topics:
{chr(10).join(f"- {topic}" for topic in channel_config.curated_topics[:10])}

Suggest ONE new, trending topic that would resonate with this audience.
The topic should be:
1. Timely and relevant
2. Different from existing curated topics
3. Engaging for the target audience
4. Suitable for a carousel post (has multiple key points)

Respond with ONLY the topic name (e.g., "Book Title by Author" or "Concept Name").
"""

        response = self.model.generate_content(prompt)
        return response.text.strip().strip('"').strip("'")

    def _build_strategy_prompt(self, channel_config: ChannelConfig, topic: str) -> str:
        """
        Build prompt for strategy determination.

        Args:
            channel_config: Channel configuration
            topic: Selected topic

        Returns:
            Strategy prompt
        """
        return f"""You are a content strategist for Instagram. Plan a carousel post strategy.

**Channel Context:**
- Theme: {channel_config.theme}
- Target Audience: {channel_config.target_audience}
- Tone: {channel_config.tone}
- Style Guidelines: {channel_config.style_guidelines}

**Topic:** {topic}

**Your Task:**
Plan the strategy for this carousel post. Think through:

1. **Hook Strategy**: What type of opening will stop the scroll?
   - curiosity: Intriguing question or mystery
   - value_proposition: Clear benefit upfront
   - controversy: Bold or contrarian take
   - relatability: "You're not alone" moment
   - question: Thought-provoking question
   - stat_shock: Surprising statistic

2. **Carousel Length**: How many slides (3-10) would best convey this content?
   - Consider topic complexity
   - Keep audience attention span in mind
   - Each slide should add value

3. **Visual Style**: What visual approach fits this topic?
   - quote_based: Focus on key quotes/phrases
   - infographic: Data-driven visualizations
   - mixed: Combination of styles
   - minimalist: Clean, simple designs
   - bold_text: Large, impactful typography

4. **Audience Insight**: What specific pain point or desire does this address?

**Output Format (JSON):**
{{
  "hook_type": "one of the hook types above",
  "carousel_length": <number between 3-10>,
  "visual_style": "one of the visual styles above",
  "target_audience_insight": "specific insight about what audience wants",
  "reasoning": "brief explanation of your strategy choices"
}}

Respond with ONLY the JSON, no other text.
"""

    def _parse_strategy_response(self, response_text: str, topic: str) -> ContentStrategy:
        """
        Parse Gemini's strategy response into ContentStrategy model.

        Args:
            response_text: Raw response from Gemini
            topic: Topic being planned

        Returns:
            ContentStrategy instance
        """
        # Clean response (remove markdown code blocks if present)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        # Parse JSON
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback to sensible defaults if parsing fails
            return ContentStrategy(
                topic=topic,
                hook_type=HookType.VALUE_PROPOSITION,
                carousel_length=7,
                visual_style=VisualStyle.MIXED,
                target_audience_insight="Seeking actionable insights",
                reasoning="Default strategy due to parsing error",
            )

        # Create ContentStrategy
        return ContentStrategy(
            topic=topic,
            hook_type=HookType(data["hook_type"]),
            carousel_length=max(3, min(10, data["carousel_length"])),
            visual_style=VisualStyle(data["visual_style"]),
            target_audience_insight=data["target_audience_insight"],
            reasoning=data["reasoning"],
        )
