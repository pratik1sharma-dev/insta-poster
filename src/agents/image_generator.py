"""
Image Generator Agent - Creates carousel images using Gemini Imagen.
"""
from pathlib import Path
from typing import List
import google.generativeai as genai
from PIL import Image
import io
from src.models import ContentStrategy, GeneratedContent, VisualStyle
from src.config import settings


class ImageGenerator:
    """AI agent that generates carousel images."""

    def __init__(self):
        """Initialize the Image Generator with Gemini API."""
        genai.configure(api_key=settings.gemini_api_key)
        # Use Imagen model for image generation
        self.model = genai.GenerativeModel(settings.gemini_model)

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

        for slide in content.slides:
            # Enhance image prompt with style guidelines
            enhanced_prompt = self._enhance_prompt(
                slide.image_prompt, slide.text_overlay, strategy.visual_style
            )

            # Generate image
            image_path = self._generate_single_image(
                enhanced_prompt, slide.slide_number, output_dir
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
        self, prompt: str, slide_number: int, output_dir: Path
    ) -> Path:
        """
        Generate a single image using Gemini.

        Args:
            prompt: Enhanced image prompt
            slide_number: Slide number for filename
            output_dir: Directory to save image

        Returns:
            Path to saved image, or None if generation fails
        """
        try:
            # Try to generate an image using the configured Gemini model.
            response = self.model.generate_content(prompt)

            image_bytes = None
            try:
                # Look for inline image data in the first candidate
                candidate = response.candidates[0]
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", []) if content is not None else []
                for part in parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        image_bytes = inline.data
                        break
            except Exception:
                image_bytes = None

            if image_bytes:
                try:
                    image = Image.open(io.BytesIO(image_bytes))
                except Exception:
                    image = self._create_placeholder_image(prompt, slide_number)
            else:
                image = self._create_placeholder_image(prompt, slide_number)

            image_path = output_dir / f"slide_{slide_number:02d}.png"
            image.save(image_path, "PNG")
            return image_path

        except Exception as e:
            print(f"Error generating image for slide {slide_number}: {e}")
            try:
                image = self._create_placeholder_image(prompt, slide_number)
                image_path = output_dir / f"slide_{slide_number:02d}.png"
                image.save(image_path, "PNG")
                return image_path
            except Exception as inner_e:
                print(f"Error saving placeholder image for slide {slide_number}: {inner_e}")
                return None

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
