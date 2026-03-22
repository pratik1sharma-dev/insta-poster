"""
Content Generator Agent - Creates captions, hashtags, and slide text.
"""
import json
import logging
import time
import re
from pathlib import Path
from typing import List, Optional, Any
from google import genai
import replicate
from groq import Groq
from replicate.exceptions import ReplicateError
from src.models import (
    CarouselSlide, 
    GeneratedContent, 
    ContentStrategy, 
    ChannelConfig,
    SlidePurpose
)
from src.config import settings

logger = logging.getLogger(__name__)

class ContentGenerator:
    """AI agent that generates written content for Instagram posts."""

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
        if not text: return ""
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
                    response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
                    raw_response = response.text
                elif self.provider == "replicate":
                    input_data = {"prompt": prompt, "max_new_tokens": 4096}
                    if system_prompt: input_data["system_prompt"] = system_prompt
                    output = replicate.run(self.model, input=input_data)
                    raw_response = "".join(output)
                elif self.provider == "groq":
                    messages = []
                    if system_prompt: messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})
                    completion = self.client.chat.completions.create(model=self.model, messages=messages, temperature=0.7, max_tokens=4096)
                    raw_response = completion.choices[0].message.content
                return self._clean_ai_response(raw_response)
            except Exception as e:
                is_rate_limit = False
                error_msg = str(e).lower()
                if self.provider == "replicate" and isinstance(e, ReplicateError):
                    if "429" in error_msg or "throttled" in error_msg: is_rate_limit = True
                elif self.provider == "gemini" and ("429" in error_msg or "resource_exhausted" in error_msg): is_rate_limit = True
                elif self.provider == "groq" and ("429" in error_msg or "rate_limit" in error_msg): is_rate_limit = True
                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logging.getLogger(__name__).warning(f"Rate limited by {self.provider}. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                raise e
        return ""

    def _build_session_brief(self, strategy: ContentStrategy, channel_config: ChannelConfig) -> str:
        """Shared high-level brief for this specific Instagram carousel post."""
        return f"""You are a High-Performance Viral Content Specialist for '{channel_config.name}'.
Goal: Transform data into visceral, scroll-stopping realizations.

### YOUR WRITING STYLE:
- **Spoken Out Loud Rule:** Every text overlay MUST read like something a person would say to a friend. No textbook "Chapter Titles."
- **Anticipation Mandate:** Every slide text should make the reader *feel* an emotion or want to know what comes next instantly.
- **Pattern Interrupt:** Use the `---` separator on nearly every slide to create a massive bold headline and smaller sub-text. 

Channel Context:
- Theme: {channel_config.theme}
- Mission: {channel_config.brand_mission}
- Audience: {channel_config.target_audience}
- Cultural Context: {channel_config.cultural_context}

Post Details:
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Character Persona: {strategy.character_persona or "N/A"}
"""

    def generate_content(self, strategy: ContentStrategy, channel_config: ChannelConfig, raw_output_dir: Optional[Path] = None) -> GeneratedContent:
        """Generate all text content for a post."""
        system_prompt = self._build_session_brief(strategy, channel_config)
        
        master_brief = f"""### GROUND RULES (NON-NEGOTIABLE):
1. Every number must come from a named authoritative report.
2. If you cannot verify a figure, do not include it. Write "data unavailable".
3. The `text_overlay` MUST contain ONLY the final words. No meta-labels.
4. **NO CITATIONS:** DO NOT include source citations (e.g. "Source: Brand Finance") in the text overlay. Keep the slides clean.
5. **NO SPOILERS:** Slide 1 MUST name the topic clearly but is FORBIDDEN from using numbers or answers. Save the "payoff" for the swipe.
6. **LOCALIZATION:** Use INR/₹ and Lakh/Crore for Indian topics. NEVER use USD or Millions/Billions.
7. **PATTERN INTERRUPT:** Use `---` to separate Massive Headline from Body Text on nearly every slide. 
   - **STRICT RULE:** You are FORBIDDEN from starting a slide with `---`. There must always be a headline above it.

### THE TASK:
Create exactly {strategy.carousel_length} slides telling a visceral story.
- Slide 1: HOOK (Explicit Subject, Zero Numbers).
- Slides 2-{strategy.carousel_length - 1}: CONTENT (Human Anchors, Precision Math: Ratios must add up to 100%).
- Slide {strategy.carousel_length}: CTA (Clear, actionable prompt).
"""
        slides = self._generate_slides(strategy, channel_config, system_prompt, master_brief, raw_output_dir)
        caption = self._generate_caption(strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir)
        hashtags = self._generate_hashtags(strategy, channel_config, system_prompt, master_brief, raw_output_dir)
        cta = self._generate_smart_cta(strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir)
        return GeneratedContent(caption=caption, hashtags=hashtags, call_to_action=cta, slides=slides)

    def _generate_slides(self, strategy, channel_config, system_prompt, master_brief, raw_output_dir) -> List[CarouselSlide]:
        """Generate slide content."""
        style_context = f"Visual Metaphor: {strategy.visual_metaphor}\nPalette: {strategy.color_palette}\nTypography: {strategy.typography_style}"
        
        prompt = f"""{master_brief}

**Visual Context:**
{style_context}

**Template Selection Rules:**
1. **standard** - Default for narratives. Use for character-driven story slides.
2. **big_fact** - ONLY for single big numbers or punchlines.
3. **split_comparison** - For direct comparisons.
4. **cta** - ONLY for the final slide.

**Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "text_overlay": "String (NO NUMBERS)",
      "image_prompt": "Literal scene description (mood, lighting, objects)",
      "template_name": "standard",
      "background_style": "solid"
    }},
    ...
  ]
}}
Respond with ONLY JSON matching the CarouselSlide model.
"""
        if raw_output_dir:
            try:
                with open(raw_output_dir / "slides_PROMPT.txt", "w") as f:
                    f.write(f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}")
            except Exception: pass

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        if raw_output_dir:
            try:
                with open(raw_output_dir / "slides.txt", "w") as f: f.write(response_text)
            except Exception: pass
        
        slides_data = self._parse_json_response(response_text)
        purpose_map = {
            "hook": SlidePurpose.HOOK, "intro": SlidePurpose.HOOK, "introduction": SlidePurpose.HOOK,
            "cta": SlidePurpose.CTA, "action": SlidePurpose.CTA, "conclusion": SlidePurpose.CTA, "call-to-action": SlidePurpose.CTA
        }
        
        slides = []
        for i, slide_data in enumerate(slides_data.get("slides", []), 1):
            purpose_raw = str(slide_data.get("purpose", "")).lower()
            purpose = purpose_map.get(purpose_raw, SlidePurpose.CONTENT)
            slide_num = slide_data.get("slide_number") or i
            
            slides.append(CarouselSlide(
                slide_number=int(slide_num),
                purpose=purpose,
                text_overlay=slide_data.get("text_overlay", ""),
                image_prompt=slide_data.get("image_prompt", ""),
                template_name=slide_data.get("template_name", "standard"),
                background_style=slide_data.get("background_style", "solid"),
                design_notes=slide_data.get("design_notes")
            ))
        return slides

    def _generate_caption(self, strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir):
        """Generate Instagram caption."""
        prompt = f"{master_brief}\n\nBased on the slides, write a high-converting 150-300 char Instagram caption. No hashtags. Include a driving question. STRICTOR: Stay under 300 characters."
        return self._generate_text(prompt, system_prompt=system_prompt)

    def _generate_hashtags(self, strategy, channel_config, system_prompt, master_brief, raw_output_dir):
        """Generate hashtags."""
        prompt = f"{master_brief}\n\nGenerate 20-25 high-reach Indian hashtags for this topic."
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        tags = re.findall(r'#\w+', response_text)
        if not tags:
            tags = ["#" + tag.strip().lstrip('#') for tag in response_text.replace(',', ' ').split() if tag.strip()]
        return tags[:30]

    def _generate_smart_cta(self, strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir):
        """Generate final CTA text."""
        return "Save this post if you found it valuable."

    def _parse_json_response(self, response_text: str) -> dict:
        """Robust JSON parsing helper."""
        try:
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if json_match: return json.loads(json_match.group(1))
            json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
            if json_match: return json.loads(json_match.group(1))
            return json.loads(response_text)
        except Exception:
            logger.error(f"Failed to parse JSON: {response_text[:200]}")
            return {"slides": []}
