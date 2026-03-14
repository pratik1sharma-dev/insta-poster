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

from src.models import ContentStrategy, GeneratedContent, VisualStyle
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
                len(content.slides),
                strategy.visual_style,
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
You are designing an Instagram carousel post.

Topic: {strategy.topic}
Visual style: {strategy.visual_style}
Total slides: {total_slides}

Design system rules:
- All slides must look like part of the SAME carousel
- Use consistent colors, typography and layout
- Maintain the same visual theme across slides
- Clean modern Instagram design
- Highly readable for mobile
"""

    def _build_slide_prompt(
        self,
        base_prompt: str,
        text_overlay: str,
        slide_number: int,
        total_slides: int,
        visual_style: VisualStyle,
        style_context: str,
    ) -> str:

        style_guidelines = {
            VisualStyle.QUOTE_BASED: "clean background, elegant typography, minimal distractions",
            VisualStyle.INFOGRAPHIC: "data visualization style, icons, simple charts",
            VisualStyle.MIXED: "combination of illustration and text",
            VisualStyle.MINIMALIST: "lots of whitespace, simple layout",
            VisualStyle.BOLD_TEXT: "large impactful typography, strong contrast",
        }

        style_guide = style_guidelines.get(
            visual_style,
            "modern Instagram design",
        )

        return f"""
{style_context}

Slide {slide_number} of {total_slides}

Visual style guidance:
{style_guide}

Text overlay:
"{text_overlay}"

Design direction:
{base_prompt}

Technical requirements:
- 1080x1080 square Instagram post
- High contrast
- Mobile readable
- Clean modern layout

Return ONLY an image.
Do not return text.
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
