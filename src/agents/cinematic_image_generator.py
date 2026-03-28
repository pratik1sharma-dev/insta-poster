import io
import logging
import re
from pathlib import Path
from typing import List, Optional

from PIL import Image

from src.agents.content_generator import ContentGenerator
from src.agents.image_providers import (
    call_gemini_image_api,
    call_replicate_api,
    call_sd_api,
    download_image_url,
)

logger = logging.getLogger(__name__)


class CinematicImageGenerator:
    """
    Generates cinematic 9:16 images for reel scenes and refines SD prompts.

    Provider methods delegate to the shared helpers in src.agents.image_providers.
    """

    def __init__(self, generator: ContentGenerator):
        from src.config import settings

        self.generator = generator
        self.provider = settings.image_provider.lower()
        self.settings = settings
        self._sd_messages: list = []
        self._sd_system_prompt: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_images(self, scenes: List[dict], output_dir: Path) -> List[dict]:
        """
        Generate a 9:16 cinematic image for each scene.

        Populates ``scene["image_path"]`` for every scene and returns the
        (mutated) scenes list.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        for i, scene in enumerate(scenes, 1):
            prompt = scene["image_prompt"]
            logger.info(
                "[Cinematic Image %d/%d] Generating via %s...", i, len(scenes), self.provider
            )
            logger.info("[Cinematic Image %d/%d] Prompt: %s", i, len(scenes), prompt)

            visual_anchor = scene.get("visual_anchor", "")
            max_attempts = 2
            path = None
            best_path = None
            best_score = -1

            for attempt in range(1, max_attempts + 1):
                try:
                    if self.provider == "replicate":
                        path = self._generate_replicate_image(prompt, i, output_dir)
                    elif self.provider == "sd":
                        path = self._generate_sd_image(prompt, i, output_dir)
                    elif self.provider == "gemini":
                        path = self._generate_gemini_image(prompt, i, output_dir)
                    else:
                        logger.error("Unsupported image provider: %s", self.provider)
                        break

                    if not path:
                        raise Exception(f"Failed to generate image {i}")

                    validation = self._validate_image_quality(path, visual_anchor, prompt)

                    logger.info(
                        "[Cinematic Image %d/%d] Validation - Quality: %d, Has Anchor: %s",
                        i,
                        len(scenes),
                        validation["quality_score"],
                        validation["has_visual_anchor"],
                    )

                    if validation["issues"]:
                        logger.warning(
                            "[Cinematic Image %d/%d] Issues detected: %s",
                            i,
                            len(scenes),
                            ", ".join(validation["issues"]),
                        )

                    # Track best attempt — retry can produce worse results
                    if validation["quality_score"] > best_score:
                        best_score = validation["quality_score"]
                        best_path = path

                    if validation["regenerate"] and attempt < max_attempts:
                        logger.warning(
                            "[Cinematic Image %d/%d] Quality insufficient (score: %d). "
                            "Regenerating (attempt %d/%d)...",
                            i,
                            len(scenes),
                            validation["quality_score"],
                            attempt + 1,
                            max_attempts,
                        )
                        refined_prompt = self._refine_prompt_from_issues(
                            prompt, validation["issues"], scene_index=i
                        )
                        logger.info(
                            "[Cinematic Image %d/%d] Refined prompt: %s",
                            i,
                            len(scenes),
                            refined_prompt,
                        )
                        prompt = refined_prompt
                        continue

                    break

                except Exception as e:
                    logger.error(
                        "[Cinematic Image %d/%d] Attempt %d failed: %s", i, len(scenes), attempt, e
                    )
                    if attempt == max_attempts and best_path is None:
                        raise RuntimeError(
                            f"Image {i}/{len(scenes)} failed after {max_attempts} attempts: {e}"
                        )

            # Use best attempt, not necessarily last
            scene["image_path"] = best_path or path
            if best_score < 70:
                logger.warning(
                    "[Cinematic Image %d/%d] Using best available image (score: %d)",
                    i,
                    len(scenes),
                    best_score,
                )
            else:
                logger.info(
                    "[Cinematic Image %d/%d] Quality validated (score: %d)",
                    i,
                    len(scenes),
                    best_score,
                )

        return scenes

    def refine_sd_prompts(
        self,
        scenes: List[dict],
        strategy,
        channel_config,
    ) -> List[dict]:
        """
        Two-turn conversation to rewrite image prompts for Stable Diffusion quality.

        Turn 1 — LLM derives channel/topic-specific SD render guidance.
        Turn 2 — LLM rewrites all prompts using its own Turn 1 analysis.
        Falls back to the original prompts on failure.
        """
        num_scenes = len(scenes)
        initial_prompts = [sc["image_prompt"] for sc in scenes]

        lines_text = "\n".join(
            f"Scene {i + 1} ({scenes[i]['motion']}): {' | '.join(scenes[i]['lines'])}"
            for i in range(num_scenes)
        )
        initial_text = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(initial_prompts))

        system_prompt = (
            "You are an expert Stable Diffusion prompt engineer for cinematic 9:16 portrait reels.\n"
            f"Channel: {channel_config.name}\n"
            f"Theme: {channel_config.theme}\n"
            f"Audience: {channel_config.target_audience}\n"
            + (f"Cultural Context: {channel_config.cultural_context}\n" if channel_config.cultural_context else "")
            + "\nUNIVERSAL SD RULES — always apply:\n"
            "• NEVER use hands as the main close-up subject\n"
            "• NEVER ask for screen content (dashboards, spreadsheets, readable numbers)\n"
            "• Vary shot types: extreme close-up / close-up / medium / wide\n"
            '• End every prompt with: "35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"'
        )

        # ── Turn 1: derive SD render guidance for this channel + topic ─────
        turn1_prompt = (
            f"Story topic: {strategy.topic}\n\n"
            f"SCENES:\n{lines_text}\n\n"
            "Based on this channel's theme and audience, briefly describe:\n"
            "1. Environments, objects, and moods SD renders well for this content\n"
            "2. What to avoid (SD failure modes specific to this content type)\n"
            "3. ONE recurring visual element to use across all scenes for continuity\n\n"
            "5-8 bullet points per section. No JSON needed."
        )

        messages = [{"role": "user", "content": turn1_prompt}]
        turn1_response = self.generator._generate_conversation(messages, system_prompt=system_prompt)
        logger.debug("SD render context (Turn 1): %s", turn1_response)

        # ── Turn 2: rewrite prompts using Turn 1 guidance ──────────────────
        turn2_prompt = (
            f"Now rewrite these {num_scenes} image prompts using your guidance above.\n\n"
            f"INITIAL PROMPTS:\n{initial_text}\n\n"
            "Requirements:\n"
            "1. Apply the render guidance from above\n"
            "2. Vary shot types across scenes\n"
            "3. Include the recurring visual element for continuity\n"
            '4. End every prompt with: "35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"\n\n'
            f'Return JSON: {{"refined_prompts": ["full prompt 1", "full prompt 2", ...]}}\n'
            f"Exactly {num_scenes} prompts. JSON only."
        )

        messages.append({"role": "assistant", "content": turn1_response})
        messages.append({"role": "user", "content": turn2_prompt})

        try:
            turn2_response = self.generator._generate_conversation(messages, system_prompt=system_prompt)
            data = self.generator._parse_json_response(turn2_response)
            refined = data.get("refined_prompts", [])

            if len(refined) == num_scenes:
                logger.info("=" * 60)
                logger.info("SD PROMPTS REFINED:")
                for i, p in enumerate(refined, 1):
                    logger.info("%d. %s", i, p[:130])
                logger.info("=" * 60)
                for i, p in enumerate(refined):
                    scenes[i]["image_prompt"] = p
                # Persist session for retry turns during image generation
                messages.append({"role": "assistant", "content": turn2_response})
                self._sd_messages = messages
                self._sd_system_prompt = system_prompt
                return scenes

            logger.warning(
                "SD prompt refinement returned wrong count (%d vs %d) — using initial prompts",
                len(refined), num_scenes,
            )
        except Exception as e:
            logger.warning("SD prompt refinement failed (%s) — using initial prompts", e)

        return scenes

    # ------------------------------------------------------------------
    # Provider methods (delegate to image_providers)
    # ------------------------------------------------------------------

    def _generate_replicate_image(
        self, prompt: str, index: int, output_dir: Path
    ) -> Optional[Path]:
        model = getattr(self.settings, "replicate_model", "ideogram-ai/ideogram-v2")
        url = call_replicate_api(
            model,
            {
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "style": "cinematic",
            },
        )
        image_bytes = download_image_url(url)
        p = output_dir / f"image_{index:02d}.png"
        p.write_bytes(image_bytes)
        return p

    def _generate_sd_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        # Generate at lower resolution for speed on Mac hardware, then upscale
        gen_w, gen_h = 768, 1344
        target_w, target_h = 1080, 1920

        logger.info(
            "SD Generation: %dx%d -> Up-scaling to %dx%d", gen_w, gen_h, target_w, target_h
        )

        image_bytes = call_sd_api(
            api_url=self.settings.sd_api_url,
            timeout=self.settings.sd_timeout,
            prompt=prompt,
            width=gen_w,
            height=gen_h,
            steps=self.settings.sd_steps,
            negative_prompt=self.settings.sd_negative_prompt,
            cfg_scale=7,
            sampler_name="DPM++ 2M Karras",
        )

        img = Image.open(io.BytesIO(image_bytes))
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

        p = output_dir / f"image_{index:02d}.png"
        img.save(p, "PNG")
        return p

    def _generate_gemini_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        image_bytes = call_gemini_image_api(
            prompt=prompt,
            model=self.settings.gemini_image_model,
            api_key=self.settings.gemini_api_key,
        )

        if not image_bytes:
            return None

        img = Image.open(io.BytesIO(image_bytes))

        # Crop to 9:16 if Gemini returned a different aspect ratio
        w, h = img.size
        target_ratio = 9 / 16
        current_ratio = w / h

        if current_ratio > target_ratio:
            # Too wide — crop horizontally
            new_w = h * target_ratio
            left = (w - new_w) / 2
            img = img.crop((left, 0, left + new_w, h))
        elif current_ratio < target_ratio:
            # Too tall — crop vertically
            new_h = w / target_ratio
            top = (h - new_h) / 2
            img = img.crop((0, top, w, top + new_h))

        p = output_dir / f"image_{index:02d}.png"
        img.save(p, "PNG")
        return p

    # ------------------------------------------------------------------
    # Image quality validation
    # ------------------------------------------------------------------

    def _validate_image_quality(
        self,
        image_path: Path,
        visual_anchor: str,
        original_prompt: str,
    ) -> dict:
        """
        Use a vision model (Gemini) to analyse generated images.

        Returns a dict with:
            - quality_score: 0-100
            - has_visual_anchor: bool
            - regenerate: bool
            - issues: list[str]
        """
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()

            validation_prompt = f"""Analyze this cinematic image for quality control.

