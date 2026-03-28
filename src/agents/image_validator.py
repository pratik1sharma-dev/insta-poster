import json
import logging
import re
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class ImageValidator:
    """
    Validates generated images using Gemini vision.
    Falls back to basic file/dimension checks if vision is unavailable.
    """

    def __init__(self, gemini_api_key: str, gemini_model: str):
        self._client = None
        self._model = gemini_model
        if gemini_api_key:
            from google import genai as genai_client
            self._client = genai_client.Client(api_key=gemini_api_key)

    def validate(
        self,
        image_path: Path,
        original_prompt: str,
    ) -> dict:
        """
        Validate a generated image for quality and watermarks.

        Returns:
            quality_score: 0-100
            regenerate: bool
            issues: list[str]
        """
        try:
            image_data = Path(image_path).read_bytes()
            validation_prompt = f"""Analyze this cinematic image for quality control.

ORIGINAL PROMPT: {original_prompt}

Evaluate the image and respond in JSON format:
{{
  "has_text_or_watermarks": true/false,
  "overall_quality": 0-100,
  "issues": ["list any specific problems: blur, artifacts, bad composition, watermarks"],
  "overall_assessment": "one sentence summary"
}}

Score overall_quality as a single holistic judgment:
- 90+: cinematic, sharp, great composition, no artifacts
- 70-89: acceptable for social media with minor issues
- below 70: regenerate — blurry, heavy artifacts, or distracting problems

Be strict but fair. Garbled AI text artifacts on screens/documents do NOT count as watermarks."""

            result = self._call_vision(image_data, validation_prompt)
            if result:
                return self._parse(result)

            logger.warning("Vision model unavailable, using basic validation")
            return self._basic_validate(image_path)

        except Exception as e:
            logger.error("Image validation failed: %s", e)
            return {"quality_score": 75, "regenerate": False, "issues": [str(e)]}

    def _call_vision(self, image_data: bytes, prompt: str) -> Optional[str]:
        if not self._client:
            return None
        try:
            from google.genai import types
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=image_data, mime_type="image/png"),
                            types.Part.from_text(text=prompt),
                        ],
                    )
                ],
            )
            return response.text
        except Exception as e:
            logger.warning("Vision model call failed: %s", e)
            return None

    def _parse(self, response_text: str) -> dict:
        try:
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")
            data = json.loads(json_match.group(0))

            quality_score = int(data.get("overall_quality", 75))
            issues = list(data.get("issues", []))
            if data.get("has_text_or_watermarks"):
                issues.append("Text or watermarks detected")

            return {
                "quality_score": quality_score,
                "regenerate": quality_score < 70,
                "issues": issues,
            }
        except Exception as e:
            logger.warning("Failed to parse validation response: %s", e)
            return {"quality_score": 75, "regenerate": False, "issues": ["Parse error"]}

    def _basic_validate(self, image_path: Path) -> dict:
        """Fallback: file size, dimensions, aspect ratio checks."""
        try:
            img = Image.open(image_path)
            width, height = img.size
            file_size = image_path.stat().st_size

            issues = []
            quality_score = 80

            if abs(width / height - 9 / 16) > 0.05:
                issues.append(f"Aspect ratio off: {width/height:.2f} vs 0.5625")
                quality_score -= 10
            if file_size < 50_000:
                issues.append("File size unusually small")
                quality_score -= 15
            if width < 800 or height < 1400:
                issues.append(f"Resolution too low: {width}x{height}")
                quality_score -= 10

            return {
                "quality_score": max(0, quality_score),
                "regenerate": quality_score < 60,
                "issues": issues,
            }
        except Exception as e:
            logger.error("Basic validation failed: %s", e)
            return {"quality_score": 70, "regenerate": False, "issues": [str(e)]}
