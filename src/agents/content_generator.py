"""
Content Generator Agent - Creates captions, hashtags, and slide text.
"""
import json
import logging
import time
from pathlib import Path
from typing import List, Optional, Any
from google import genai
import replicate
from groq import Groq
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
        elif self.provider == "groq":
            self.client = Groq(api_key=settings.groq_api_key)
            self.model = settings.groq_model
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _clean_ai_response(self, text: str) -> str:
        """Strip <think> blocks and other AI artifacts."""
        if not text:
            return ""
        # Remove <think>...</think> blocks
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return text.strip()

    def _generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Utility to generate text from the configured provider with retry logic and system instructions."""
        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            try:
                raw_response = ""
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
                    raw_response = response.text
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
                    raw_response = "".join(output)
                elif self.provider == "groq":
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})
                    
                    completion = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=4096,
                    )
                    raw_response = completion.choices[0].message.content
                
                return self._clean_ai_response(raw_response)

            except Exception as e:
                # Check if it's a rate limit error (429)
                is_rate_limit = False
                error_msg = str(e).lower()
                
                if self.provider == "replicate" and isinstance(e, ReplicateError):
                    if "429" in error_msg or "throttled" in error_msg:
                        is_rate_limit = True
                elif self.provider == "gemini":
                    if "429" in error_msg or "resource_exhausted" in error_msg:
                        is_rate_limit = True
                elif self.provider == "groq":
                    if "429" in error_msg or "rate_limit" in error_msg:
                        is_rate_limit = True
                
                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logging.getLogger(__name__).warning(f"Rate limited by {self.provider}. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
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
        self, strategy: ContentStrategy, channel_config: ChannelConfig, raw_output_dir: Optional[Path] = None
    ) -> GeneratedContent:
        """Generate all text content for a post."""

        system_prompt = f"""You are the '{channel_config.name}' content team executing the strategy brief below.
Mission: {channel_config.brand_mission or channel_config.theme}
Tone: {channel_config.tone}
Audience: {channel_config.target_audience}"""

        # 1. GROUND RULES FIRST (TOP OF PROMPT)
        master_brief = f"""### GROUND RULES (NON-NEGOTIABLE):
1. Every number must come from a named authoritative report.
2. If you cannot verify a figure, do not include it. Write "data unavailable".
3. Appending a source label to an unverified number is a CRITICAL FAILURE.
4. The `text_overlay` must contain ONLY the final words for the slide. No meta-labels.

### LOCALIZATION MANDATE:
- If the cultural context mentions India, you MUST use Indian Rupees (INR or ₹) and Indian units (Lakh, Crore). 
- NEVER use USD or Millions/Billions for Indian topics. This is a critical brand rule.

### THE STRATEGY BRIEF:
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Visual Theme: {strategy.visual_metaphor}
- Carousel Length: {strategy.carousel_length}

### THE TASK:
Create exactly {strategy.carousel_length} slides that tell a complete, visceral story.
1. **The Hook (Slide 1):** 
   - **Explicit Subject (MANDATORY):** You MUST name the core topic using its actual name (e.g. "Infertility", "Side Hustles", "GDP"). You are FORBIDDEN from using vague metaphors like "biological future" or "the dream". The user must know exactly what the case is in 0.5 seconds.
   - **Flexible Style:** Choose the style that fits. Use **Direct Style** (e.g. "Top 5 Luxury Brands") or **Teaser Style** (e.g. "Why Infertility is rising in India").
   - **ZERO NUMBERS (FORBIDDEN):** You are strictly forbidden from using any specific numbers or percentages on Slide 1. Save the math for the swipe.
2. **The Journey:** Take the reader from the Hook to a high-impact realization.
3. **The Human Anchor Rule:** NEVER list raw numbers alone. Every "Trillion", "Crore", or "%" must be compared to something human (e.g. "4 in 10 colleagues" instead of "40%", "Enough to fill 3 pools" instead of "200k tons").
4. **Value Density:** Name every item in a list. Teach something specific.
5. **No Citations in Overlay:** The `text_overlay` MUST be clean and punchy. No meta-labels.

4. **Visual Choice:** Select the Template and Background Style based on these strict logical rules:
   - `standard`: The default choice. Use for narrative sentences.
   - `big_fact`: Use ONLY for a single, high-impact statistic or a powerful punchline.
   - `split_comparison`: Use for comparing items or lists.
   - `cta`: Use ONLY for the final action slide.
   - **Dual-Size Text (NEW):** If you want a massive headline and smaller sub-text on the same slide, separate them with `---` (e.g., "75% --- of users prefer X").
   - **Background Strategy:** Use `blurred_hook` for at least 50% of the slides to maintain a cohesive high-end brand feel.
