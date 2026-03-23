"""
Image Generator Agent - Creates carousel images using AI (hook) and HTML templates (content slides).
"""

import base64
from pathlib import Path
from typing import List, Optional, Union
import logging
import io
import time
import requests
import re

from google import genai as genai_client
from google.genai import types
import replicate
from replicate.exceptions import ReplicateError
from PIL import Image, ImageFilter, ImageEnhance

from jinja2 import Template
from html2image import Html2Image

from src.models import ContentStrategy, GeneratedContent, ChannelConfig, CarouselSlide
from src.config import settings


logger = logging.getLogger(__name__)


class ImageGenerator:
    """
    Generates carousel images.
    - Slide 1: AI-generated background image (Gemini or Replicate)
    - Slides 2+: HTML/CSS templates rendered via html2image

    Key improvements over previous version:
    - Accent color extracted and passed to all templates
    - Structured slide fields (headline, subtext, left_content, etc.)
      passed to templates instead of flat text_overlay only
    - AI image prompt explicitly forbids text/labels in the scene
    - channel_name always comes from ChannelConfig, not a default string
    - action_text from generated CTA passed to cta template
    """

    def __init__(self):
        """Initialize the requested provider and HTML renderer."""
        self.provider = settings.image_provider.lower()

        if self.provider == "gemini":
            self.client = genai_client.Client(api_key=settings.gemini_api_key)
            self.model = settings.gemini_image_model
        elif self.provider == "replicate":
            self.model = settings.replicate_model
        elif self.provider == "sd":
            self.api_url = settings.sd_api_url
            self.steps = settings.sd_steps
            self.timeout = settings.sd_timeout
        else:
            raise ValueError(f"Unsupported image provider: {self.provider}")

        self.hti = Html2Image(size=(1080, 1080))
        self.hti.browser.flags = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--hide-scrollbars',
            '--window-size=1080,1080',
            '--force-device-scale-factor=1',
            '--disable-dev-shm-usage',
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_carousel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        output_dir: Path,
        skip_ai_image: bool = False,
    ) -> List[Path]:
        """
        Generate all carousel slide images.

        Args:
            content:        Generated slide content including structured fields.
            strategy:       Content strategy with color palette etc.
            channel_config: Channel config — used for name and branding.
            output_dir:     Where to save the images.
            skip_ai_image:  If True, renders slide 1 with HTML instead of AI.

        Returns:
            List of Paths to generated images in slide order.
        """
        image_paths = []
        total_slides = len(content.slides)

        # Extract all three brand colors
        bg_color = self._extract_color(strategy.color_palette, "background", "#111827")
        text_color = self._extract_color(strategy.color_palette, "text", None)
        if not text_color:
            text_color = self._get_contrast_color(bg_color)
        accent_color = self._extract_color(strategy.color_palette, "accent", "#3b82f6")

        # Channel name always from config
        channel_name = channel_config.name

        style_context = self._build_style_context(strategy)
        hook_image_path: Optional[Path] = None

        for slide in content.slides:
            image_path = output_dir / f"slide_{slide.slide_number:02d}.png"

            # ── Slide 1: AI Hook Image ──────────────────────────────────
            if slide.slide_number == 1 and not skip_ai_image:
                logger.info("[Slide 1] Generating AI hook image: %s", strategy.topic)

                prompt = self._build_ai_image_prompt(
                    slide, style_context, strategy
                )

                try:
                    if self.provider == "gemini":
                        if slide.slide_number > 1:
                            logger.info("Waiting 35s for Gemini free tier rate limit...")
                            time.sleep(35)

                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=["IMAGE"]
                            ),
                        )
                        hook_image_path = self._save_gemini_image(
                            response, slide.slide_number, output_dir
                        )

                    elif self.provider == "replicate":
                        hook_image_path = self._generate_replicate_image(
                            prompt, slide.slide_number, output_dir
                        )

                    elif self.provider == "sd":
                        hook_image_path = self._generate_sd_image(
                            prompt, slide.slide_number, output_dir
                        )

                except Exception as e:
                    logger.error(
                        "Failed to generate AI image for slide %s: %s",
                        slide.slide_number, e
                    )

                if hook_image_path:
                    image_paths.append(hook_image_path)

            # ── Slides 2+ (or slide 1 if skipping AI): HTML templates ──
            elif slide.slide_number > 1 or skip_ai_image:
                if skip_ai_image and slide.slide_number == 1:
                    logger.info("[Slide 1] skip_ai_image=True: using HTML template")
                    hook_image_path = image_path

                template_name = slide.template_name or "standard"
                bg_style = slide.background_style or "solid"

                logger.info(
                    "[Slide %s] Rendering template='%s' bg='%s'",
                    slide.slide_number, template_name, bg_style
                )
                logger.info("[Slide %s] Headline: %s", slide.slide_number, slide.headline or slide.text_overlay)

                try:
                    rendered_path = self._render_html_slide(
                        slide=slide,
                        template_name=template_name,
                        bg_style=bg_style,
                        bg_color=bg_color,
                        text_color=text_color,
                        accent_color=accent_color,
                        channel_name=channel_name,
                        hook_image_path=hook_image_path,
                        current_slide=slide.slide_number,
                        total_slides=total_slides,
                        output_path=image_path,
                        cta_text=content.call_to_action,
                    )
                    if rendered_path:
                        image_paths.append(rendered_path)

                except Exception as e:
                    logger.error(
                        "Failed to render HTML for slide %s: %s",
                        slide.slide_number, e
                    )

        return image_paths

    # ------------------------------------------------------------------
    # HTML template rendering
    # ------------------------------------------------------------------

    def _render_html_slide(
        self,
        slide: CarouselSlide,
        template_name: str,
        bg_style: str,
        bg_color: str,
        text_color: str,
        accent_color: str,
        channel_name: str,
        hook_image_path: Optional[Path],
        current_slide: int,
        total_slides: int,
        output_path: Path,
        cta_text: str = "",
    ) -> Optional[Path]:
        """Load a Jinja2 template and render it to a 1080x1080 PNG."""

        # Find template file
        template_file = Path(f"src/templates/{template_name}.html")
        if not template_file.exists():
            logger.warning(
                "Template '%s' not found, falling back to standard.html",
                template_name
            )
            template_file = Path("src/templates/standard.html")
        if not template_file.exists():
            raise FileNotFoundError(f"No template found at {template_file}")

        with open(template_file, "r") as f:
            jinja_template = Template(f.read())

        # Build blurred background if needed
        bg_image_b64 = None
        if bg_style == "blurred_hook" and hook_image_path and hook_image_path.exists():
            bg_image_b64 = self._make_blurred_b64(hook_image_path)

        # Derive action_text for CTA slide
        # Priority: slide.action_text > first ~5 words of generated CTA > fallback
        action_text = slide.action_text
        if not action_text and slide.purpose.value == "cta" and cta_text:
            # Use a short version of the CTA as button label
            action_text = "Comment below"

        # Render
        html_content = jinja_template.render(
            # Colors
            bg_color=bg_color,
            text_color=text_color,
            accent_color=accent_color,
            # Background
            bg_style=bg_style,
            bg_image_b64=bg_image_b64,
            # Branding
            channel_name=channel_name,
            # Slide counters
            current_slide=current_slide,
            total_slides=total_slides,
            # Structured text fields
            headline=slide.headline,
            subtext=slide.subtext,
            pre_label=slide.pre_label,
            left_content=slide.left_content,
            right_content=slide.right_content,
            action_text=action_text,
            # Flat fallback (always populated)
            text_overlay=slide.text_overlay,
        )

        temp_name = f"temp_slide_{current_slide}.png"
        self.hti.screenshot(html_str=html_content, save_as=temp_name, size=(1080, 1080))

        temp_path = Path(temp_name)
        if not temp_path.exists():
            raise FileNotFoundError(f"html2image failed to create {temp_name}")

        # Crop to exact 1080x1080 to remove any gray bars
        img = Image.open(temp_path)
        if img.size != (1080, 1080):
            logger.info(
                "Cropping slide %s from %s to 1080x1080",
                current_slide, img.size
            )
            if img.size[0] >= 1080 and img.size[1] >= 1080:
                left = (img.size[0] - 1080) // 2
                top = (img.size[1] - 1080) // 2
                img = img.crop((left, top, left + 1080, top + 1080))
            else:
                logger.warning("Slide %s smaller than expected: %s", current_slide, img.size)
        img.save(temp_path)
        temp_path.replace(output_path)

        return output_path

    def _make_blurred_b64(self, image_path: Path) -> str:
        """Blur, darken, and base64-encode an image for use as background."""
        with Image.open(image_path) as img:
            blurred = img.filter(ImageFilter.GaussianBlur(radius=40))
            darkened = ImageEnhance.Brightness(blurred).enhance(0.4)
            buffered = io.BytesIO()
            darkened.save(buffered, format="PNG")
            b64 = base64.b64encode(buffered.getvalue()).decode()
            return f"data:image/png;base64,{b64}"

    # ------------------------------------------------------------------
    # AI image generation
    # ------------------------------------------------------------------

    def _build_style_context(self, strategy: ContentStrategy) -> str:
        """Shared design brief for the AI image model."""
        return f"""You are a senior graphic designer creating a background image for an Instagram carousel.

Brand context:
- Topic: {strategy.topic}
- Visual theme: {strategy.visual_metaphor}
- Color palette: {strategy.color_palette}
- Aesthetic: Clean, modern, cinematic, minimalist.

Composition rules:
- Create ONE unified background scene.
- Leave generous negative space (especially center) for text overlay.
- No collages or multi-image grids.
- Photorealistic or high-quality illustrative style.
"""

    def _build_ai_image_prompt(
        self,
        slide: CarouselSlide,
        style_context: str,
        strategy: ContentStrategy,
    ) -> str:
        """
        Build the image generation prompt for slide 1.

        Critical: explicitly forbids any text, letters, words, or labels
        in the generated image. Text is handled by the HTML layer.
        """
        return f"""{style_context}

Scene to create:
{slide.image_prompt}

ABSOLUTE RULES — violations will ruin the slide:
1. NO TEXT of any kind in the image. No words, letters, numbers, labels,
   watermarks, captions, or typographic elements anywhere in the scene.
   Text will be added separately as an overlay.
2. NO charts, graphs, infographics, or data tables.
3. NO collages or multi-panel layouts.
4. ONE clear focal point with negative space around it.
5. Output a single 1080x1080 square image only.

Generate the background scene now."""

    def _generate_sd_image(
        self,
        prompt: str,
        slide_number: int,
        output_dir: Path,
    ) -> Optional[Path]:
        """Generate image via local Stable Diffusion API."""
        payload = {
            "prompt": prompt,
            "steps": self.steps,
            "width": 1080,
            "height": 1080,
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            r = response.json()
            
            image_data = base64.b64decode(r['images'][0])
            image_path = output_dir / f"slide_{slide_number:02d}.png"
            
            with open(image_path, 'wb') as f:
                f.write(image_data)
                
            logger.info("Saved SD image: slide %s → %s", slide_number, image_path)
            return image_path
            
        except Exception as e:
            logger.error("SD image generation failed: %s", e)
            return None

    def _generate_replicate_image(
        self,
        prompt: str,
        slide_number: int,
        output_dir: Path,
    ) -> Optional[Path]:
        """Generate image via Replicate with retry logic."""
        max_retries = 3
        retry_delay = 10

        for attempt in range(max_retries):
            try:
                input_params = {"prompt": prompt, "aspect_ratio": "1:1"}
                if "flux" in self.model:
                    input_params["output_format"] = "png"

                output = replicate.run(self.model, input=input_params)
                image_url = output[0] if isinstance(output, list) else str(output)
                return self._save_replicate_image(image_url, slide_number, output_dir)

            except Exception as e:
                is_rate_limit = (
                    isinstance(e, ReplicateError)
                    and ("429" in str(e) or "throttled" in str(e).lower())
                )
                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(
                        "Image rate limit hit. Retrying in %ss (attempt %d/%d)",
                        wait_time, attempt + 1, max_retries
                    )
                    time.sleep(wait_time)
                    continue
                raise e

        return None

    # ------------------------------------------------------------------
    # Color utilities
    # ------------------------------------------------------------------

    def _extract_color(
        self,
        color_palette: Union[str, dict],
        key: str,
        fallback: Optional[str],
    ) -> Optional[str]:
        """
        Extract a specific color from the palette.

        Handles both dict format (from improved LLM output) and
        legacy string format (fallback hex extraction).
        """
        if isinstance(color_palette, dict):
            value = color_palette.get(key)
            if value and isinstance(value, str) and value.startswith("#"):
                return value
            # Try common aliases
            aliases = {
                "background": ["bg", "background_color"],
                "text": ["primary", "text_color", "foreground"],
                "accent": ["secondary", "highlight", "accent_color"],
            }
            for alias in aliases.get(key, []):
                value = color_palette.get(alias)
                if value and isinstance(value, str) and value.startswith("#"):
                    return value

        # Legacy: parse JSON string then extract
        if isinstance(color_palette, str):
            try:
                parsed = __import__("json").loads(color_palette)
                return self._extract_color(parsed, key, fallback)
            except Exception:
                pass
            # Last resort: return first hex found for background, ignore key
            if key == "background":
                match = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}", color_palette)
                if match:
                    return match.group(0)

        if fallback:
            logger.warning(
                "Could not extract '%s' from palette: %s — using fallback %s",
                key, color_palette, fallback
            )
        return fallback

    def _get_contrast_color(self, hex_color: str) -> str:
        """Return black or white for best contrast against the given background."""
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#000000" if luminance > 0.5 else "#ffffff"

    # ------------------------------------------------------------------
    # Image save helpers
    # ------------------------------------------------------------------

    def _save_gemini_image(
        self,
        response,
        slide_number: int,
        output_dir: Path,
    ) -> Path:
        """Extract and save image bytes from a Gemini response."""
        image_bytes = None
        try:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    break
        except Exception as e:
            logger.error(
                "Failed to extract Gemini image for slide %s: %s", slide_number, e
            )

        if not image_bytes:
            raise RuntimeError(f"No image returned for slide {slide_number}")

        image = Image.open(io.BytesIO(image_bytes))
        image_path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(image_path, "PNG")
        logger.info("Saved Gemini image: slide %s → %s", slide_number, image_path)
        return image_path

    def _save_replicate_image(
        self,
        url: str,
        slide_number: int,
        output_dir: Path,
    ) -> Path:
        """Download and save image from a Replicate URL."""
        response = requests.get(url, timeout=60)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to download image from {url} (status {response.status_code})"
            )
        image = Image.open(io.BytesIO(response.content))
        image_path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(image_path, "PNG")
        logger.info("Saved Replicate image: slide %s → %s", slide_number, image_path)
        return image_path