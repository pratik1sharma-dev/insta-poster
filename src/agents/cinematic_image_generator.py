import io
import logging
from pathlib import Path
from typing import List, Optional

from PIL import Image

from src.agents.content_generator import ContentGenerator
from src.agents.image_validator import ImageValidator
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
        self.validator = ImageValidator(settings.gemini_api_key, settings.gemini_model)

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
            scene_negative = scene.get("negative_prompt", "")
            negative_prompt = (
                f"{self.settings.sd_negative_prompt}, {scene_negative}"
                if scene_negative
                else self.settings.sd_negative_prompt
            )
            logger.info(
                "[Cinematic Image %d/%d] Generating via %s...", i, len(scenes), self.provider
            )
            logger.info("[Cinematic Image %d/%d] Prompt: %s", i, len(scenes), prompt)

            max_attempts = 2
            path = None
            best_path = None
            best_score = -1

            for attempt in range(1, max_attempts + 1):
                try:
                    if self.provider == "replicate":
                        path = self._generate_replicate_image(prompt, i, output_dir)
                    elif self.provider == "sd":
                        path = self._generate_sd_image(prompt, i, output_dir, negative_prompt)
                    elif self.provider == "gemini":
                        path = self._generate_gemini_image(prompt, i, output_dir)
                    else:
                        logger.error("Unsupported image provider: %s", self.provider)
                        break

                    if not path:
                        raise Exception(f"Failed to generate image {i}")

                    validation = self.validator.validate(path, prompt)

                    logger.info(
                        "[Cinematic Image %d/%d] Validation - Quality: %d",
                        i,
                        len(scenes),
                        validation["quality_score"],
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

        # Pair captions with prompts so the LLM sees them together in Turn 2
        paired_text = "\n\n".join(
            f"Scene {i + 1}:\n"
            f"  Caption: {' | '.join(scenes[i]['lines'])}\n"
            f"  Initial prompt: {initial_prompts[i]}"
            for i in range(num_scenes)
        )

        system_prompt = (
            "You are an expert Stable Diffusion prompt engineer for cinematic 9:16 portrait reels.\n"
            f"Channel: {channel_config.name}\n"
            f"Theme: {channel_config.theme}\n"
            f"Audience: {channel_config.target_audience}\n"
            + (f"Cultural Context: {channel_config.cultural_context}\n" if channel_config.cultural_context else "")
            + "\nUNIVERSAL SD RULES — always apply:\n"
            "• NEVER use hands as the main close-up subject\n"
            "• NEVER ask for screen content (dashboards, spreadsheets, readable numbers)\n"
            "• All images are 9:16 portrait, photorealistic, cinematic — no text or watermarks in the scene\n"
            "• Include specific lighting: rim lighting, golden hour, soft box, chiaroscuro, volumetric light\n"
            "• Include cinematic depth: shallow depth of field, bokeh, foreground element for layering"
        )

        # ── Turn 1: derive SD render guidance for this channel + topic ─────
        turn1_prompt = (
            f"Story topic: {strategy.topic}\n\n"
            f"SCENES:\n{paired_text}\n\n"
            "Based on this channel's theme and audience, briefly describe:\n"
            "1. Environments, objects, and moods SD renders well for this content\n"
            "2. What to avoid (SD failure modes specific to this content type)\n"
            "3. ONE recurring visual element for continuity across all scenes\n"
            "   — Good anchors: a person, a room, a specific object (coffee cup, notebook, plant)\n"
            "   — BAD anchors: whiteboards, screens, books — anything that invites readable text\n"
            "   — The anchor must work as a background element, not the main subject requiring text\n\n"
            "5-8 bullet points per section. No JSON needed."
        )

        messages = [{"role": "user", "content": turn1_prompt}]
        turn1_response = self.generator._generate_conversation(messages, system_prompt=system_prompt)
        logger.debug("SD render context (Turn 1): %s", turn1_response)

        # ── Turn 2: refine prompts using Turn 1 guidance ──────────────────
        turn2_prompt = (
            f"Now refine these {num_scenes} image prompts using your guidance above.\n\n"
            f"SCENES (caption paired with its initial image prompt):\n{paired_text}\n\n"
            "CRITICAL rules:\n"
            "1. The caption is the TEXT OVERLAY — the image is the BACKGROUND. They don't need to match literally.\n"
            "2. Keep the initial prompt's subject unless you have a strong creative reason to change it\n"
            "3. Fix SD-specific issues: remove readable text references, replace screen content with atmospheric equivalents\n"
            "4. Add the recurring visual element naturally without overwhelming the scene\n"
            "5. Choose shot type to match the emotional beat of the scene (close-up for tension/intimacy, wide for scale/revelation)\n"
            "\n"
            f'Return JSON:\n'
            f'{{\n'
            f'  "refined_prompts": ["positive prompt for scene 1", ...],\n'
            f'  "negative_prompts": ["scene-specific negatives for scene 1", ...]\n'
            f'}}\n'
            f"Exactly {num_scenes} entries in each list. JSON only.\n\n"
            f"For negative_prompts: add what specifically could go wrong for that scene "
            f"(e.g. 'deformed face, extra limbs' for person scenes, 'hands visible, person in frame' "
            f"for object scenes, 'text on signs, readable labels' for environment scenes). "
            f"Do not repeat the universal negatives already applied — only scene-specific ones."
        )

        messages.append({"role": "assistant", "content": turn1_response})
        messages.append({"role": "user", "content": turn2_prompt})

        try:
            turn2_response = self.generator._generate_conversation(messages, system_prompt=system_prompt)
            data = self.generator._parse_json_response(turn2_response)
            refined = data.get("refined_prompts", [])

            negatives = data.get("negative_prompts", [])
            if len(refined) == num_scenes:
                logger.info("=" * 60)
                logger.info("SD PROMPTS REFINED:")
                for i, p in enumerate(refined, 1):
                    logger.info("%d. %s", i, p[:130])
                    if i <= len(negatives):
                        logger.info("   NEG: %s", negatives[i - 1][:100])
                logger.info("=" * 60)
                for i, p in enumerate(refined):
                    scenes[i]["image_prompt"] = p
                    scenes[i]["negative_prompt"] = negatives[i] if i < len(negatives) else ""
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

    def _generate_sd_image(self, prompt: str, index: int, output_dir: Path, negative_prompt: str = "") -> Optional[Path]:
        # 640x1120 at 20 steps ≈ same compute as 768x1344 at 15 steps, better quality
        gen_w, gen_h = 640, 1120
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
            negative_prompt=negative_prompt or self.settings.sd_negative_prompt,
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

