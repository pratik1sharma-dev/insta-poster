"""
Image Generator Agent - Creates carousel images using Gemini.
"""

from pathlib import Path
from typing import List
import logging
import io

from google import genai as genai_client
from google.genai import types
from PIL import Image

from src.models import ContentStrategy, GeneratedContent
from src.config import settings


logger = logging.getLogger(__name__)


class ImageGenerator:
    """AI agent that generates carousel images."""

    def __init__(self):
        """Initialize Gemini client."""
        self.client = genai_client.Client(api_key=settings.gemini_api_key)
        self.image_model = settings.gemini_model

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
            )

            logger.info(
                "Generating image for slide %s with prompt:\n%s",
                slide.slide_number,
                prompt,
            )

            response = self.client.models.generate_content(
                model=self.image_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"]
                ),
            )

            image_path = self._save_image(
                response,
                slide.slide_number,
                output_dir,
            )

            image_paths.append(image_path)

        return image_paths

    def _build_style_context(self, strategy: ContentStrategy, total_slides: int) -> str:
        """Create shared design system for the carousel."""

        return f"""
You are a creative director designing a cohesive Instagram carousel.

**Core Creative:**
- Topic: {strategy.topic}
- Angle: {strategy.angle}
- Visual Metaphor: {strategy.visual_metaphor}
- Color Palette: {strategy.color_palette}
- Typography Style: {strategy.typography_style}
- Total Slides: {total_slides}

**Design System Rules:**
- **One Metaphor:** Every slide MUST be a visual variation of the single core **Visual Metaphor**.
- **Cohesive Story:** The slides must tell a clear visual story, progressing from one to the next.
- **Consistent Style:** Use the same colors and typography as defined above.
- **Aesthetic:** Clean, modern, and professional. Avoid garish, overly saturated, or "loud" colors.
- **Readability:** Ensure text is clean, modern, and highly readable on mobile.
"""

    def _build_slide_prompt(
        self,
        base_prompt: str,
        text_overlay: str,
        slide_number: int,
        style_context: str,
    ) -> str:

        return f"""
{style_context}

**This is Slide {slide_number}.**

**Your Task:**
Create an image for this slide that is a clear and creative execution of the core **Visual Metaphor**.

**Text Overlay for this slide:**
"{text_overlay}"

**Specific design direction for this slide (build on the metaphor):**
{base_prompt}

**Technical Requirements:**
- 1080x1080 square Instagram post.
- High contrast and mobile readable.
- Adhere to the visual style described in the design system.

Return ONLY an image. Do not return text.
"""

    def _save_image(
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
            logger.error("Failed to extract image for slide %s: %s", slide_number, e)

        if not image_bytes:
            raise RuntimeError(f"No image returned for slide {slide_number}")

        image = Image.open(io.BytesIO(image_bytes))

        image_path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(image_path, "PNG")

        logger.info("Saved image for slide %s to %s", slide_number, image_path)

        return image_path
