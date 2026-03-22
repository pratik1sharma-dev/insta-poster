"""
Image Generator Agent - Creates carousel images using Gemini or Replicate.
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
from PIL import Image, ImageFilter

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
        # Add flags for Linux server environment (running as root)
        # Force window size and disable features that cause gray/white bars
        self.hti.browser.flags = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--hide-scrollbars',
            '--window-size=1080,1080',
            '--force-device-scale-factor=1',
            '--disable-dev-shm-usage',       # Prevent memory issues in containers
        ]

    def _extract_primary_color(self, color_palette: Union[str, dict]) -> str:
        """Extract background color from strategy (expects dict format)."""

        # If it's already a dictionary (correct format from LLM)
        if isinstance(color_palette, dict):
            bg = color_palette.get('background')
            if bg and isinstance(bg, str) and bg.startswith('#'):
                return bg
            # Fallback keys
            primary = color_palette.get('primary', color_palette.get('bg', "#111827"))
            if isinstance(primary, str) and primary.startswith('#'):
                return primary

        # Legacy string parsing (fallback for old strategy format)
        hex_match = re.search(r'#(?:[0-9a-fA-F]{3}){1,2}', str(color_palette))
        if hex_match:
            return hex_match.group(0)

        # If all else fails, return default
        logger.warning(f"Could not parse color_palette: {color_palette}, using default #111827")
        return "#111827"  # Dark gray default

    def _extract_text_color(self, color_palette: Union[str, dict]) -> str:
        """Extract text color or calculate contrast from background."""

        # If dict has explicit text color, use it
        if isinstance(color_palette, dict):
            text = color_palette.get('text')
            if text and isinstance(text, str) and text.startswith('#'):
                return text

        # Calculate from background for best contrast
        bg_color = self._extract_primary_color(color_palette)
        return self._get_contrast_color(bg_color)

    def _get_contrast_color(self, hex_color: str) -> str:
        """Calculate whether white or black text has better contrast with the background."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        
        # Convert hex to RGB
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        
        # Calculate luminance (standard formula)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        
        # If background is light (luminance > 0.5), use black text. Otherwise white.
        return "#000000" if luminance > 0.5 else "#ffffff"

    def generate_carousel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        output_dir: Path,
        channel_name: str = "Capsule",
        skip_ai_image: bool = False,
    ) -> List[Path]:

        image_paths = []
        total_slides = len(content.slides)
        
        # Determine brand colors for templates
        bg_color = self._extract_primary_color(strategy.color_palette)
        text_color = self._extract_text_color(strategy.color_palette)

        style_context = self._build_style_context(strategy, total_slides)
        
        # Keep track of Slide 1 path for blurred background
        hook_image_path = None

        for slide in content.slides:
            image_path = output_dir / f"slide_{slide.slide_number:02d}.png"

            # Slide 1: AI Hook Image
            if slide.slide_number == 1 and not skip_ai_image:
                logger.info(f"[Slide 1] Generating AI Hook Image: {strategy.topic}")
                
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
                        hook_image_path = self._save_gemini_image(response, slide.slide_number, output_dir)
                    
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
                        hook_image_path = self._save_replicate_image(image_url, slide.slide_number, output_dir)
                except Exception as e:
                    logger.error("Failed to generate AI image for slide %s: %s", slide.slide_number, e)

                if hook_image_path:
                    image_paths.append(hook_image_path)

            # Slides 2+ (or Slide 1 if skipping AI): HTML/CSS Templated Images
            elif slide.slide_number > 1 or skip_ai_image:
                if skip_ai_image and slide.slide_number == 1:
                    logger.info("[Slide 1] SKIP-AI-IMAGE: Using HTML template for Slide 1")
                    hook_image_path = image_path # Used for blurred backgrounds later
                template_name = slide.template_name if slide.template_name else "standard"
                bg_style = slide.background_style if slide.background_style else "solid"
                
                msg = f"[Slide {slide.slide_number}] Rendering into '{template_name}' template with '{bg_style}' background"
                logging.getLogger(__name__).info(msg)
                logging.getLogger(__name__).info(f"Text Overlay: {slide.text_overlay}")
                
                try:
                    # Load template
                    template_file = Path(f"src/templates/{template_name}.html")
                    if not template_file.exists():
                        # Fallback to standard
                        template_file = Path("src/templates/standard.html")
                        if not template_file.exists():
                            # Fallback to generic slide.html if created earlier
                            template_file = Path("src/templates/slide.html")
                    
                    with open(template_file, "r") as f:
                        jinja_template = Template(f.read())

                    # Prepare background data
                    bg_data = {"type": bg_style, "value": bg_color}
                    if bg_style == "blurred_hook" and hook_image_path and hook_image_path.exists():
                        # Create blurred background
                        with Image.open(hook_image_path) as img:
                            # Apply blur and darken
                            bg_img = img.filter(ImageFilter.GaussianBlur(radius=40))
                            # Add dark overlay
                            from PIL import ImageEnhance
                            enhancer = ImageEnhance.Brightness(bg_img)
                            bg_img = enhancer.enhance(0.4)
                            
                            # Convert to base64
                            buffered = io.BytesIO()
                            bg_img.save(buffered, format="PNG")
                            img_str = base64.b64encode(buffered.getvalue()).decode()
                            bg_data["image_b64"] = f"data:image/png;base64,{img_str}"

                    html_content = jinja_template.render(
                        bg_color=bg_color,
                        bg_style=bg_style,
                        bg_image_b64=bg_data.get("image_b64"),
                        text_color=text_color,
                        channel_name=channel_name,
                        text_overlay=slide.text_overlay,
                        current_slide=slide.slide_number,
                        total_slides=total_slides
                    )
                    
                    temp_name = f"temp_slide_{slide.slide_number}.png"

                    # Render with explicit size
                    self.hti.screenshot(
                        html_str=html_content,
                        save_as=temp_name,
                        size=(1080, 1080)
                    )

                    temp_path = Path(temp_name)
                    if temp_path.exists():
                        # Crop to exact 1080x1080 to remove any gray bars
                        img = Image.open(temp_path)
                        if img.size != (1080, 1080):
                            logger.info(f"Cropping image from {img.size} to 1080x1080")
                            # Crop from center if larger, or pad if smaller
                            if img.size[0] >= 1080 and img.size[1] >= 1080:
                                left = (img.size[0] - 1080) // 2
                                top = (img.size[1] - 1080) // 2
                                img = img.crop((left, top, left + 1080, top + 1080))
                            else:
                                # If smaller, something went wrong - try to use what we have
                                logger.warning(f"Image smaller than expected: {img.size}")
                        img.save(temp_path)

                        temp_path.replace(image_path)
                        image_paths.append(image_path)
                    else:
                        raise FileNotFoundError("html2image failed to create the file.")

                except Exception as e:
                    logger.error(f"Failed to render HTML for slide {slide.slide_number}: {e}")

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
