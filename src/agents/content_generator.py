"""
Content Generator Agent - Creates slide text, captions, hashtags, and CTAs.
"""
import json
import logging
import time
import re
from pathlib import Path
from typing import List, Optional
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


# ---------------------------------------------------------------------------
# Default copy voice examples — override per channel via
# ChannelConfig.copy_voice_examples
# ---------------------------------------------------------------------------
_DEFAULT_COPY_VOICE_EXAMPLES = """
### COPY VOICE — WHAT GOOD LOOKS LIKE:

WRONG (textbook headline): "Key Milestones in Renewable Energy Growth"
RIGHT (spoken out loud):   "The world just spent $2.3 trillion on clean energy. Emissions still went up. Let that sink in."

WRONG (data dump):  "Solar capacity grew 20% in 2023."
RIGHT (human anchor): "India is building solar faster than almost any country on earth. Your electricity bill doesn't reflect that yet. Here's why."

WRONG (vague concept): "Sunk cost fallacy affects decision-making."
RIGHT (realization):   "The more you invest in something, the harder your brain fights to keep you there. Even when leaving is the only logical move."

WRONG (generic CTA): "Like and follow for more content."
RIGHT (specific):    "What's one belief you held for years before realising it was costing you?"

The test: read each slide out loud to a friend. If it sounds like a
textbook chapter title or a LinkedIn post — rewrite it.
"""

