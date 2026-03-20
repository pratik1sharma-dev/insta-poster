"""
Content Generator Agent - Creates captions, hashtags, and slide text.
"""
import json
import logging
import time
from typing import List, Optional
from google import genai
import replicate
from replicate.exceptions import ReplicateError
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
        """Initialize the Content Generator with the requested provider."""
        self.provider = settings.llm_provider.lower()
        
        if self.provider == "gemini":
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model = settings.gemini_generator_model
        elif self.provider == "replicate":
            self.model = settings.replicate_llm_model
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Utility to generate text from the configured provider with retry logic and system instructions."""
        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            try:
                if self.provider == "gemini":
                    from google.genai import types
                    config = None
                    if system_prompt:
                        config = types.GenerateContentConfig(system_instruction=system_prompt)
                    
                    response = self.client.models.generate_content(
                        model=self.model, 
                        contents=prompt,
                        config=config
                    )
                    return response.text
                elif self.provider == "replicate":
                    input_data = {
                        "prompt": prompt,
                        "max_new_tokens": 4096,
                    }
                    if system_prompt:
                        input_data["system_prompt"] = system_prompt
                        
                    output = replicate.run(
                        self.model,
                        input=input_data
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
- Cultural Context: {channel_config.cultural_context}
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
        system_prompt = f"""You are an expert Instagram content creator.
Your goal is to create engaging, saveable content that grows followers and encourages interactions.

Channel: {channel_config.theme}
Tone: {channel_config.tone}
Audience: {channel_config.target_audience}
Cultural Context: {channel_config.cultural_context}

ALWAYS maintain a consistent voice and follow the strategic angle provided."""

        # Generate slides with text overlays
        slides = self._generate_slides(strategy, channel_config, system_prompt)

        # Generate caption
        caption = self._generate_caption(strategy, channel_config, slides, system_prompt)

        # Generate hashtags
        hashtags = self._generate_hashtags(strategy, channel_config, system_prompt)

        # Generate call-to-action
        cta = self._generate_smart_cta(strategy, channel_config, slides, system_prompt)

        return GeneratedContent(
            caption=caption,
            hashtags=hashtags,
            call_to_action=cta,
            slides=slides,
        )

    def _generate_slides(
        self, strategy: ContentStrategy, channel_config: ChannelConfig, system_prompt: str
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
You are the Creative Director and Lead Researcher. Your goal is to create a 6-10 slide carousel that tells a complete, high-value story.

**The "Master Brief" for this Post:**
1. **The Journey:** Use the Visual Metaphor ({strategy.visual_metaphor}) to take the reader from a curiosity-driven Hook to a high-impact conclusion.
2. **Value Density (CRITICAL):** Do not be vague. Use your internal knowledge to provide specific names, numbers, and facts. If the topic is "The Top 5...", name all 5. Every slide must teach the reader something they didn't know.
3. **The Balance:** Balance the storytelling (narrative flow) with the raw information. The slides should feel connected, like turning the pages of a well-researched book.
4. **Visual Choice:** You have full judge-like authority to select the **Template** and **Background Style** that best delivers the message of each slide.

**Formatting Rules:**
- `big_fact`: Use `KEY STAT: Brief context` (The part before the colon is massive).
- `split_comparison`: Use `A vs B`.
- `standard`: Conversational sentences under 15 words.

**Guidelines:**
- Be punchy and professional.
- Reference the visual metaphor in your writing.
- Every slide must reinforce the Angle: "{strategy.angle}".

**Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "text_overlay": "The hook text",
      "image_prompt": "Detailed AI art prompt",
      "template_name": "standard",
      "background_style": "solid"
    }},
    ...
  ]
}}

Respond with ONLY the JSON, no other text.
"""

        logger.debug("Slides prompt:\n%s", prompt)
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        logger.debug("Slides raw response:\n%s", response_text)
        
        # Save raw response for debugging if it seems empty or short
        if not response_text or len(response_text) < 100:
            logger.warning(f"Short or empty response from LLM: {response_text}")

        slides_data = self._parse_json_response(response_text)

        purpose_map = {
            "hook": "hook",
            "intro": "intro",
            "introduction": "intro",
            "content": "content",
            "journey": "journey",
            "climax": "climax",
            "resolution": "resolution",
            "conclusion": "conclusion",
            "cta": "cta",
            "call-to-action": "cta",
            "call_to_action": "cta",
        }

        slides = []
        for slide_data in slides_data.get("slides", []):
            purpose_raw = str(slide_data.get("purpose", "")).strip().lower()

            # Normalize common variants
            if purpose_raw in purpose_map:
                purpose = purpose_map[purpose_raw]
            elif "hook" in purpose_raw:
                purpose = "hook"
            elif "intro" in purpose_raw:
                purpose = "intro"
            elif "content" in purpose_raw:
                purpose = "content"
            elif "cta" in purpose_raw or "action" in purpose_raw:
                purpose = "cta"
            elif "climax" in purpose_raw or "aha" in purpose_raw:
                purpose = "climax"
            else:
                # Default to content if we really don't know
                purpose = "content"
            slides.append(
                CarouselSlide(
                    slide_number=slide_data["slide_number"],
                    purpose=SlidePurpose(purpose),
                    text_overlay=slide_data["text_overlay"],
                    image_prompt=slide_data["image_prompt"],
                    template_name=slide_data.get("template_name", "standard"),
                    background_style=slide_data.get("background_style", "solid"),
                    design_notes=slide_data.get("design_notes"),
                )
            )

        return slides

    def _generate_caption(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
        system_prompt: str,
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
- Cultural Context: {channel_config.cultural_context}
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
- If the Cultural Context is provided, use relevant examples, analogies, or phrases to make the content more relatable.

Write the caption now (no JSON, just the caption text):
"""

        logger.debug("Caption prompt:\n%s", prompt)
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        logger.debug("Caption raw response:\n%s", response_text)
        return response_text.strip()

    def _generate_hashtags(
        self, strategy: ContentStrategy, channel_config: ChannelConfig, system_prompt: str
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
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        logger.debug("Hashtags raw response:\n%s", response_text)
        hashtags_data = self._parse_json_response(response_text)

        return ["#" + tag.lstrip("#") for tag in hashtags_data.get("hashtags", [])]

    def _generate_smart_cta(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
        system_prompt: str,
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
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        return response_text.strip()

    def _parse_json_response(self, response_text: str) -> dict:
        """
        Parse JSON from LLM response.
        Handles markdown blocks and tries to find JSON even if surrounded by text.

        Args:
            response_text: Raw response text

        Returns:
            Parsed JSON dictionary
        """
        if not response_text:
            return {}

        # 1. Try to find content within markdown code blocks
        import re
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Try to find anything that looks like a JSON object
        json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Last ditch: clean the whole string
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from response: {response_text[:200]}...")
            return {}
