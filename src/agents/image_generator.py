"""
Image Generator Agent - Creates carousel images using Gemini or Replicate.
"""

from pathlib import Path
from typing import List, Optional
import logging
import io
import time
import requests
import re

from google import genai as genai_client
from google.genai import types
import replicate
from replicate.exceptions import ReplicateError
from PIL import Image

from jinja2 import Template
from html2image import Html2Image

from src.models import ContentStrategy, GeneratedContent, ChannelConfig
from src.config import settings


logger = logging.getLogger(__name__)


class ImageGenerator:
    """AI agent that generates carousel images using AI for the hook and HTML templates for the rest."""

    def __init__(self):
        """Initialize the requested provider and HTML renderer."""
        self.provider = settings.image_provider.lower()
        
        if self.provider == "gemini":
            self.client = genai_client.Client(api_key=settings.gemini_api_key)
            self.model = settings.gemini_generator_model
        elif self.provider == "replicate":
            # REPLICATE_API_TOKEN is handled by the replicate library if in environment
            self.model = settings.replicate_model
        else:
            raise ValueError(f"Unsupported image provider: {self.provider}")

        # Initialize HTML Renderer
        self.hti = Html2Image(size=(1080, 1080))
        # Optional: Disable sandbox if running as root on a server
        # self.hti.browser.flags = ['--no-sandbox', '--disable-setuid-sandbox']

    def _extract_primary_color(self, color_palette: str) -> str:
        """Attempt to extract a primary hex or CSS color from the strategy text."""
        if "blue" in color_palette.lower():
            return "#0f172a" # Deep Slate Blue
        elif "green" in color_palette.lower():
            return "#064e3b" # Deep Emerald
        elif "red" in color_palette.lower():
            return "#7f1d1d" # Deep Red
        elif "purple" in color_palette.lower():
            return "#4c1d95"
        return "#111827" # Default Dark Gray/Black

    def _extract_text_color(self, bg_color: str) -> str:
        """Return white or black text depending on background."""
        return "#ffffff"

    def generate_carousel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        output_dir: Path,
        channel_name: str = "Capsule",
    ) -> List[Path]:

        image_paths = []
        total_slides = len(content.slides)
        
        # Determine brand colors for templates
        bg_color = self._extract_primary_color(strategy.color_palette)
        text_color = self._extract_text_color(bg_color)

        style_context = self._build_style_context(strategy, total_slides)

        # Load HTML Template
        template_path = Path("src/templates/slide.html")
        if template_path.exists():
            with open(template_path, "r") as f:
                template_str = f.read()
            jinja_template = Template(template_str)
        else:
            logger.warning("HTML template not found, falling back to AI for all slides.")
            jinja_template = None

        for slide in content.slides:
            image_path = output_dir / f"slide_{slide.slide_number:02d}.png"

            # Slide 1: AI Hook Image
            # OR if no template is found, use AI for all.
            if slide.slide_number == 1 or not jinja_template:
                logger.info("Generating AI Hook Image for slide %s...", slide.slide_number)
                
                prompt = self._build_slide_prompt(
                    slide.image_prompt,
                    slide.text_overlay,
                    slide.slide_number,
                    style_context,
                    strategy,
                )

                try:
                    if self.provider == "gemini":
                        # Add delay to avoid 2-images-per-minute free tier limit
                        if slide.slide_number > 1:
                            logger.info("Waiting 35s to respect Gemini free tier image rate limits...")
                            time.sleep(35)

                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=["IMAGE"]
                            ),
                        )
                        self._save_gemini_image(response, slide.slide_number, output_dir)
                    
                    elif self.provider == "replicate":
                        max_retries = 3
                        retry_delay = 10
                        
                        output = None
                        for attempt in range(max_retries):
                            try:
                                input_params = {
                                    "prompt": prompt,
                                    "aspect_ratio": "1:1",
                                }
                                if "flux" in self.model:
                                    input_params["output_format"] = "png"

                                output = replicate.run(
                                    self.model,
                                    input=input_params
                                )
                                break
                            except Exception as e:
                                is_rate_limit = False
                                if isinstance(e, ReplicateError) and ("429" in str(e) or "throttled" in str(e).lower()):
                                    is_rate_limit = True
                                
                                if is_rate_limit and attempt < max_retries - 1:
                                    wait_time = retry_delay * (2 ** attempt)
                                    logger.warning(f"Image rate limit hit. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                                    time.sleep(wait_time)
                                    continue
                                raise e

                        if not output:
                            raise RuntimeError(f"Failed to generate image for slide {slide.slide_number} after retries")

                        image_url = output[0] if isinstance(output, list) else str(output)
                        self._save_replicate_image(image_url, slide.slide_number, output_dir)

                    image_paths.append(image_path)
                
                except Exception as e:
                    logger.error("Failed to generate AI image for slide %s: %s", slide.slide_number, e)

            # Slides 2+: HTML/CSS Templated Images
            else:
                logger.info("Rendering HTML template for slide %s...", slide.slide_number)
                try:
                    html_content = jinja_template.render(
                        bg_color=bg_color,
                        text_color=text_color,
                        channel_name=channel_name,
                        text_overlay=slide.text_overlay,
                        current_slide=slide.slide_number,
                        total_slides=total_slides
                    )
                    
                    # html2image requires saving to current dir first, so we use a temp name then move it
                    temp_name = f"temp_slide_{slide.slide_number}.png"
                    self.hti.screenshot(html_str=html_content, save_as=temp_name)
                    
                    # Move to output dir
                    temp_path = Path(temp_name)
                    if temp_path.exists():
                        temp_path.replace(image_path)
                        image_paths.append(image_path)
                        logger.info("Successfully rendered HTML for slide %s", slide.slide_number)
                    else:
                        raise FileNotFoundError("html2image failed to create the file.")

                except Exception as e:
                    logger.error("Failed to render HTML for slide %s: %s", slide.slide_number, e)

        return image_paths

    def _build_style_context(self, strategy: ContentStrategy, total_slides: int) -> str:
        """Create shared design system for the carousel."""

        return f"""
You are a senior graphic designer creating a single, high-impact Instagram post.

**Brand DNA:**
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Color Palette: {strategy.color_palette}
- Typography Style: {strategy.typography_style}
- Aesthetic: Clean, modern, professional, and minimalist.

**Strict Composition Rules:**
- **Single Image Only:** Create one unified, focused composition for this specific slide.
- **No Collages:** Do not use sub-images, grids, or multi-image layouts. 
- **Negative Space:** Ensure there is enough clean space for the text to be easily readable.
- **Readability:** Text must be bold, sharp, and highly readable on mobile screens.
"""

    def _build_slide_prompt(
        self,
        base_prompt: str,
        text_overlay: str,
        slide_number: int,
        style_context: str,
        strategy: ContentStrategy,
    ) -> str:

        return f"""
{style_context}

**Visual Theme:** {strategy.visual_metaphor}

**Slide Design Mission:**
You must create a single, clean image that combines a visual background with a specific text overlay.

1. **The Background Scene:** {base_prompt}
2. **The ONLY Text Allowed:** "{text_overlay}"

**Strict Visual Rules:**
- **No Background Text:** Do not include any labels, numbers, data legends, or random characters in the background. 
- **No Charts/Grids:** Avoid drawing literal charts or data tables that contain text. Represent data through abstract shapes instead.
- **Single Focal Point:** The ONLY readable words in the entire image must be: "{text_overlay}".
- **Placement:** Position "{text_overlay}" in a clear area of negative space using bold, professional typography.

**Final Directive:**
Generate a single 1080x1080 image. Ensure zero typos in the text. Do not return conversational text. Return ONLY the image.
"""

    def _save_gemini_image(
        self,
        response,
        slide_number: int,
        output_dir: Path,
    ) -> Path:

        image_bytes = None

        try:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    break
        except Exception as e:
            logger.error("Failed to extract Gemini image for slide %s: %s", slide_number, e)

        if not image_bytes:
            raise RuntimeError(f"No image returned for slide {slide_number}")

        image = Image.open(io.BytesIO(image_bytes))
        image_path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(image_path, "PNG")

        logger.info("Saved Gemini image for slide %s to %s", slide_number, image_path)
        return image_path

    def _save_replicate_image(
        self,
        url: str,
        slide_number: int,
        output_dir: Path,
    ) -> Path:
        """Download and save image from Replicate URL."""
        
        response = requests.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download image from {url}")

        image = Image.open(io.BytesIO(response.content))
        image_path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(image_path, "PNG")

        logger.info("Saved Replicate image for slide %s to %s", slide_number, image_path)
        return image_path
