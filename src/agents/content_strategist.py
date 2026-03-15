"""
Content Strategist Agent - Determines topic, hook strategy, and carousel structure.
"""
import json
import random
import logging
from typing import Optional
import google.generativeai as genai
from src.models import ChannelConfig, ContentStrategy, HookType
from src.config import settings


logger = logging.getLogger(__name__)


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
        logger.debug("Strategy prompt:\n%s", prompt)
        response = self.model.generate_content(prompt)
        logger.debug("Strategy raw response:\n%s", getattr(response, "text", response))

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

        logger.debug("Topic discovery prompt:\n%s", prompt)
        response = self.model.generate_content(prompt)
        logger.debug("Topic discovery raw response:\n%s", getattr(response, "text", response))
        return response.text.strip().strip('"').strip("'")

    def _build_strategy_prompt(self, channel_config: ChannelConfig, topic: str) -> str:
        """Build prompt for strategy determination."""
        return f"""You are a world-class Instagram growth strategist who is an expert at creating content that sparks conversation.
Your primary goal is to develop a "spiky point of view" for each post that will make people stop, think, and engage. Avoid generic, boring content at all costs.

**Channel Context:**
- Theme: {channel_config.theme}
- Target Audience: {channel_config.target_audience}
- Tone: {channel_config.tone}

**Today's Topic:** {topic}

**Your Task:**
Devise a content strategy with a strong, unique angle.

1.  **Find the "Spiky" Angle:** What is a surprising, controversial, counter-intuitive, or highly relatable "big idea" related to this topic? Don't just summarize. Take a stand. What's a take that most people haven't considered?
2.  **Choose a Hook Strategy:** Based on your angle, what is the best hook to grab attention?
    - `curiosity`: Hint at the surprising angle.
    - `controversy`: State the controversial opinion directly.
    - `relatability`: Frame the angle as a shared, unspoken truth.
    - `value_proposition`: Clearly state the benefit of understanding this new angle.
    - `question`: Ask a question that challenges a common belief.
3.  **Determine Carousel Length:** How many slides (3-10) are needed to effectively argue for your angle?
4.  **Define a Visual Metaphor:** Invent a single, powerful visual metaphor that represents the post's Angle. This metaphor must be used across all slides to create a cohesive visual story. For example, for an angle about "focus," a visual metaphor could be "a laser beam vs. a floodlight."
5.  **Define the Visuals:** Based on the metaphor, define the creative direction.
    - `color_palette`: Describe a sophisticated and engaging color palette. Think in terms of a primary, secondary, and accent color. (e.g., "A palette of dark slate grey, off-white, and a vibrant but not overpowering electric blue accent").
    - `typography_style`: Describe the desired font style. (e.g., "A clean, modern sans-serif font like 'Inter', using bold for headers and regular for body text to create clear hierarchy").
6.  **Identify the Core Insight:** What specific pain point or desire does this angle tap into for the target audience?

**Output Format (JSON):**
{{
  "angle": "The unique, spiky angle for this post. This is the most important field.",
  "hook_type": "one of the hook types above",
  "carousel_length": <number between 3-10>,
  "visual_metaphor": "The single, unifying visual metaphor for the entire carousel.",
  "color_palette": "A description of the color palette.",
  "typography_style": "A description of the typography style.",
  "target_audience_insight": "The specific insight this angle addresses.",
  "reasoning": "Explain WHY this strategy is compelling and will drive engagement."
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
                angle="A default angle because the LLM response was not valid JSON.",
                hook_type=HookType.VALUE_PROPOSITION,
                carousel_length=7,
                visual_metaphor="No visual metaphor due to parsing error.",
                color_palette="A default color palette.",
                typography_style="A default typography style.",
                target_audience_insight="Seeking actionable insights",
                reasoning="Default strategy due to parsing error",
            )

        # Create ContentStrategy
        return ContentStrategy(
            topic=topic,
            angle=data["angle"],
            hook_type=HookType(data["hook_type"]),
            carousel_length=max(3, min(10, data["carousel_length"])),
            visual_metaphor=data["visual_metaphor"],
            color_palette=data["color_palette"],
            typography_style=data["typography_style"],
            target_audience_insight=data["target_audience_insight"],
            reasoning=data.get("reasoning"), # Now optional
        )