EXPECTED VISUAL ANCHOR: {visual_anchor}
ORIGINAL PROMPT: {original_prompt}

Evaluate the image on these criteria and provide scores:

1. **Visual Anchor Present** (Yes/No): Is '{visual_anchor}' clearly visible in the image?

2. **Technical Quality** (0-100):
   - Sharpness: Is the image crisp and in focus, or blurry?
   - Composition: Is the framing and arrangement visually pleasing?
   - Artifacts: Are there any visual glitches, distortions, or AI artifacts?

3. **Watermarks/Logos** (Yes/No): Are there any real watermarks, brand logos, or readable captions overlaid ON the image (e.g. Shutterstock, Getty, site URLs)?
   NOTE: Garbled/illegible AI text artifacts on phone screens, documents, or newspapers in the scene do NOT count — only flag actual overlaid watermarks or logos.

4. **Cinematic Style** (0-100): Does it have a cinematic, film-like quality with proper lighting and mood?

Respond in JSON format:
{{
  "visual_anchor_present": true/false,
  "technical_quality": 0-100,
  "cinematic_style": 0-100,
  "has_text_or_watermarks": true/false,
  "sharpness_notes": "description of sharpness/blur issues if any",
  "composition_notes": "description of composition issues if any",
  "artifact_notes": "description of visual artifacts if any",
  "overall_assessment": "brief summary"
}}

