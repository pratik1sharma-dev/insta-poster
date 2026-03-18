"""
Content Strategist Agent - Determines topic, hook strategy, and carousel structure.
"""
import json
import random
import logging
import time
from typing import Optional
from google import genai
import replicate
from replicate.exceptions import ReplicateError
from src.models import ChannelConfig, ContentStrategy, HookType
from src.config import settings


logger = logging.getLogger(__name__)


class ContentStrategist:
    """AI agent that plans content strategy for Instagram posts."""

    def __init__(self):
        """Initialize the Content Strategist with the requested provider."""
        self.provider = settings.llm_provider.lower()
        
        if self.provider == "gemini":
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model = settings.gemini_model
        elif self.provider == "replicate":
            self.model = settings.replicate_llm_model
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _generate_text(self, prompt: str) -> str:
        """Utility to generate text from the configured provider with retry logic."""
        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            try:
                if self.provider == "gemini":
                    response = self.client.models.generate_content(model=self.model, contents=prompt)
                    return response.text
                elif self.provider == "replicate":
                    output = replicate.run(
                        self.model,
                        input={
                            "prompt": prompt,
                            "max_new_tokens": 4096,
                        }
                    )
                    return "".join(output)
            except Exception as e:
                # Check if it's a rate limit error (429)
                is_rate_limit = False
                if self.provider == "replicate" and isinstance(e, ReplicateError):
                    if "429" in str(e) or "throttled" in str(e).lower():
                        is_rate_limit = True
                
                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"Rate limited by Replicate. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                
                # If not a rate limit or we've exhausted retries, re-raise
                raise e
        return ""

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

        # Use LLM to determine optimal strategy
        prompt = self._build_strategy_prompt(channel_config, topic)
        logger.debug("Strategy prompt:\n%s", prompt)
        
        response_text = self._generate_text(prompt)
        logger.debug("Strategy raw response:\n%s", response_text)

        # Parse strategy from response
        strategy = self._parse_strategy_response(response_text, topic)

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
        response_text = self._generate_text(prompt)
        logger.debug("Topic discovery raw response:\n%s", response_text)
        return response_text.strip().strip('"').strip("'")

    def _build_strategy_prompt(self, channel_config: ChannelConfig, topic: str) -> str:
        """Build prompt for strategy determination."""
        return f"""You are a world-class Instagram growth strategist who is an expert at creating content that sparks conversation.
Your primary goal is to develop a "spiky point of view" for each post that will make people stop, think, and engage. Avoid generic, boring content at all costs.

**Channel Context:**
- Theme: {channel_config.theme}
- Target Audience: {channel_config.target_audience}
- Cultural Context: {channel_config.cultural_context}
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
        Parse LLM's strategy response into ContentStrategy model.

        Args:
            response_text: Raw response from LLM
            topic: Topic being planned

        Returns:
            ContentStrategy instance
        """
        if not response_text:
            return self._get_default_strategy(topic)

        # 1. Try to find content within markdown code blocks
        import re
        data = None
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Try to find anything that looks like a JSON object
        if not data:
            json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

        # 3. Last ditch: clean the whole string
        if not data:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse strategy JSON: {response_text[:200]}...")
                return self._get_default_strategy(topic)

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
            reasoning=data.get("reasoning"),
        )

    def _get_default_strategy(self, topic: str) -> ContentStrategy:
        """Return a fallback strategy if LLM fails."""
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