"""

        # Generate components using the consolidated master brief
        slides = self._generate_slides(strategy, channel_config, system_prompt, master_brief, raw_output_dir)
        caption = self._generate_caption(strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir)
        hashtags = self._generate_hashtags(strategy, channel_config, system_prompt, master_brief, raw_output_dir)
        cta = self._generate_smart_cta(strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir)
        
        return GeneratedContent(
            caption=caption,
            hashtags=hashtags,
            call_to_action=cta,
            slides=slides,
        )

    def _generate_slides(
        self, strategy: ContentStrategy, channel_config: ChannelConfig, system_prompt: str, master_brief: str, raw_output_dir: Optional[Path] = None
    ) -> List[CarouselSlide]:
        """Generate slides."""
        prompt = f"""{master_brief}

**Slide Breakdown:**
- Slide 1: HOOK - Selection: AI image generation.
- Slides 2-{strategy.carousel_length - 1}: CONTENT - Deliver the core data and narrative.
- Slide {strategy.carousel_length}: CTA - Final action.

**Template Selection Rules (CRITICAL - READ CAREFULLY):**

Choose template_name based on content type:

1. **standard** - Use for: Regular sentences, explanations, multi-line content
   - Character limit: 100 characters MAX
   - Best for: Insights, explanations, context
   - Example: "This is why compound interest beats active trading"

2. **big_fact** - Use for: ONLY single big numbers or stats
   - Character limit: 60 characters MAX
   - Best for: Shocking statistics, large numbers
   - Example: "₹2.5 Crore" or "78% fail within 2 years"
   - DO NOT use for: Full sentences or explanations

3. **cta** - Use for: ONLY the final call-to-action slide
   - Character limit: 80 characters MAX
   - Best for: Engagement prompts
   - Example: "Save this for later" or "Follow for daily insights"

**Background Style Rules:**

- **"solid"** - Default, use for most slides
- **"gradient"** - Use sparingly (1-2 slides) for visual variety
- **"blurred_hook"** - Use ONLY for slides 2-3 to create continuity from slide 1

**TEXT LENGTH ENFORCEMENT:**
Before assigning a template, COUNT THE CHARACTERS in text_overlay.
- If > 100 chars → MUST shorten text or use standard template
- If > 60 chars → CANNOT use big_fact template
- Unreadable text = rejected post

**Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "text_overlay": "Short punchy hook (max 80 chars)",
      "image_prompt": "Literal scene description (objects, positions, no abstract concepts)",
      "template_name": "standard",
      "background_style": "solid"
    }},
    {{
      "slide_number": 2,
      "purpose": "content",
      "text_overlay": "First insight (max 100 if standard, 60 if big_fact)",
      "image_prompt": "Not used for template slides",
      "template_name": "standard",
      "background_style": "blurred_hook"
    }}
  ]
}}
Respond with ONLY JSON.
"""

        if raw_output_dir:
            try:
                with open(raw_output_dir / "slides_PROMPT.txt", "w") as f:
                    f.write(f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}")
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to save slides prompt: {e}")

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        
        if raw_output_dir:
            raw_path = raw_output_dir / "slides.txt"
            with open(raw_path, "w") as f:
                f.write(response_text)
        
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
        master_brief: str,
        raw_output_dir: Optional[Path] = None,
    ) -> str:
        """Generate Instagram caption."""
        prompt = f"""{master_brief}

### TASK:
Write an engaging Instagram caption for this post.
1. **Hook**: Start with a strong line reflecting the Angle.
2. **Value**: Briefly explain the value of this insight.
3. **Length**: 150-300 characters.
4. **No Hashtags**.

Write the caption now:
"""

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        
        if raw_output_dir:
            raw_path = raw_output_dir / "caption.txt"
            with open(raw_path, "w") as f:
                f.write(response_text)
            
        return response_text.strip()

    def _generate_hashtags(
        self, strategy: ContentStrategy, channel_config: ChannelConfig, system_prompt: str, master_brief: str, raw_output_dir: Optional[Path] = None
    ) -> List[str]:
        """Generate relevant hashtags."""
        prompt = f"""{master_brief}

### TASK:
Generate 20-25 relevant hashtags for this post.
Respond with ONLY JSON: {{"hashtags": ["list"]}}
"""

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        
        if raw_output_dir:
            raw_path = raw_output_dir / "hashtags.txt"
            with open(raw_path, "w") as f:
                f.write(response_text)
            
        hashtags_data = self._parse_json_response(response_text)

        return ["#" + tag.lstrip("#") for tag in hashtags_data.get("hashtags", [])]

    def _generate_smart_cta(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
        system_prompt: str,
        master_brief: str,
        raw_output_dir: Optional[Path] = None,
    ) -> str:
        """Generate a content-specific, engaging CTA."""
        prompt = f"""{master_brief}

### TASK:
Write a single, compelling, open-ended question that directly relates to the post's content to encourage comments.
Respond with ONLY the CTA text.
"""
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        
        if raw_output_dir:
            raw_path = raw_output_dir / "cta.txt"
            with open(raw_path, "w") as f:
                f.write(response_text)
            
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