# ---------------------------------------------------------------------------
# Slide output format instructions per template
# ---------------------------------------------------------------------------
_SLIDE_FORMAT_GUIDE = """
### STRUCTURED SLIDE FIELDS:

Each slide JSON object must include these fields based on its template:

**standard** (narrative slides):
{
  "slide_number": N,
  "purpose": "content",
  "template_name": "standard",
  "background_style": "solid | gradient | blurred_hook",
  "headline": "The bold top line — 8 words max",
  "subtext": "The supporting explanation — 1-2 sentences",
  "text_overlay": "headline + subtext combined as one string",
  "image_prompt": "Literal scene description"
}

**big_fact** (single punchline number or bold statement):
{
  "slide_number": N,
  "purpose": "content",
  "template_name": "big_fact",
  "background_style": "blurred_hook",
  "pre_label": "Small label above the number e.g. 'Every year' or 'By 2030'",
  "headline": "THE BIG NUMBER OR STATEMENT e.g. '₹2.3 Crore'",
  "subtext": "What this number means in plain language",
  "text_overlay": "pre_label + headline + subtext combined",
  "image_prompt": "Literal scene description"
}

**split_comparison** (two-sided comparison):
{
  "slide_number": N,
  "purpose": "content",
  "template_name": "split_comparison",
  "background_style": "solid | blurred_hook",
  "headline": "The framing question or context e.g. 'Which actually grows faster?'",
  "left_content": "Label|Value|Short description (pipe-separated)",
  "right_content": "Label|Value|Short description (pipe-separated)",
  "text_overlay": "headline + left + right combined as readable string",
  "image_prompt": "Literal scene description"
}

Example left_content: "SIP at 25|₹2.3 Crore|by retirement"
Example right_content: "SIP at 35|₹67 Lakh|same monthly amount"

**cta** (final slide only):
{
  "slide_number": N,
  "purpose": "cta",
  "template_name": "cta",
  "background_style": "blurred_hook",
  "headline": "The engagement question — make it personal and specific",
  "subtext": "Optional one-line supporting context",
  "action_text": "Short button label e.g. 'Drop your answer' or 'Comment below'",
  "text_overlay": "headline + subtext combined",
  "image_prompt": "Literal scene description"
}

RULES:
- headline is always short and punchy (8 words max for standard/big_fact, question format for cta)
- subtext carries the detail and explanation
- text_overlay is always the full readable combination of all text fields
- left_content and right_content use pipe | as separator: "Label|Value|Description"
- action_text for cta must be 3-5 words max (it renders as a button)
- image_prompt describes a pure visual scene — no text, no charts, no abstract concepts
"""


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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_content(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        raw_output_dir: Optional[Path] = None,
    ) -> GeneratedContent:
        """
        Generate all text content for a post.

        Args:
            strategy:        Content strategy. strategy.verified_data carries
                             real figures from the research step.
            channel_config:  Channel configuration.
            raw_output_dir:  If set, saves raw prompts and responses for debugging.

        Returns:
            GeneratedContent with caption, hashtags, slides, and CTA.
        """
        system_prompt = self._build_generator_system_prompt(channel_config)
        master_brief = self._build_master_brief(strategy, channel_config)

        slides = self._generate_slides(
            strategy, channel_config, system_prompt, master_brief, raw_output_dir
        )
        caption = self._generate_caption(
            strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir
        )
        hashtags = self._generate_hashtags(
            strategy, channel_config, system_prompt, master_brief, raw_output_dir
        )
        cta = self._generate_smart_cta(
            strategy, channel_config, slides, system_prompt, master_brief, raw_output_dir
        )

        return GeneratedContent(
            caption=caption,
            hashtags=hashtags,
            call_to_action=cta,
            slides=slides,
        )

    # ------------------------------------------------------------------
    # System prompt & master brief
    # ------------------------------------------------------------------

    def _build_generator_system_prompt(self, channel_config: ChannelConfig) -> str:
        """Build the system prompt using channel persona if defined."""
        if channel_config.content_team_persona:
            persona = channel_config.content_team_persona
        else:
            persona = (
                f"You are the '{channel_config.name}' content team "
                f"executing the strategy brief below.\n"
                f"Tone: {channel_config.tone}\n"
                f"Audience: {channel_config.target_audience}"
            )

        return (
            f"{persona}\n\n"
            "Your single goal: transform data and ideas into carousel slides "
            "that make a stranger stop scrolling at 11 PM and read every word."
        )

    def _build_master_brief(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
    ) -> str:
        """
        Build the master brief injected into every generation call.
        Contains ground rules, verified data, localization, copy voice,
        and post context.
        """

        # Verified data block — prevents fabrication
        # Truncate to ~2000 chars to stay within Groq TPM limits (model cap ~6000 tokens/request)
        if strategy.verified_data:
            verified_data_trimmed = strategy.verified_data[:2000]
            if len(strategy.verified_data) > 2000:
                verified_data_trimmed += "\n[... truncated for brevity ...]"
            data_block = (
                "### VERIFIED DATA (use ONLY these figures — no others):\n"
                f"{verified_data_trimmed}\n\n"
                "If a slide needs a number not in this list, write the "
                "insight without a figure rather than inventing one."
            )
        else:
            data_block = (
                "### VERIFIED DATA:\n"
                "No pre-verified data provided. Do NOT invent statistics. "
                "Write insights without quoting figures you cannot verify."
            )

        # Localization
        if channel_config.localization_type == "india":
            localization_note = (
                "LOCALIZATION: Use INR/₹ and Lakh/Crore for all figures. "
                "Never use USD or Millions/Billions."
            )
        else:
            localization_note = (
                "LOCALIZATION: Global topic. Never convert USD to INR. "
                "Reference India only where a verified India-specific data "
                "point exists in the data block above."
            )

        # Copy voice examples
        copy_voice = (
            channel_config.copy_voice_examples
            if channel_config.copy_voice_examples
            else _DEFAULT_COPY_VOICE_EXAMPLES
        )

        # Character persona (optional)
        persona_line = ""
        if hasattr(strategy, "character_persona") and strategy.character_persona:
            persona_line = f"- Character Persona: {strategy.character_persona}\n"

        return f"""### GROUND RULES (NON-NEGOTIABLE):
1. Every number must come ONLY from the VERIFIED DATA block below.
2. If you cannot verify a figure, write the insight without a number.
3. Appending a source label to an unverified number is a CRITICAL FAILURE.
4. **NO CITATIONS:** DO NOT include source citations (e.g. "Source: Brand Finance") in the text overlay. Keep the slides clean.
5. Slide 1 MUST name the topic clearly but is FORBIDDEN from using numbers or answers.
6. Write complete, logical thoughts — not forced headlines or marketing slogans.

{data_block}

{localization_note}

{copy_voice}

### POST CONTEXT:
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Hook Type: {strategy.hook_type}
- Visual Theme: {strategy.visual_metaphor}
- Color Palette: {strategy.color_palette}
- Typography: {strategy.typography_style}
- Audience Insight: {strategy.target_audience_insight}
{persona_line}
### CHANNEL CONTEXT:
- Theme: {channel_config.theme}
- Mission: {getattr(channel_config, 'brand_mission', '') or channel_config.theme}
- Audience: {channel_config.target_audience}
- Cultural Context: {channel_config.cultural_context or 'None'}
"""

    # ------------------------------------------------------------------
    # Slide generation
    # ------------------------------------------------------------------

    def _generate_slides(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        system_prompt: str,
        master_brief: str,
        raw_output_dir: Optional[Path],
    ) -> List[CarouselSlide]:
        """Generate structured slide content."""

        prompt = f"""{master_brief}

### THE TASK:
Create exactly {strategy.carousel_length} slides that tell a complete,
high-value story.

**Slide Breakdown:**
- Slide 1: HOOK — Name the topic. Create curiosity. Zero numbers.
  Meet the reader where they are — assume they know nothing yet.
  Use template: standard, background: solid
- Slides 2–{strategy.carousel_length - 1}: CONTENT — Build the story
  using only the verified data. Each slide teaches something specific.
  Mix templates: use big_fact for punchline numbers, split_comparison
  for direct comparisons, standard for narrative slides.
  Use blurred_hook background for at least 2 content slides.
- Slide {strategy.carousel_length}: CTA — One specific engagement question.
  Use template: cta, background: blurred_hook

**Emotional Arc (follow this order):**
1. Shock or surprise — slides 1–2
2. Understanding, here is why — slides 3–4
3. Concern or realization — slides 5–6
4. Agency, what to do about it — slide {strategy.carousel_length - 1}
5. Action — slide {strategy.carousel_length}

{_SLIDE_FORMAT_GUIDE}

**Full Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "template_name": "standard",
      "background_style": "solid",
      "headline": "...",
      "subtext": "...",
      "text_overlay": "...",
      "image_prompt": "..."
    }},
    ...
  ]
}}

Respond with ONLY valid JSON. No markdown fences, no explanation."""

        self._save_debug_file(
            raw_output_dir,
            "slides_PROMPT.txt",
            f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}",
        )

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        self._save_debug_file(raw_output_dir, "slides.txt", response_text)

        if not response_text or len(response_text) < 100:
            logger.warning("Short or empty response from LLM: %s", response_text)

        slides_data = self._parse_json_response(response_text)
        return self._parse_slides(slides_data)

    def _parse_slides(self, slides_data: dict) -> List[CarouselSlide]:
        """Normalise raw slide dicts into CarouselSlide objects."""
        purpose_map = {
            "hook": SlidePurpose.HOOK,
            "intro": SlidePurpose.HOOK,
            "introduction": SlidePurpose.HOOK,
            "cta": SlidePurpose.CTA,
            "action": SlidePurpose.CTA,
            "conclusion": SlidePurpose.CTA,
            "call-to-action": SlidePurpose.CTA,
            "call_to_action": SlidePurpose.CTA,
        }

        slides = []
        for i, slide_data in enumerate(slides_data.get("slides", []), 1):
            purpose_raw = str(slide_data.get("purpose", "")).strip().lower()
            purpose = purpose_map.get(purpose_raw, SlidePurpose.CONTENT)
            slide_num = slide_data.get("slide_number") or i

            # Build text_overlay fallback if model didn't provide it
            text_overlay = slide_data.get("text_overlay", "")
            if not text_overlay:
                parts = [
                    slide_data.get("pre_label", ""),
                    slide_data.get("headline", ""),
                    slide_data.get("subtext", ""),
                ]
                text_overlay = "\n".join(p for p in parts if p).strip()

            slides.append(
                CarouselSlide(
                    slide_number=int(slide_num),
                    purpose=purpose,
                    text_overlay=text_overlay,
                    image_prompt=slide_data.get("image_prompt", ""),
                    template_name=slide_data.get("template_name", "standard"),
                    background_style=slide_data.get("background_style", "solid"),
                    headline=slide_data.get("headline"),
                    subtext=slide_data.get("subtext"),
                    pre_label=slide_data.get("pre_label"),
                    left_content=slide_data.get("left_content"),
                    right_content=slide_data.get("right_content"),
                    action_text=slide_data.get("action_text"),
                    design_notes=slide_data.get("design_notes"),
                )
            )

        return slides

    # ------------------------------------------------------------------
    # Caption
    # ------------------------------------------------------------------

    def _generate_caption(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
        system_prompt: str,
        master_brief: str,
        raw_output_dir: Optional[Path],
    ) -> str:
        """Generate Instagram caption."""
        slides_summary = "\n".join(
            f"Slide {s.slide_number}: {s.text_overlay}" for s in slides[:3]
        )

        prompt = f"""{master_brief}

Write an Instagram caption for this post.

First 3 slides for context:
{slides_summary}

Requirements:
1. Hook in first 125 characters — make it impossible to ignore.
2. One sentence on why this matters right now.
3. 150–300 characters total.
4. Use line breaks for readability.
5. 1–3 emojis maximum, only where they add meaning.
6. No hashtags.
7. Conversational and opinionated — not corporate.

Write only the caption text. No JSON."""

        self._save_debug_file(
            raw_output_dir, "caption_PROMPT.txt",
            f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}",
        )
        response = self._generate_text(prompt, system_prompt=system_prompt)
        self._save_debug_file(raw_output_dir, "caption.txt", response)
        return response.strip()

    # ------------------------------------------------------------------
    # Hashtags
    # ------------------------------------------------------------------

    def _generate_hashtags(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        system_prompt: str,
        master_brief: str,
        raw_output_dir: Optional[Path],
    ) -> List[str]:
        """Generate relevant hashtags."""
        prompt = f"""{master_brief}

Generate Instagram hashtags for this post.

Requirements:
- 20–25 hashtags total
- Mix: 3–5 large (500k+ posts), 8–10 medium (50k–500k), 7–10 niche (<50k)
- All must be directly relevant to the topic and channel
- No banned or spam hashtags
- For Indian channels, include relevant Indian community hashtags

Output Format (JSON):
{{"hashtags": ["hashtag1", "hashtag2"]}}

No # symbol in the list. Respond with ONLY JSON."""

        self._save_debug_file(
            raw_output_dir, "hashtags_PROMPT.txt",
            f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}",
        )
        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        self._save_debug_file(raw_output_dir, "hashtags.txt", response_text)

        hashtags_data = self._parse_json_response(response_text)
        if hashtags_data.get("hashtags"):
            return ["#" + tag.lstrip("#") for tag in hashtags_data["hashtags"]]

        # Fallback extraction
        tags = re.findall(r"#\w+", response_text)
        if not tags:
            tags = [
                "#" + tag.strip().lstrip("#")
                for tag in response_text.replace(",", " ").split()
                if tag.strip()
            ]
        return tags[:25]

    # ------------------------------------------------------------------
    # CTA
    # ------------------------------------------------------------------

    def _generate_smart_cta(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        slides: List[CarouselSlide],
        system_prompt: str,
        master_brief: str,
        raw_output_dir: Optional[Path],
    ) -> str:
        """Generate a content-specific, engaging CTA."""
        slides_summary = "\n".join(
            f"Slide {s.slide_number}: {s.text_overlay}" for s in slides
        )

        prompt = f"""{master_brief}

Write a single Call-to-Action for this Instagram post.

Post summary:
{slides_summary}

Rules:
- Never use: "like this post", "follow for more", "save this post",
  "share with a friend", "drop a comment"
- Write one open-ended question the reader wants to answer in comments
- Must relate directly to the post's specific content
- Under 20 words
- Feel like a friend asking, not a brand broadcasting

Good examples:
- "What's one belief you held for years before realising it was costing you?"
- "If you could move ₹10,000 into one investment today — what would it be?"
- "Which of these surprised you most? Drop the number below."
- "What would you do differently if you had read this 5 years ago?"

Write only the CTA text. No JSON."""

        self._save_debug_file(
            raw_output_dir, "cta_PROMPT.txt",
            f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}",
        )
        response = self._generate_text(prompt, system_prompt=system_prompt)
        self._save_debug_file(raw_output_dir, "cta.txt", response)
        return response.strip()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _clean_ai_response(self, text: str) -> str:
        """Strip <think> blocks and other model artifacts."""
        if not text:
            return ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()

    def _save_debug_file(
        self,
        output_dir: Optional[Path],
        filename: str,
        content: str,
    ) -> None:
        """Save debug file if output_dir is set. Silently ignores errors."""
        if not output_dir:
            return
        try:
            with open(output_dir / filename, "w") as f:
                f.write(content)
        except Exception:
            pass

    def _parse_json_response(self, response_text: str) -> dict:
        """Parse JSON from LLM response handling markdown and bare objects."""
        if not response_text:
            return {}

        # 1. Markdown code block
        json_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL
        )
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Bare JSON object
        json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Last resort — clean the whole string
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(
                "Failed to parse JSON from response: %s...", response_text[:200]
            )
            return {}

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------

    def _generate_text(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> str:
        """Generate text from the configured provider with retry logic."""
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                raw_response = ""

                if self.provider == "gemini":
                    from google.genai import types
                    config = None
                    if system_prompt:
                        config = types.GenerateContentConfig(
                            system_instruction=system_prompt
                        )
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=config,
                    )
                    raw_response = response.text

                elif self.provider == "replicate":
                    input_data = {"prompt": prompt, "max_new_tokens": 4096}
                    if system_prompt:
                        input_data["system_prompt"] = system_prompt
                    output = replicate.run(self.model, input=input_data)
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
                error_msg = str(e).lower()
                is_rate_limit = (
                    (self.provider == "replicate"
                     and isinstance(e, ReplicateError)
                     and ("429" in error_msg or "throttled" in error_msg))
                    or (self.provider == "gemini"
                        and ("429" in error_msg or "resource_exhausted" in error_msg))
                    or (self.provider == "groq"
                        and ("429" in error_msg or "rate_limit" in error_msg))
                )

                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(
                        "Rate limited by %s. Retrying in %ss (attempt %d/%d)",
                        self.provider, wait_time, attempt + 1, max_retries,
                    )
                    time.sleep(wait_time)
                    continue
                raise e

        return ""