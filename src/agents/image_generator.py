"""
Image Generator Agent - Creates carousel images using Gemini or Replicate.
"""

from pathlib import Path
from typing import List
import logging
import io
import time
import requests

from google import genai as genai_client
from google.genai import types
import replicate
from replicate.exceptions import ReplicateError
from PIL import Image

from src.models import ContentStrategy, GeneratedContent
from src.config import settings


logger = logging.getLogger(__name__)


class ImageGenerator:
    """AI agent that generates carousel images."""

    def __init__(self):
        """Initialize the requested provider."""
        self.provider = settings.image_provider.lower()
        
        if self.provider == "gemini":
            self.client = genai_client.Client(api_key=settings.gemini_api_key)
            self.model = settings.gemini_generator_model
        elif self.provider == "replicate":
            # REPLICATE_API_TOKEN is handled by the replicate library if in environment
            self.model = settings.replicate_model
        else:
            raise ValueError(f"Unsupported image provider: {self.provider}")

    def generate_carousel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        output_dir: Path,
    ) -> List[Path]:

        image_paths = []

        style_context = self._build_style_context(strategy, len(content.slides))

        for slide in content.slides:

            prompt = self._build_slide_prompt(
                slide.image_prompt,
                slide.text_overlay,
                slide.slide_number,
                style_context,
                strategy,
            )

            logger.info(
                "Generating image (%s) for slide %s with prompt:\n%s",
                self.provider,
                slide.slide_number,
                prompt,
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
                    image_path = self._save_gemini_image(response, slide.slide_number, output_dir)
                
                elif self.provider == "replicate":
                    # Add retry logic for image generation
                    max_retries = 3
                    retry_delay = 10  # seconds (images take longer and have tighter limits)
                    
                    output = None
                    for attempt in range(max_retries):
                        try:
                            output = replicate.run(
                                self.model,
                                input={
                                    "prompt": prompt,
                                    "aspect_ratio": "1:1",
                                    "output_format": "png",
                                }
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

                    # Replicate returns a list of File objects or URLs
                    image_url = output[0] if isinstance(output, list) else str(output)
                    image_path = self._save_replicate_image(image_url, slide.slide_number, output_dir)

                image_paths.append(image_path)
            
            except Exception as e:
                logger.error("Failed to generate image for slide %s: %s", slide.slide_number, e)
                # We could implement a retry or fallback here if needed

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
You must create a single image that artfully combines a visual scene with a text overlay.

1. **The Visual Scene:** {base_prompt}
2. **The Text Overlay:** "{text_overlay}"

**Placement Directive:**
- Integrate the text overlay into the scene in a professional, cinematic way.
- Use areas of negative space or center the text for maximum impact.
- The text must be large, bold, and high-contrast against the background.
- **CRITICAL:** Every word in "{text_overlay}" must be spelled perfectly.

Return ONLY the single 1080x1080 image file. Do not include conversational text or explanation.
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
