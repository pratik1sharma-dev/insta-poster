"""
Image Generator Agent - Creates carousel images using Gemini.
"""
from pathlib import Path
from typing import List
import logging
from google import genai as genai_client
from google.genai import types
from PIL import Image
import io
from src.models import ContentStrategy, GeneratedContent, VisualStyle
from src.config import settings


logger = logging.getLogger(__name__)


class ImageGenerator:
    """AI agent that generates carousel images."""

    def __init__(self):
        """Initialize the Image Generator with Gemini API."""
        self.client = genai_client.Client(api_key=settings.gemini_api_key)
        self.image_model = settings.gemini_model

    def generate_carousel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        output_dir: Path,
    ) -> List[Path]:
        """
        Generate all images for a carousel post.

        Args:
            content: Generated content with slides
            strategy: Content strategy
            output_dir: Directory to save images

        Returns:
            List of paths to generated images
        """
        image_paths = []

        # Create a single chat session so the model keeps context across slides
        chat = self.client.chats.create(
            model=self.image_model,
            config=types.GenerateContentConfig(
                response_modalities=["Text", "Image"],
            ),
        )

        # Global style / goal brief for this carousel
        style_brief = f"""You are designing all images for a single Instagram carousel post.

Topic: {strategy.topic}
Visual style: {strategy.visual_style}
Total slides: {len(content.slides)}

Goal:
- Create visually consistent, scroll-stopping images that match the text content.
- Help grow followers and engagement (saves, shares, comments, follows).

Global rules:
- All slides must clearly look like one cohesive series.
- Use a consistent color palette and typography across slides.
- Keep overall layout structure and style coherent across slides.
"""

        # Prime the chat with the shared brief
        chat.send_message(style_brief)

        for slide in content.slides:
            # Enhance image prompt with style guidelines
            enhanced_prompt = self._enhance_prompt(
                slide.image_prompt, slide.text_overlay, strategy.visual_style
            )

            logger.info(
                "Generating image for slide %s with prompt:\n%s",
                slide.slide_number,
                enhanced_prompt,
            )

            # Generate image in the shared chat session
            response = chat.send_message(enhanced_prompt)

            image_path = self._generate_single_image(
                response, slide.slide_number, output_dir
            )

            if image_path:
                image_paths.append(image_path)

        return image_paths

    def _enhance_prompt(
        self, base_prompt: str, text_overlay: str, visual_style: VisualStyle
    ) -> str:
        """
        Enhance image prompt with style guidelines and text overlay.

        Args:
            base_prompt: Base image prompt from content generator
            text_overlay: Text to overlay on image
            visual_style: Visual style to apply

        Returns:
            Enhanced prompt for image generation
        """
        style_guidelines = {
            VisualStyle.QUOTE_BASED: "Clean background with elegant typography, focus on readability, minimal distractions",
            VisualStyle.INFOGRAPHIC: "Data visualization style, charts and icons, professional color scheme, easy to understand",
            VisualStyle.MIXED: "Balanced combination of imagery and text, dynamic layout, engaging composition",
            VisualStyle.MINIMALIST: "Simple and clean design, lots of whitespace, single focus point, elegant",
            VisualStyle.BOLD_TEXT: "Large, impactful typography, high contrast, attention-grabbing, modern fonts",
        }

        style_guide = style_guidelines.get(
            visual_style, "Professional Instagram post design"
        )

        enhanced = f"""Create an Instagram carousel image (1080x1080px square format).

**Visual Style:** {style_guide}

**Text Overlay:** "{text_overlay}"

**Design Direction:** {base_prompt}

**Technical Requirements:**
- Square format (1:1 aspect ratio)
- High contrast for mobile viewing
- Text must be highly readable
- Professional color scheme
- Modern, engaging aesthetic
- Suitable for Instagram feed

The text overlay should be integrated into the design, not just placed on top.
"""

        return enhanced

    def _generate_single_image(
        self, response, slide_number: int, output_dir: Path
    ) -> Path:
        """
        Save a single image from a Gemini chat response.

        Args:
            response: Chat response containing image data
            slide_number: Slide number for filename
            output_dir: Directory to save image

        Returns:
            Path to saved image.

        Raises:
            RuntimeError if the model does not return valid image bytes.
        """
        image_bytes = None

        # First try the chat-style server_content structure
        try:
            server_content = getattr(response, "server_content", None)
            model_turn = getattr(server_content, "model_turn", None) if server_content else None
            parts = getattr(model_turn, "parts", []) if model_turn else []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    image_bytes = inline.data
                    break
        except Exception as e:
            logger.error("Failed to extract image data (server_content) for slide %s: %s", slide_number, e)

        # Fallback to candidate/content.parts shape if needed
        if not image_bytes:
            try:
                candidate = response.candidates[0]
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", []) if content is not None else []
                for part in parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        image_bytes = inline.data
                        break
            except Exception as e:
                logger.error("Failed to extract image data (candidates) for slide %s: %s", slide_number, e)

        if not image_bytes:
            msg = f"No image data returned from Gemini for slide {slide_number}"
            logger.error(msg)
            raise RuntimeError(msg)

        try:
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            logger.error("Failed to decode image bytes for slide %s: %s", slide_number, e)
            raise

        image_path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(image_path, "PNG")
        logger.info("Saved image for slide %s to %s", slide_number, image_path)
        return image_path

    def _create_placeholder_image(self, prompt: str, slide_number: int) -> Image.Image:
        """
        Create a placeholder image.
        This would be replaced with actual Gemini Imagen API call.

        Args:
            prompt: Image prompt
            slide_number: Slide number

        Returns:
            PIL Image
        """
        from PIL import Image, ImageDraw, ImageFont

        # Create a 1080x1080 image with a gradient background
        img = Image.new("RGB", (1080, 1080), color=(73, 109, 137))

        # Add some basic text
        draw = ImageDraw.Draw(img)

        # Try to load a font, fall back to default if not available
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
            small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 30)
        except:
            font = ImageFont.load_default()
            small_font = ImageFont.load_default()

        # Add text
        text = f"Slide {slide_number}"
        draw.text((540, 500), text, fill=(255, 255, 255), font=font, anchor="mm")

        note = "Placeholder - Replace with Gemini Imagen"
        draw.text((540, 580), note, fill=(200, 200, 200), font=small_font, anchor="mm")

        return img