Be strict but fair. If the image is acceptable for social media, scores should be 70+."""

            result = self._call_vision_model(image_data, validation_prompt)

            if result:
                return self._parse_validation_response(result)
            else:
                logger.warning("Vision model unavailable, using basic validation")
                return self._basic_image_validation(image_path)

        except Exception as e:
            logger.error("Image validation failed: %s", e)
            return {
                "quality_score": 75,
                "has_visual_anchor": True,
                "regenerate": False,
                "issues": [f"Validation error: {str(e)}"],
            }

    def _call_vision_model(self, image_data: bytes, prompt: str) -> Optional[str]:
        """Call Gemini vision API to analyse the image."""
        try:
            if self.settings.gemini_api_key:
                from google import genai as genai_client
                from google.genai import types

                client = genai_client.Client(api_key=self.settings.gemini_api_key)

                response = client.models.generate_content(
                    model=self.settings.gemini_model,
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

            return None

        except Exception as e:
            logger.warning("Vision model call failed: %s", e)
            return None

    def _parse_validation_response(self, response_text: str) -> dict:
        """Parse the vision model JSON response into a validation result dict."""
        import json

        try:
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
            else:
                raise ValueError("No JSON found in response")

            technical = data.get("technical_quality", 75)
            cinematic = data.get("cinematic_style", 75)
            quality_score = int((technical * 0.6) + (cinematic * 0.4))

            has_visual_anchor = data.get("visual_anchor_present", True)
            has_text = data.get("has_text_or_watermarks", False)

            issues = []
            if not has_visual_anchor:
                issues.append("Visual anchor not found")
            if has_text:
                issues.append("Text or watermarks detected")
            if technical < 70:
                if data.get("sharpness_notes"):
                    issues.append(f"Sharpness: {data['sharpness_notes']}")
                if data.get("composition_notes"):
                    issues.append(f"Composition: {data['composition_notes']}")
                if data.get("artifact_notes"):
                    issues.append(f"Artifacts: {data['artifact_notes']}")

            regenerate = quality_score < 70 or (has_text and quality_score < 75)
            if not has_visual_anchor and quality_score >= 70:
                logger.info(
                    "Visual anchor not detected but quality acceptable (score: %d), skipping regen",
                    quality_score,
                )
            if has_text and not regenerate:
                logger.info(
                    "Text/watermark flagged but quality acceptable (score: %d), skipping regen",
                    quality_score,
                )

            return {
                "quality_score": quality_score,
                "has_visual_anchor": has_visual_anchor,
                "regenerate": regenerate,
                "issues": issues,
            }

        except Exception as e:
            logger.warning("Failed to parse validation response: %s", e)
            return {
                "quality_score": 75,
                "has_visual_anchor": True,
                "regenerate": False,
                "issues": ["Parse error in validation"],
            }

    def _basic_image_validation(self, image_path: Path) -> dict:
        """Basic validation without a vision model (file size, dimensions, aspect ratio)."""
        try:
            img = Image.open(image_path)
            width, height = img.size

            aspect_ratio = width / height
            expected_ratio = 9 / 16
            ratio_diff = abs(aspect_ratio - expected_ratio)

            file_size = image_path.stat().st_size

            issues = []
            quality_score = 80

            if ratio_diff > 0.05:
                issues.append(f"Aspect ratio off: {aspect_ratio:.2f} vs {expected_ratio:.2f}")
                quality_score -= 10

            if file_size < 50000:  # Less than 50 KB
                issues.append("File size unusually small, may indicate generation issue")
                quality_score -= 15

            if width < 800 or height < 1400:
                issues.append(f"Resolution too low: {width}x{height}")
                quality_score -= 10

            return {
                "quality_score": max(0, quality_score),
                "has_visual_anchor": True,  # Cannot verify without vision model
                "regenerate": quality_score < 60,
                "issues": issues,
            }

        except Exception as e:
            logger.error("Basic validation failed: %s", e)
            return {
                "quality_score": 70,
                "has_visual_anchor": True,
                "regenerate": False,
                "issues": [f"Validation error: {str(e)}"],
            }

    # ------------------------------------------------------------------
    # Prompt utilities
    # ------------------------------------------------------------------

    def _refine_prompt_from_issues(
        self, original_prompt: str, issues: List[str], scene_index: int = 1
    ) -> str:
        """
        Turn 3 in the SD session: ask the LLM to fix the prompt given the detected issues.
        Falls back to the original prompt if the session isn't available or the call fails.
        """
        if not self._sd_messages:
            logger.warning("SD session unavailable for prompt refinement — using original prompt")
            return original_prompt

        turn3_prompt = (
            f"Scene {scene_index} image had quality issues after generation:\n"
            f"Issues detected: {', '.join(issues)}\n\n"
            f"Prompt that was used:\n{original_prompt}\n\n"
            "Rewrite this single prompt to fix the detected issues, applying your SD render guidance above. "
            "Return the rewritten prompt text only — no JSON, no explanation."
        )

        messages = self._sd_messages + [{"role": "user", "content": turn3_prompt}]
        try:
            refined = self.generator._generate_conversation(messages, system_prompt=self._sd_system_prompt)
            logger.debug("Refined prompt (Turn 3): %s", refined)
            return refined.strip()
        except Exception as e:
            logger.warning("Prompt refinement Turn 3 failed (%s) — using original prompt", e)
            return original_prompt

