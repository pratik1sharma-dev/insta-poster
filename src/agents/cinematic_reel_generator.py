import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
import time
import requests
import base64
import io
import textwrap
import asyncio

from src.models import ContentStrategy, ChannelConfig, GeneratedContent
from src.agents.content_generator import ContentGenerator
from src.config import settings
from PIL import Image

logger = logging.getLogger(__name__)

class CinematicReelGenerator:
    """
    Generates a cinematic mood Reel:
    - AI-generated background images (9:16, no text)
    - High-impact 'spiky' captions overlaid
    - Moody background music
    - No narration (mood film style)
    """
    REEL_W = 1080
    REEL_H = 1920
    FPS    = 25

    STORY_FORMATS = {
        'contrast': {
            'structure': ['setup', 'context', 'insight', 'takeaway'],
            'description': 'Compare two approaches showing difference',
            'best_for': 'financial comparisons, decision frameworks'
        },
        'timeline': {
            'structure': ['past', 'inflection', 'present', 'future'],
            'description': 'Historical progression to future prediction',
            'best_for': 'market trends, technological evolution'
        },
        'myth_buster': {
            'structure': ['common_belief', 'why_it_exists', 'the_truth', 'what_to_do'],
            'description': 'Debunk misconception with evidence',
            'best_for': 'investment myths, behavioral psychology'
        },
        'case_study': {
            'structure': ['situation', 'decision', 'outcome', 'lesson'],
            'description': 'Real example with concrete results',
            'best_for': 'success stories, cautionary tales'
        }
    }

    def __init__(self):
        self.generator = ContentGenerator()
        self.temp_dir  = Path("temp_cinematic")
        self.temp_dir.mkdir(exist_ok=True)
        self.provider = settings.image_provider.lower()

    def generate(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        output_path: Path,
        num_images: int = 4,
        with_voice: bool = False,
    ) -> Path:
        """
        Full pipeline: generate script → generate 9:16 images →
        overlay text → (optional voice) → blend → music.

        Args:
            with_voice: If True, adds voiceover narration to the reel
        """
        logger.info("Starting Cinematic Reel: %s (voice=%s)", strategy.topic, with_voice)

        # 1. Generate Story Lines + initial image prompts
        lines, initial_prompts = self._generate_script_and_prompts(
            strategy, channel_config, num_images
        )

        # 1b. Refine image prompts via dedicated SD-optimized AI call
        prompts = self._refine_sd_prompts(lines, initial_prompts, strategy, num_images)

        # 2. Generate Cinematic Images (9:16)
        image_dir = self.temp_dir / "images"
        image_dir.mkdir(exist_ok=True)
        image_paths = self._generate_cinematic_images(prompts, image_dir)

        # 3. Generate Voice (if enabled)
        audio_paths = None
        if with_voice:
            audio_dir = self.temp_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_paths = self._generate_voice(lines, audio_dir, channel_config)

        # 4. Build Clips with Text Overlays (and optional voice)
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)

        slide_duration = getattr(settings, "cinematic_slide_duration", 4.0)
        transition_dur = getattr(settings, "cinematic_transition_duration", 0.6)

        clip_paths = self._build_cinematic_clips(
            image_paths, lines, video_dir, slide_duration, transition_dur, audio_paths
        )

        # 5. Blend Clips
        blended = self._blend_clips(clip_paths, video_dir, transition_dur)

        # 6. Add Music
        # Lower music volume if voice is present
        music_volume = getattr(settings, "cinematic_music_volume", 0.08 if with_voice else 0.15)
        self._mix_music(blended, output_path, music_volume)

        logger.info("Cinematic Reel complete: %s", output_path)
        return output_path

    def cleanup(self):
        """Remove all temporary files."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # ------------------------------------------------------------------
    # Image Generation
    # ------------------------------------------------------------------

    def _generate_cinematic_images(self, prompts: List[str], output_dir: Path) -> List[Path]:
        """Generate 9:16 cinematic images using the configured provider with quality validation."""
        image_paths = []

        for i, prompt in enumerate(prompts, 1):
            logger.info("[Cinematic Image %d/%d] Generating via %s...", i, len(prompts), self.provider)
            logger.info("[Cinematic Image %d/%d] Prompt: %s", i, len(prompts), prompt)

            # Extract visual anchor from prompt for validation
            visual_anchor = self._extract_visual_anchor(prompt)

            # Try generating with quality validation (max 2 attempts)
            max_attempts = 2
            path = None

            for attempt in range(1, max_attempts + 1):
                try:
                    # Generate the image
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

                    # Validate image quality
                    validation = self._validate_image_quality(path, visual_anchor, prompt)

                    logger.info(
                        "[Cinematic Image %d/%d] Validation - Quality: %d, Has Anchor: %s",
                        i, len(prompts), validation['quality_score'], validation['has_visual_anchor']
                    )

                    if validation['issues']:
                        logger.warning(
                            "[Cinematic Image %d/%d] Issues detected: %s",
                            i, len(prompts), ', '.join(validation['issues'])
                        )

                    # Check if regeneration is needed
                    if validation['regenerate'] and attempt < max_attempts:
                        logger.warning(
                            "[Cinematic Image %d/%d] Quality insufficient (score: %d). Regenerating (attempt %d/%d)...",
                            i, len(prompts), validation['quality_score'], attempt + 1, max_attempts
                        )

                        # Refine prompt based on issues
                        refined_prompt = self._refine_prompt_from_issues(prompt, validation['issues'])
                        logger.info("[Cinematic Image %d/%d] Refined prompt: %s", i, len(prompts), refined_prompt)
                        prompt = refined_prompt
                        continue

                    # Quality is acceptable or we've exhausted attempts
                    if validation['quality_score'] < 70:
                        logger.warning(
                            "[Cinematic Image %d/%d] Using image with quality score %d (below threshold)",
                            i, len(prompts), validation['quality_score']
                        )
                    else:
                        logger.info(
                            "[Cinematic Image %d/%d] ✓ Quality validated (score: %d)",
                            i, len(prompts), validation['quality_score']
                        )

                    image_paths.append(path)
                    break

                except Exception as e:
                    logger.error("[Cinematic Image %d/%d] Attempt %d failed: %s", i, len(prompts), attempt, e)
                    if attempt == max_attempts:
                        raise RuntimeError(
                            f"Image {i}/{len(prompts)} failed after {max_attempts} attempts: {e}"
                        )

        return image_paths

    def _generate_replicate_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        import replicate
        model = getattr(settings, "replicate_model", "ideogram-ai/ideogram-v2")
        
        output = replicate.run(
            model,
            input={
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "style": "cinematic"
            }
        )
        url = output[0] if isinstance(output, list) else str(output)
        
        res = requests.get(url, timeout=60)
        if res.status_code == 200:
            p = output_dir / f"image_{index:02d}.png"
            with open(p, "wb") as f:
                f.write(res.content)
            return p
        return None

    def _generate_sd_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        # Generate at lower resolution (768x1344) for speed on Mac hardware, then upscale
        gen_w, gen_h = 768, 1344
        target_w, target_h = 1080, 1920

        payload = {
            "prompt":          prompt,
            "negative_prompt": settings.sd_negative_prompt,
            "steps":           settings.sd_steps,
            "width":           gen_w,
            "height":          gen_h,
            "sampler_name":    "DPM++ 2M Karras",
            "cfg_scale":       7,
        }

        logger.info("SD Generation: %dx%d -> Up-scaling to %dx%d", gen_w, gen_h, target_w, target_h)
        response = requests.post(settings.sd_api_url, json=payload, timeout=settings.sd_timeout)
        response.raise_for_status()
        r = response.json()

        image_data = base64.b64decode(r['images'][0])
        p = output_dir / f"image_{index:02d}.png"

        # Load and upscale using Pillow
        img = Image.open(io.BytesIO(image_data))
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

        img.save(p, "PNG")
        return p

    def _generate_gemini_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        from google import genai as genai_client
        from google.genai import types
        
        client = genai_client.Client(api_key=settings.gemini_api_key)
        
        # Gemini often requires 1:1 or specific aspect ratios; for 9:16 we might need to crop
        # or hope the model supports it. Using 1:1 and then cropping is safer if 9:16 isn't supported.
        response = client.models.generate_content(
            model=settings.gemini_image_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"]
            ),
        )
        
        image_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                break
        
        if not image_bytes:
            return None

        img = Image.open(io.BytesIO(image_bytes))
        # If Gemini gave 1:1, we crop to 9:16 aspect ratio (center crop)
        w, h = img.size
        target_ratio = 9/16
        current_ratio = w/h
        
        if current_ratio > target_ratio:
            # Too wide
            new_w = h * target_ratio
            left = (w - new_w) / 2
            img = img.crop((left, 0, left + new_w, h))
        elif current_ratio < target_ratio:
            # Too tall
            new_h = w / target_ratio
            top = (h - new_h) / 2
            img = img.crop((0, top, w, top + new_h))

        p = output_dir / f"image_{index:02d}.png"
        img.save(p, "PNG")
        return p

    # ------------------------------------------------------------------
    # Image Quality Validation
    # ------------------------------------------------------------------

    def _validate_image_quality(
        self,
        image_path: Path,
        visual_anchor: str,
        original_prompt: str
    ) -> dict:
        """
        Use a vision model (Gemini or Claude) to analyze generated images.

        Returns:
            dict with:
                - quality_score: 0-100 based on blur, composition, artifacts
                - has_visual_anchor: bool if the expected element is present
                - regenerate: bool whether to regenerate the image
                - issues: list of detected problems
        """
        try:
            # Read the image
            with open(image_path, 'rb') as f:
                image_data = f.read()

            # Build validation prompt
            validation_prompt = f"""Analyze this cinematic image for quality control.

EXPECTED VISUAL ANCHOR: {visual_anchor}
ORIGINAL PROMPT: {original_prompt}

Evaluate the image on these criteria and provide scores:

1. **Visual Anchor Present** (Yes/No): Is '{visual_anchor}' clearly visible in the image?

2. **Technical Quality** (0-100):
   - Sharpness: Is the image crisp and in focus, or blurry?
   - Composition: Is the framing and arrangement visually pleasing?
   - Artifacts: Are there any visual glitches, distortions, or AI artifacts?

3. **Text/Watermarks** (Yes/No): Are there any text, captions, watermarks, or logos visible?

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

            # Call vision model (try Gemini first, fallback to basic checks)
            result = self._call_vision_model(image_data, validation_prompt)

            if result:
                # Parse the vision model response
                return self._parse_validation_response(result)
            else:
                # Fallback: basic validation without vision model
                logger.warning("Vision model unavailable, using basic validation")
                return self._basic_image_validation(image_path)

        except Exception as e:
            logger.error("Image validation failed: %s", e)
            # Return permissive result on error
            return {
                'quality_score': 75,
                'has_visual_anchor': True,
                'regenerate': False,
                'issues': [f"Validation error: {str(e)}"]
            }

    def _call_vision_model(self, image_data: bytes, prompt: str) -> Optional[str]:
        """Call Gemini or Claude vision API to analyze the image."""
        try:
            # Try Gemini first (preferred if available)
            if settings.gemini_api_key:
                from google import genai as genai_client
                from google.genai import types

                client = genai_client.Client(api_key=settings.gemini_api_key)

                # Call Gemini with vision
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_bytes(
                                    data=image_data,
                                    mime_type="image/png"
                                ),
                                types.Part.from_text(text=prompt)
                            ]
                        )
                    ],
                )

                return response.text

            # Could add Claude vision support here in the future
            # elif settings.claude_api_key:
            #     ...

            return None

        except Exception as e:
            logger.warning("Vision model call failed: %s", e)
            return None

    def _parse_validation_response(self, response_text: str) -> dict:
        """Parse the vision model's JSON response into validation result."""
        import json
        import re

        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
            else:
                raise ValueError("No JSON found in response")

            # Calculate overall quality score (weighted average)
            technical = data.get('technical_quality', 75)
            cinematic = data.get('cinematic_style', 75)
            quality_score = int((technical * 0.6) + (cinematic * 0.4))

            # Check if visual anchor is present
            has_visual_anchor = data.get('visual_anchor_present', True)

            # Check for text/watermarks
            has_text = data.get('has_text_or_watermarks', False)

            # Collect issues
            issues = []
            if not has_visual_anchor:
                issues.append("Visual anchor not found")
            if has_text:
                issues.append("Text or watermarks detected")
            if technical < 70:
                if data.get('sharpness_notes'):
                    issues.append(f"Sharpness: {data['sharpness_notes']}")
                if data.get('composition_notes'):
                    issues.append(f"Composition: {data['composition_notes']}")
                if data.get('artifact_notes'):
                    issues.append(f"Artifacts: {data['artifact_notes']}")

            # Decide if regeneration is needed
            regenerate = quality_score < 70 or not has_visual_anchor or has_text

            return {
                'quality_score': quality_score,
                'has_visual_anchor': has_visual_anchor,
                'regenerate': regenerate,
                'issues': issues
            }

        except Exception as e:
            logger.warning("Failed to parse validation response: %s", e)
            # Return permissive result on parse error
            return {
                'quality_score': 75,
                'has_visual_anchor': True,
                'regenerate': False,
                'issues': ["Parse error in validation"]
            }

    def _basic_image_validation(self, image_path: Path) -> dict:
        """Basic validation without vision model (checks file size, dimensions, etc)."""
        try:
            img = Image.open(image_path)
            width, height = img.size

            # Check aspect ratio
            aspect_ratio = width / height
            expected_ratio = 9 / 16
            ratio_diff = abs(aspect_ratio - expected_ratio)

            # Check file size
            file_size = image_path.stat().st_size

            issues = []
            quality_score = 80  # Start with decent score

            if ratio_diff > 0.05:
                issues.append(f"Aspect ratio off: {aspect_ratio:.2f} vs {expected_ratio:.2f}")
                quality_score -= 10

            if file_size < 50000:  # Less than 50KB
                issues.append("File size unusually small, may indicate generation issue")
                quality_score -= 15

            if width < 800 or height < 1400:
                issues.append(f"Resolution too low: {width}x{height}")
                quality_score -= 10

            return {
                'quality_score': max(0, quality_score),
                'has_visual_anchor': True,  # Can't verify without vision model
                'regenerate': quality_score < 60,
                'issues': issues
            }

        except Exception as e:
            logger.error("Basic validation failed: %s", e)
            return {
                'quality_score': 70,
                'has_visual_anchor': True,
                'regenerate': False,
                'issues': [f"Validation error: {str(e)}"]
            }

    def _extract_visual_anchor(self, prompt: str) -> str:
        """Extract the main subject/visual anchor from the image prompt."""
        import re

        # Common patterns: "Close-up of [anchor]", "Medium shot of [anchor]", etc.
        patterns = [
            r'(?:close-?up|medium shot|wide shot|extreme close-?up)\s+of\s+([^,]+)',
            r'^([^,]+?)(?:,|\s+in\s+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                anchor = match.group(1).strip()
                # Clean up common prefixes
                anchor = re.sub(r'^(a|an|the)\s+', '', anchor, flags=re.IGNORECASE)
                return anchor

        # Fallback: extract first few words
        words = prompt.split()[:5]
        return ' '.join(words)

    def _refine_prompt_from_issues(self, original_prompt: str, issues: List[str]) -> str:
        """Refine the image generation prompt based on detected quality issues."""
        refinements = []

        for issue in issues:
            issue_lower = issue.lower()

            if 'visual anchor' in issue_lower:
                refinements.append("emphasize main subject clearly in center frame")
            if 'blur' in issue_lower or 'sharpness' in issue_lower:
                refinements.append("sharp focus, high detail, crystal clear")
            if 'composition' in issue_lower:
                refinements.append("professional composition, rule of thirds")
            if 'artifact' in issue_lower:
                refinements.append("clean render, no artifacts, photorealistic quality")
            if 'text' in issue_lower or 'watermark' in issue_lower:
                refinements.append("absolutely no text, no watermarks, no logos")

        if refinements:
            # Append refinements to original prompt
            refined = f"{original_prompt}, {', '.join(refinements)}"
            return refined

        return original_prompt

    # ------------------------------------------------------------------
    # Voice Generation (TTS)
    # ------------------------------------------------------------------

    def _generate_voice(
        self,
        lines: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """Generate voiceover for each caption using TTS."""
        provider = getattr(settings, "tts_provider", "edge").lower()
        logger.info("Generating voice using provider: %s", provider)

        if provider == "elevenlabs":
            return self._tts_elevenlabs(lines, output_dir, channel_config)
        elif provider == "edge":
            return self._tts_edge(lines, output_dir, channel_config)
        else:
            return self._tts_gtts(lines, output_dir)

    def _tts_edge(
        self,
        lines: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """Microsoft Edge TTS — free, high quality."""
        try:
            import edge_tts
        except ImportError:
            logger.warning("edge-tts not installed, falling back to gTTS")
            return self._tts_gtts(lines, output_dir)

        voice = (
            getattr(channel_config, "voice_id", None)
            or getattr(settings, "edge_tts_voice", "en-IN-PrabhatNeural")
        )
        paths: List[Path] = []

        async def _gen():
            for i, text in enumerate(lines, 1):
                p = output_dir / f"audio_{i:02d}.mp3"
                await edge_tts.Communicate(text, voice).save(str(p))
                paths.append(p)
                logger.info("Edge-TTS %d: %s", i, text[:50])

        asyncio.run(_gen())
        return paths

    def _tts_gtts(self, lines: List[str], output_dir: Path) -> List[Path]:
        """Google TTS — free, basic quality."""
        try:
            from gtts import gTTS
        except ImportError:
            logger.error("gTTS not installed. Install: pip install gtts")
            return []

        paths = []
        for i, text in enumerate(lines, 1):
            p = output_dir / f"audio_{i:02d}.mp3"
            gTTS(text=text, lang="en", tld="co.in").save(str(p))
            paths.append(p)
            logger.info("gTTS %d: %s", i, text[:50])
        return paths

    def _tts_elevenlabs(
        self,
        lines: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """ElevenLabs TTS — premium, natural voices."""
        try:
            from elevenlabs import ElevenLabs
            from elevenlabs import save as el_save
        except ImportError:
            logger.warning("elevenlabs not installed, falling back to gTTS")
            return self._tts_gtts(lines, output_dir)

        api_key = getattr(settings, "elevenlabs_api_key", "")
        voice_id = (
            getattr(channel_config, "voice_id", None)
            or getattr(settings, "elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        )

        if not api_key:
            logger.warning("elevenlabs_api_key not set, falling back to gTTS")
            return self._tts_gtts(lines, output_dir)

        client = ElevenLabs(api_key=api_key)
        paths: List[Path] = []

        for i, text in enumerate(lines, 1):
            p = output_dir / f"audio_{i:02d}.mp3"
            try:
                audio = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=text,
                    model_id="eleven_multilingual_v2",
                )
                el_save(audio, str(p))
                paths.append(p)
                logger.info("ElevenLabs %d: %s", i, text[:50])
            except Exception as e:
                logger.error("ElevenLabs failed for segment %d: %s", i, e)
                # Fallback to gTTS for this segment
                from gtts import gTTS
                gTTS(text=text, lang="en", tld="co.in").save(str(p))
                paths.append(p)

        return paths

    # ------------------------------------------------------------------
    # Text Animation
    # ------------------------------------------------------------------

    def _create_kinetic_text_overlay(
        self,
        text: str,
        style: str,
        duration: float,
        index: int = 1,
        total: int = 4
    ) -> str:
        """
        Generate FFmpeg filter_complex string with kinetic text animations.

        Args:
            text: The caption text to animate
            style: Animation style - 'hook', 'main', 'number', 'insight'
            duration: Duration of the clip in seconds
            index: Current line index (1-based)
            total: Total number of lines

        Returns:
            FFmpeg filter_complex string with animations

        Animation Styles:
            - hook: Typewriter effect (reveal word-by-word)
            - main: Fade + slide from left
            - number: Scale + emphasis (zoom in slightly)
            - insight: Word-by-word reveal with pause
        """
        # Escape text for FFmpeg
        escaped_text = text.replace('\\', '\\\\').replace("'", "'\\''").replace(':', '\\:')

        # Manual text wrapping
        wrapped_lines = textwrap.wrap(text, width=28)
        wrapped_text = "\n".join(wrapped_lines)
        escaped_wrapped = wrapped_text.replace('\\', '\\\\').replace("'", "'\\''").replace(':', '\\:')

        # Animation speed configuration
        speed_multipliers = {
            'slow': 1.5,
            'medium': 1.0,
            'fast': 0.7
        }
        speed = getattr(settings, "cinematic_animation_speed", "medium")
        multiplier = speed_multipliers.get(speed, 1.0)

        # Base text style (common to all)
        base_style = (
            f"fontcolor=white:fontsize=72:"
            f"x=(w-text_w)/2:y=(h-text_h)/2+200:"
            f"box=1:boxcolor=black@0.5:boxborderw=40:"
            f"line_spacing=15:fix_bounds=1"
        )

        if style == 'hook':
            # Typewriter effect - words appear sequentially
            # Calculate timing
            words = text.split()
            word_count = len(words)
            reveal_duration = min(duration * 0.6, 2.0 * multiplier)  # 60% of duration or 2s max

            # Fade in gradually with enable expression
            # Words appear over time using alpha fade
            filter_str = (
                f"drawtext=text='{escaped_wrapped}':"
                f"{base_style}:"
                f"alpha='if(lt(t,{reveal_duration}),t/{reveal_duration},1)'"
            )
            return filter_str

        elif style == 'main':
            # Fade + slide from left
            fade_duration = 0.5 * multiplier
            slide_distance = 50

            filter_str = (
                f"drawtext=text='{escaped_wrapped}':"
                f"{base_style}:"
                f"x='if(lt(t,{fade_duration}),(w-text_w)/2-{slide_distance}*(1-t/{fade_duration}),(w-text_w)/2)':"
                f"alpha='if(lt(t,{fade_duration}),t/{fade_duration},1)'"
            )
            return filter_str

        elif style == 'number':
            # Scale + emphasis (zoom in slightly with bounce)
            scale_duration = 0.4 * multiplier
            max_scale = 1.15

            # Scale from max_scale down to 1.0 with bounce effect
            filter_str = (
                f"drawtext=text='{escaped_wrapped}':"
                f"fontcolor=white:"
                f"fontsize='72*if(lt(t,{scale_duration}),1+{max_scale-1}*(1-t/{scale_duration}),1)':"
                f"x=(w-text_w)/2:y=(h-text_h)/2+200:"
                f"box=1:boxcolor=black@0.5:boxborderw=40:"
                f"line_spacing=15:fix_bounds=1:"
                f"alpha='if(lt(t,0.2),t/0.2,1)'"
            )
            return filter_str

        elif style == 'insight':
            # Word-by-word reveal with slight pause
            words = text.split()
            word_count = len(words)
            reveal_duration = min(duration * 0.7, 2.5 * multiplier)

            # Similar to hook but slower, more deliberate
            filter_str = (
                f"drawtext=text='{escaped_wrapped}':"
                f"{base_style}:"
                f"alpha='if(lt(t,{reveal_duration}),t/{reveal_duration},1)'"
            )
            return filter_str

        else:
            # Default: simple fade in
            fade_duration = 0.3 * multiplier
            filter_str = (
                f"drawtext=text='{escaped_wrapped}':"
                f"{base_style}:"
                f"alpha='if(lt(t,{fade_duration}),t/{fade_duration},1)'"
            )
            return filter_str

    # ------------------------------------------------------------------
    # Video Building
    # ------------------------------------------------------------------

    def _build_cinematic_clips(
        self,
        image_paths: List[Path],
        lines: List[str],
        output_dir: Path,
        duration: float,
        transition_dur: float,
        audio_paths: Optional[List[Path]] = None,
    ) -> List[Path]:
        """Overlay text on images (with optional voice) using FFmpeg."""
        clip_paths = []
        n = len(image_paths)

        for i, (img, text) in enumerate(zip(image_paths, lines), 1):
            is_last = (i == n)
            clip_path = output_dir / f"clip_{i:02d}.mp4"

            # Determine clip duration
            if audio_paths and i <= len(audio_paths):
                # Voice mode: duration = audio duration + small tail
                audio_dur = self._get_duration(audio_paths[i-1])
                slide_dur = audio_dur + 0.3  # 0.3s tail after voice ends
                logger.info(
                    "[Clip %d] Voice mode: audio %.1fs + 0.3s tail",
                    i, audio_dur
                )
            else:
                # Text-only mode: dynamic duration based on reading speed
                word_count = len(text.split())
                calculated_duration = max(3.0, (word_count / 3.5) + 1.5)
                slide_dur = max(duration, calculated_duration)
                logger.info(
                    "[Clip %d] Text mode: %d words → %.1fs duration",
                    i, word_count, slide_dur
                )

            clip_dur = slide_dur + (0 if is_last else transition_dur)

            # Detect line type and choose animation style
            animation_enabled = getattr(settings, "cinematic_text_animation_enabled", True)

            if animation_enabled:
                # Determine animation style based on line position and content
                if i == 1:
                    # First line = hook
                    text_style = 'hook'
                elif is_last:
                    # Last line = insight/takeaway
                    text_style = 'insight'
                elif any(char.isdigit() for char in text):
                    # Contains numbers = number emphasis
                    text_style = 'number'
                else:
                    # Middle lines = main style
                    text_style = 'main'

                logger.info("[Clip %d] Using animation style: %s", i, text_style)

                # Get kinetic text overlay filter
                drawtext_filter = self._create_kinetic_text_overlay(
                    text, text_style, slide_dur, i, n
                )
            else:
                # Fallback to basic text overlay (no animation)
                wrapped_lines = textwrap.wrap(text, width=28)
                wrapped_text = "\n".join(wrapped_lines)
                escaped_text = wrapped_text.replace('\\', '\\\\').replace("'", "'\\''").replace(':', '\\:')

                drawtext_filter = (
                    f"drawtext=text='{escaped_text}':fontcolor=white:fontsize=72:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.5:boxborderw=40:"
                    f"line_spacing=15:fix_bounds=1"
                )

            # Build FFmpeg command
            if audio_paths and i <= len(audio_paths):
                # WITH VOICE: Image + Text + Audio
                filter_complex = (
                    f"[0:v]scale={self.REEL_W}:{self.REEL_H},"
                    f"{drawtext_filter},format=yuv420p[v];"
                    f"[1:a]volume=1.0[a]"
                )

                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(self.FPS),
                    "-t", str(clip_dur),
                    "-i", str(img),
                    "-i", str(audio_paths[i-1]),
                    "-filter_complex", filter_complex,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    str(clip_path)
                ]
            else:
                # TEXT ONLY: Image + Text
                filter_complex = (
                    f"scale={self.REEL_W}:{self.REEL_H},"
                    f"{drawtext_filter}"
                )

                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(self.FPS),
                    "-t", str(clip_dur),
                    "-i", str(img),
                    "-vf", filter_complex,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    str(clip_path)
                ]

            logger.info("[Cinematic Clip %d/%d] Rendering...", i, n)
            subprocess.run(cmd, capture_output=True, check=True)
            clip_paths.append(clip_path)

        return clip_paths

    def _get_duration(self, path: Path) -> float:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(r.stdout.strip())
        except ValueError:
            return 5.0

    def _blend_clips(self, clip_paths: List[Path], output_dir: Path, transition_dur: float) -> Path:
        if len(clip_paths) == 1:
            return clip_paths[0]

        current = clip_paths[0]
        for i in range(1, len(clip_paths)):
            blended = output_dir / f"blend_{i:02d}.mp4"
            dur = self._get_duration(current)
            offset = max(0.0, dur - transition_dur)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(current), "-i", str(clip_paths[i]),
                "-filter_complex",
                f"[0:v][1:v]xfade=transition=fade:duration={transition_dur}:offset={offset:.3f},format=yuv420p[v]",
                "-map", "[v]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                str(blended),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            current = blended
        return current

    def _mix_music(self, video_path: Path, output_path: Path, volume: float) -> None:
        music = Path("assets/music/background.mp3")
        if not music.exists():
            shutil.copy(video_path, output_path)
            return

        # Use a simpler filter if needed, or just map the background music
        cmd_no_v_audio = [
            "ffmpeg", "-y",
            "-i", str(video_path), "-i", str(music),
            "-filter_complex", f"[1:a]volume={volume}[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(output_path),
        ]
        
        r = subprocess.run(cmd_no_v_audio, capture_output=True, text=True)
        if r.returncode != 0:
            shutil.copy(video_path, output_path)

    # ------------------------------------------------------------------
    # Story Validation
    # ------------------------------------------------------------------

    def _validate_data_usage(
        self,
        generated_lines: List[str],
        research_numbers: List[str],
        verified_data: str,
        story_format: str = "contrast",
    ) -> None:
        """
        Verify generated story uses ONLY researched facts.

        For CASE_STUDY format, only the final lesson line is checked —
        the scenario lines (lines 1-3) use illustrative numbers that are
        computed from or consistent with research, not direct citations.

        Raises ValueError if unverified numbers are found in factual lines.
        """
        import re

        # CASE_STUDY: scenario lines use illustrative numbers by design.
        # Only validate the final lesson/takeaway line.
        if story_format == "case_study" and len(generated_lines) > 1:
            lines_to_check = generated_lines[-1:]
            logger.info(
                "CASE_STUDY format: validating only final lesson line (scenario lines use illustrative numbers)"
            )
        else:
            lines_to_check = generated_lines

        story_numbers = []
        for line in lines_to_check:
            # Extract numbers that have financial units attached — bare years/counts are OK
            story_numbers.extend(
                re.findall(r'[\d,\.]+\s*(?:crore|lakh|million|billion|%|₹|\$)', line)
            )

        if not story_numbers:
            logger.info("✓ No verifiable numbers in checked lines")
            return

        unverified = []
        for num in story_numbers:
            normalized = num.replace(',', '').strip()
            found = any(normalized in r.replace(',', '') for r in research_numbers)
            if not found:
                unverified.append(num)

        if unverified:
            logger.error("=" * 60)
            logger.error("DATA INTEGRITY VIOLATION")
            logger.error("Unverified numbers detected: %s", unverified)
            logger.error("These numbers were NOT in research data:")
            logger.error(verified_data[:500])
            logger.error("=" * 60)
            raise ValueError(f"Story contains unverified data: {unverified}")

        logger.info("✓ All numbers verified against research data")

    def _validate_story_coherence(self, lines: List[str], story_spine: str) -> None:
        """Basic validation to check if story makes sense."""

        # Check for abstract/philosophical keywords that indicate poor storytelling
        abstract_keywords = [
            'illusion', 'mirror', 'mask', 'journey', 'destination',
            'perception', 'construct', 'authentic', 'identity'
        ]

        abstract_count = 0
        for line in lines:
            line_lower = line.lower()
            for keyword in abstract_keywords:
                if keyword in line_lower:
                    abstract_count += 1
                    logger.warning(f"⚠️  Abstract language detected: '{keyword}' in '{line}'")

        if abstract_count >= 2:
            logger.warning("⚠️  Story may be too abstract. Consider more concrete examples.")

        # Check for numbers (good sign of concrete storytelling)
        has_numbers = any(char.isdigit() for line in lines for char in line)
        if not has_numbers:
            logger.warning("⚠️  No specific numbers found. Story may lack concrete examples.")

        # Check word count consistency
        for i, line in enumerate(lines, 1):
            word_count = len(line.split())
            if word_count < 5:
                logger.warning(f"⚠️  Line {i} too short ({word_count} words): {line}")
            elif word_count > 16:
                logger.warning(f"⚠️  Line {i} too long ({word_count} words): {line}")

    # ------------------------------------------------------------------
    # Hook Generation
    # ------------------------------------------------------------------

    def _generate_hook_variants(
        self,
        topic: str,
        angle: str,
        audience_insight: str,
        verified_data: str = ""
    ) -> dict:
        """
        Generate and score 5 hook variants using proven patterns.

        Returns:
            {
                'best_hook': str,
                'best_score': float,
                'reasoning': str,
                'all_variants': [
                    {
                        'hook': str,
                        'pattern': str,
                        'curiosity_gap': int,
                        'relevance': int,
                        'emotional_trigger': int,
                        'total_score': float
                    }
                ]
            }
        """
        logger.info("Generating hook variants for: %s", topic)

        system_prompt = """You are a Hook Architect specializing in attention-grabbing first lines.
Your hooks must stop scrollers in their tracks within 0.5 seconds."""

        prompt = f"""### TOPIC: {topic}
### ANGLE: {angle}
### TARGET AUDIENCE: {audience_insight}
{f'### VERIFIED DATA: {verified_data[:500]}' if verified_data else ''}

### YOUR TASK:
Generate 5 distinct hooks using proven psychological patterns.

### HOOK PATTERNS:

**1. SHOCKING STATISTIC**
Format: "[Specific number] [surprising fact]"
Example: "₹7.5 crore lost because of one word: safe"
Psychology: Numbers + surprise = pattern interrupt

**2. CONTRARIAN STATEMENT**
Format: "Everything you know about [X] is wrong"
Example: "Your 'safe' investments are the riskiest bet"
Psychology: Challenges existing belief = curiosity

**3. PATTERN INTERRUPT QUESTION**
Format: "What if [opposite of common belief]?"
Example: "What if playing it safe made you poor?"
Psychology: Cognitive dissonance = engagement

**4. PERSONAL COST/BENEFIT**
Format: "You're losing/gaining [specific amount] by [action]"
Example: "Every FD costs you ₹2.3 lakh per year"
Psychology: Self-interest + specificity = relevance

**5. STATUS QUO CHALLENGE**
Format: "[Common action] is quietly [negative outcome]"
Example: "Fixed deposits are quietly bankrupting your future"
Psychology: Hidden danger + urgency = emotional trigger

### SCORING CRITERIA:

**Curiosity Gap (0-10):**
- 10: Must know what happens next
- 5: Mildly interesting
- 0: Predictable/boring

**Relevance to Audience (0-10):**
- 10: "This is about MY situation"
- 5: Generally interesting
- 0: Not applicable to me

**Emotional Trigger (0-10):**
- 10: Fear, desire, anger, shock
- 5: Mild interest
- 0: Neutral/indifferent

### REQUIREMENTS:
- Use specific numbers from VERIFIED DATA when available
- Keep hooks under 14 words
- Make it immediately understandable (no jargon)
- Focus on OUTCOME, not process
- Each hook must use a DIFFERENT pattern

### OUTPUT FORMAT (JSON):
{{
  "hooks": [
    {{
      "hook": "The actual hook text (8-14 words)",
      "pattern": "shocking_statistic | contrarian_statement | pattern_interrupt | personal_cost | status_quo_challenge",
      "curiosity_gap": 0-10,
      "relevance": 0-10,
      "emotional_trigger": 0-10,
      "reasoning": "Why this hook works for this audience (1 sentence)"
    }},
    ... (5 total)
  ]
}}

Respond with ONLY valid JSON."""

        try:
            response = self.generator._generate_text(prompt, system_prompt=system_prompt)
            logger.debug("Hook variants raw response: %s", response)

            data = self.generator._parse_json_response(response)
            hooks = data.get("hooks", [])

            if not hooks or len(hooks) < 5:
                logger.warning("Insufficient hooks generated (%d), using fallback", len(hooks))
                return self._fallback_hooks(topic, angle, verified_data)

            # Score each hook
            scored_variants = []
            for h in hooks:
                curiosity = int(h.get("curiosity_gap", 5))
                relevance = int(h.get("relevance", 5))
                emotional = int(h.get("emotional_trigger", 5))

                # Weighted scoring: emotional triggers matter most for scrolling
                total_score = (
                    curiosity * 0.3 +
                    relevance * 0.35 +
                    emotional * 0.35
                )

                scored_variants.append({
                    'hook': h.get("hook", ""),
                    'pattern': h.get("pattern", "unknown"),
                    'curiosity_gap': curiosity,
                    'relevance': relevance,
                    'emotional_trigger': emotional,
                    'total_score': round(total_score, 2),
                    'reasoning': h.get("reasoning", "")
                })

            # Sort by total score
            scored_variants.sort(key=lambda x: x['total_score'], reverse=True)

            best = scored_variants[0]

            # Log all variants
            logger.info("=" * 60)
            logger.info("HOOK VARIANTS GENERATED:")
            logger.info("-" * 60)
            for i, variant in enumerate(scored_variants, 1):
                logger.info(
                    "%d. [Score: %.1f] %s",
                    i, variant['total_score'], variant['hook']
                )
                logger.info(
                    "   Pattern: %s | C:%d R:%d E:%d",
                    variant['pattern'],
                    variant['curiosity_gap'],
                    variant['relevance'],
                    variant['emotional_trigger']
                )
                logger.info("   Reasoning: %s", variant['reasoning'])
                logger.info("")
            logger.info("BEST HOOK SELECTED: %s (Score: %.1f)", best['hook'], best['total_score'])
            logger.info("=" * 60)

            return {
                'best_hook': best['hook'],
                'best_score': best['total_score'],
                'reasoning': best['reasoning'],
                'all_variants': scored_variants
            }

        except Exception as e:
            logger.error("Hook generation failed: %s", e)
            return self._fallback_hooks(topic, angle, verified_data)

    def _fallback_hooks(self, topic: str, angle: str, verified_data: str) -> dict:
        """Generate fallback hooks when LLM generation fails."""
        import re

        # Try to extract a number from verified data
        numbers = re.findall(
            r'[\d,\.]+(?:\s*(?:crore|lakh|million|billion|%|₹|\$))',
            verified_data
        ) if verified_data else []

        number_phrase = numbers[0] if numbers else "the numbers"

        fallback_variants = [
            {
                'hook': f"Let's talk about {topic[:40]}",
                'pattern': 'generic',
                'curiosity_gap': 3,
                'relevance': 5,
                'emotional_trigger': 2,
                'total_score': 3.3,
                'reasoning': 'Generic fallback'
            },
            {
                'hook': f"Here's what most people miss about {topic[:30]}",
                'pattern': 'contrarian_statement',
                'curiosity_gap': 5,
                'relevance': 6,
                'emotional_trigger': 4,
                'total_score': 5.0,
                'reasoning': 'Fallback contrarian'
            },
            {
                'hook': f"The truth about {topic[:40]}",
                'pattern': 'status_quo_challenge',
                'curiosity_gap': 4,
                'relevance': 6,
                'emotional_trigger': 3,
                'total_score': 4.3,
                'reasoning': 'Fallback challenge'
            },
            {
                'hook': f"{number_phrase} you need to know",
                'pattern': 'shocking_statistic',
                'curiosity_gap': 6,
                'relevance': 5,
                'emotional_trigger': 5,
                'total_score': 5.3,
                'reasoning': 'Fallback with data'
            },
            {
                'hook': f"Why {angle[:50]}",
                'pattern': 'pattern_interrupt',
                'curiosity_gap': 5,
                'relevance': 7,
                'emotional_trigger': 4,
                'total_score': 5.4,
                'reasoning': 'Fallback angle-based'
            }
        ]

        fallback_variants.sort(key=lambda x: x['total_score'], reverse=True)
        best = fallback_variants[0]

        logger.warning("Using fallback hooks (best score: %.1f)", best['total_score'])

        return {
            'best_hook': best['hook'],
            'best_score': best['total_score'],
            'reasoning': best['reasoning'],
            'all_variants': fallback_variants
        }

    # ------------------------------------------------------------------
    # Script Generation
    # ------------------------------------------------------------------

    def _get_format_guidelines(self, format_name: str, structure: List[str]) -> str:
        """Generate format-specific guidelines for story structure."""

        guidelines = {
            'contrast': """
**Line 1 - SETUP:**
Introduce the first approach/option with concrete details.
Example: "Your parents saved ₹50 lakh in FDs over 30 years"
NOT: "Safety is an illusion we cling to"

**Line 2 - CONTEXT:**
Show the result or reasoning behind the first approach.
Example: "It grew to ₹1.2 crore. They felt safe."
NOT: "The mirror shows what others want to see"

**Line 3 - INSIGHT:**
Reveal the alternative approach and its result. This is the comparison moment.
Example: "The same amount in Nifty 50? ₹8.7 crore."
NOT: "Behind every mask is another mask"

**Line 4 - TAKEAWAY:**
Quantify the difference and its meaning.
Example: "Playing it safe cost them ₹7.5 crore."
NOT: "Authenticity is the final illusion"
""",
            'timeline': """
**Line 1 - PAST:**
Establish where things were historically.
Example: "In 2010, solar energy made up 2% of India's power"
NOT: "The past is a mirror we don't recognize"

**Line 2 - INFLECTION:**
Show the turning point or key change.
Example: "Then came the 2015 solar mission with subsidies"
NOT: "Change happens when we least expect it"

**Line 3 - PRESENT:**
Reveal current state with specific data.
Example: "Today it's 15% and growing 25% yearly"
NOT: "We stand at a crossroads"

**Line 4 - FUTURE:**
Project forward based on the trend.
Example: "By 2030, India could hit 40% solar capacity"
NOT: "The future is what we make it"
""",
            'myth_buster': """
**Line 1 - COMMON BELIEF:**
State the misconception people hold.
Example: "Everyone says gold is the safest investment"
NOT: "Beliefs are comfortable lies we tell ourselves"

**Line 2 - WHY IT EXISTS:**
Explain why people believe this (history, culture).
Example: "Our grandparents survived on gold during crises"
NOT: "Tradition chains us to outdated thinking"

**Line 3 - THE TRUTH:**
Reveal what data actually shows.
Example: "But gold gave 8% returns vs Nifty's 14% over 20 years"
NOT: "Reality shatters our illusions"

**Line 4 - WHAT TO DO:**
Provide the actionable correction.
Example: "Diversify: 30% gold, 70% equity beats both"
NOT: "Question everything you know"
""",
            'case_study': """
**Line 1 - SITUATION:**
Set up the specific example/scenario.
Example: "Ravi had ₹10 lakh to invest in 2018"
NOT: "Every journey begins with a choice"

**Line 2 - DECISION:**
Show what action was taken.
Example: "He split it: ₹3L in fixed deposits, ₹7L in index funds"
NOT: "He chose the path less traveled"

**Line 3 - OUTCOME:**
Reveal the concrete results.
Example: "By 2024: FD → ₹4.2L, Index → ₹15.8L"
NOT: "Success came with patience and wisdom"

**Line 4 - LESSON:**
Extract the actionable insight.
Example: "His mixed approach gave 15% returns with lower risk"
NOT: "Balance is the key to everything"
"""
        }

        return guidelines.get(format_name, guidelines['contrast'])

    def _select_story_format(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig
    ) -> Tuple[str, str]:
        """
        Analyze topic, angle, and verified_data to select the best story format.

        Returns:
            Tuple of (format_name, reasoning)
        """
        topic = strategy.topic.lower()
        angle = strategy.angle.lower()
        verified_data = (strategy.verified_data or "").lower()

        # Keywords for each format
        contrast_keywords = ['vs', 'versus', 'compare', 'comparison', 'better', 'worse',
                           'difference', 'alternative', 'instead', 'choice']
        timeline_keywords = ['history', 'evolution', 'growth', 'trend', 'past', 'future',
                           'years', 'decade', 'century', 'progression', 'change over time']
        myth_keywords = ['myth', 'misconception', 'wrong', 'believe', 'think', 'assume',
                        'truth', 'reality', 'actually', 'debunk', 'false']
        case_study_keywords = ['example', 'case', 'story', 'how', 'success', 'failure',
                             'real', 'actual', 'happened', 'result', 'outcome']

        # Score each format
        scores = {
            'contrast': 0,
            'timeline': 0,
            'myth_buster': 0,
            'case_study': 0
        }

        # Check topic and angle
        combined_text = f"{topic} {angle}"

        for keyword in contrast_keywords:
            if keyword in combined_text:
                scores['contrast'] += 2

        for keyword in timeline_keywords:
            if keyword in combined_text:
                scores['timeline'] += 2

        for keyword in myth_keywords:
            if keyword in combined_text:
                scores['myth_buster'] += 2

        for keyword in case_study_keywords:
            if keyword in combined_text:
                scores['case_study'] += 2

        # Check verified data patterns
        if verified_data:
            # Timeline indicators: years, historical data
            if any(year in verified_data for year in ['2010', '2015', '2020', '2024']):
                scores['timeline'] += 1

            # Contrast indicators: multiple data points to compare
            import re
            numbers = re.findall(r'\d+(?:\.\d+)?(?:\s*(?:crore|lakh|million|billion|%|₹|\$))', verified_data)
            if len(numbers) >= 4:
                scores['contrast'] += 1

            # Myth buster indicators: sources, studies
            if any(word in verified_data for word in ['study', 'research', 'found', 'shows']):
                scores['myth_buster'] += 1

            # Case study indicators: specific examples, names
            if any(word in verified_data for word in ['example', 'company', 'person', 'case']):
                scores['case_study'] += 1

        # Financial content defaults to contrast (best for comparisons)
        if any(word in topic for word in ['invest', 'money', 'finance', 'stock', 'fund', 'saving']):
            scores['contrast'] += 1

        # Select format with highest score
        selected_format = max(scores, key=scores.get)

        # Default to contrast if all scores are 0 or tied
        if scores[selected_format] == 0 or list(scores.values()).count(scores[selected_format]) > 1:
            selected_format = 'contrast'
            reasoning = "Default format (no strong indicators for other formats)"
        else:
            format_info = self.STORY_FORMATS[selected_format]
            reasoning = f"Selected for {format_info['best_for']} (score: {scores[selected_format]})"

        logger.info("=" * 60)
        logger.info("STORY FORMAT SELECTION:")
        logger.info(f"Topic: {strategy.topic}")
        logger.info(f"Angle: {strategy.angle}")
        logger.info(f"Format Scores: {scores}")
        logger.info(f"Selected: {selected_format.upper()}")
        logger.info(f"Reasoning: {reasoning}")
        logger.info(f"Structure: {' → '.join(self.STORY_FORMATS[selected_format]['structure'])}")
        logger.info("=" * 60)

        return selected_format, reasoning

    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> Tuple[List[str], List[str]]:
        """
        Generate caption lines and matching SD image prompts in one call.

        Caption lines: 8-14 words, clear narrative progression.
        Image prompts: cinematic, story-driven, 9:16, no text.
        """
        # Enforce research requirement
        if not strategy.verified_data or len(strategy.verified_data) < 100:
            raise ValueError(
                f"Cannot generate cinematic reel without research data. "
                f"Topic: {strategy.topic} - Enable Tavily API or provide manual data."
            )

        # Extract numbers for later validation
        import re
        research_numbers = re.findall(
            r'[\d,\.]+(?:\s*(?:crore|lakh|million|billion|%|₹|\$))?',
            strategy.verified_data
        )
        logger.info("Extracted %d numbers from research for validation", len(research_numbers))

        # Select story format
        selected_format, format_reasoning = self._select_story_format(strategy, channel_config)
        format_info = self.STORY_FORMATS[selected_format]
        format_structure = format_info['structure']

        # Generate hook variants
        hook_result = self._generate_hook_variants(
            topic=strategy.topic,
            angle=strategy.angle,
            audience_insight=strategy.target_audience_insight,
            verified_data=strategy.verified_data
        )
        best_hook = hook_result['best_hook']
        all_hook_variants = hook_result['all_variants']

        system_prompt = (
            f"You are a Story Architect for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Brand Mission: {channel_config.brand_mission}\n"
            f"Target Audience: {channel_config.target_audience}\n"
            f"Cultural Context: {channel_config.cultural_context}\n\n"
            f"Your goal: Tell a clear, coherent story in {num_images} lines that the audience can follow and learn from.\n"
            "Priority: STORY COHERENCE over shock value. Each line must logically connect to the next.\n"
            "Use concrete examples and specific situations the audience recognizes."
        )

        # Format hook variants for prompt
        hook_variants_text = "\n".join([
            f"  {i}. [{v['pattern']}] \"{v['hook']}\" (Score: {v['total_score']:.1f})"
            for i, v in enumerate(all_hook_variants, 1)
        ])

        prompt = f"""### TOPIC: {strategy.topic}
### CORE ANGLE: {strategy.angle}
### TARGET AUDIENCE: {channel_config.target_audience}
### AUDIENCE INSIGHT: {strategy.target_audience_insight}
{f'### VERIFIED DATA (USE THESE FACTS): {strategy.verified_data}' if strategy.verified_data else ''}

### HOOK OPTIMIZATION:
We've generated and scored 5 hook variants. Use the BEST HOOK as guidance for Line 1:

**BEST HOOK (Score: {hook_result['best_score']:.1f}):**
"{best_hook}"

**Reasoning:** {hook_result['reasoning']}

**All Hook Variants:**
{hook_variants_text}

**For Line 1:** Use the best hook above as your starting point. You may adapt it slightly to fit the story flow, but maintain its core psychological trigger ({all_hook_variants[0]['pattern']}).

### YOUR TASK:
Create a {num_images}-line story that teaches the audience something valuable about {strategy.topic}.

The story must be:
1. **Easy to Follow** - Each line builds logically on the previous one
2. **Relevant** - Addresses a real situation the audience faces
3. **Concrete** - Uses specific examples, not abstract concepts
4. **Coherent** - The {num_images} lines together deliver ONE clear insight

### STORY FORMAT: {selected_format.upper()}
**Why this format:** {format_reasoning}
**Description:** {format_info['description']}

### STORY STRUCTURE ({' → '.join(format_structure)}):

{self._get_format_guidelines(selected_format, format_structure)}

### CAPTION REQUIREMENTS (8-14 words each):
- Use clear, conversational language
- Include specific numbers from VERIFIED DATA when available
- Each line must answer: "What happens next in this story?"
- Avoid abstract philosophical statements
- Write like you're explaining to a friend over coffee

### GOOD STORY EXAMPLES:

**Topic: Compound Interest**
Line 1: "₹5,000 monthly SIP starting at age 25"
Line 2: "By age 60, it becomes ₹2.3 crore"
Line 3: "Start the same SIP at 35 instead"
Line 4: "You end with ₹67 lakh. That's just 10 years."

**Topic: Career Growth**
Line 1: "You switched jobs 3 times in 5 years"
Line 2: "Salary went from ₹8L to ₹22L"
Line 3: "Your friend stayed at one company"
Line 4: "Still at ₹12L after 5 years"

Notice: Concrete numbers, clear progression, relatable situations.

### BAD EXAMPLES (DO NOT DO THIS):
❌ "Your identity is a construct of perception"
❌ "Success hides behind the mask of failure"
❌ "The journey is the destination we never reach"
→ Abstract, confusing, no concrete learning

### VISUAL ANCHOR:
Choose ONE concrete object/element that appears in ALL {num_images} images to create visual continuity.
Examples: hands, a specific object (phone, notebook, wallet), same location

### IMAGE PROMPT REQUIREMENTS:

Each image must:
1. **Feature the visual anchor** in different contexts
2. **Support the story beat** - visually show what the caption describes
3. **Be cinematically specific** - include shot type, lighting, mood

**Format Template:**
"[Shot type] of [visual anchor] [doing what], [lighting style], [emotional mood],
35mm film grain, 9:16 portrait, photorealistic, NO text NO watermarks"

**Shot Types:** Extreme close-up | Close-up | Medium shot | Wide shot
**Lighting:** Soft natural light | Warm side light | Golden hour | Dramatic side light
**Mood:** Hopeful | Contemplative | Tense | Relieved | Nostalgic

**GOOD Image Prompt:**
"Close-up of elderly hands holding worn bank passbook, warm soft side lighting,
nostalgic mood, shallow depth, 35mm film grain, 9:16 portrait, NO text"

**BAD Image Prompt:**
"Person thinking about money" ❌ Generic, no specifics, no visual anchor

### OUTPUT FORMAT (JSON):
{{
  "visual_anchor": "The one object/element appearing in all images (e.g., 'elderly hands', 'smartphone', 'notebook')",
  "story_spine": "One sentence: what does this {num_images}-line story teach?",
  "lines": [
    "Line 1 - The concrete setup",
    "Line 2 - The context or belief",
    "Line 3 - The key insight or comparison",
    "Line 4 - The takeaway"
  ],
  "image_prompts": [
    "Close-up of [visual_anchor] in Context A, [lighting], [mood], 35mm film grain, 9:16 portrait, NO text",
    "Medium shot of [visual_anchor] in Context B, [lighting], [mood], 35mm film grain, 9:16 portrait, NO text",
    "Close-up of [visual_anchor] in Context C, [lighting], [mood], 35mm film grain, 9:16 portrait, NO text",
    "Wide shot of [visual_anchor] in Context D, [lighting], [mood], 35mm film grain, 9:16 portrait, NO text"
  ]
}}

### FINAL CHECKLIST:
Before responding, verify:
- [ ] Each line logically follows from the previous one
- [ ] A new viewer can understand the story without prior context
- [ ] You used specific numbers/examples from VERIFIED DATA
- [ ] Visual anchor appears in all {num_images} image prompts
- [ ] No abstract philosophical statements
- [ ] Story teaches something concrete and actionable

Respond with ONLY valid JSON. Exactly {num_images} lines and {num_images} image_prompts."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        
        # Log Prompts
        logger.info("Cinematic Script System Prompt: %s", system_prompt)
        logger.info("Cinematic Script User Prompt: %s", prompt)
        logger.debug("Cinematic Script Raw Response: %s", response)

        data    = self.generator._parse_json_response(response)
        lines   = data.get("lines", [])
        prompts = data.get("image_prompts", [])
        visual_anchor = data.get("visual_anchor", "subject")
        story_spine   = data.get("story_spine", strategy.topic)

        # Validate counts — raise immediately if wrong
        if len(lines) != num_images or len(prompts) != num_images:
            raise RuntimeError(
                f"Script generation returned wrong counts (lines={len(lines)}, "
                f"prompts={len(prompts)}, expected={num_images}). "
                f"Raw response: {response[:300]}"
            )

        # Enforce word count on captions
        trimmed_lines = []
        for line in lines:
            words = str(line).split()
            if len(words) > 16:
                line = " ".join(words[:14]) + "..."
            trimmed_lines.append(str(line))

        # Append no-text instruction to every image prompt
        clean_prompts = []
        for p in prompts:
            p = str(p)
            if "no text" not in p.lower():
                p += (
                    ", cinematic noir, neo-realism, moody lighting, "
                    "35mm film grain, 9:16 portrait, NO text NO watermarks"
                )
            clean_prompts.append(p)

        # Log the final storyline
        logger.info("=" * 60)
        logger.info("GENERATED CINEMATIC STORY:")
        logger.info("STORY SPINE: %s", story_spine)
        logger.info("VISUAL ANCHOR: %s", visual_anchor)
        logger.info("-" * 60)
        for i, (l, p) in enumerate(zip(trimmed_lines, clean_prompts), 1):
            logger.info("%d. CAPTION: %s", i, l)
            logger.info("   IMAGE: %s...", p[:120])
            logger.info("")
        logger.info("=" * 60)

        # Validate story coherence (warnings only)
        self._validate_story_coherence(trimmed_lines, story_spine)

        # Validate data usage — CASE_STUDY only checks the final lesson line
        self._validate_data_usage(
            trimmed_lines, research_numbers, strategy.verified_data, selected_format
        )

        return trimmed_lines, clean_prompts

    # ------------------------------------------------------------------
    # SD Prompt Refinement
    # ------------------------------------------------------------------

    def _refine_sd_prompts(
        self,
        lines: List[str],
        initial_prompts: List[str],
        strategy: ContentStrategy,
        num_images: int,
    ) -> List[str]:
        """
        Dedicated AI call to rewrite image prompts for Stable Diffusion quality.

        The story-generation LLM doesn't know SD constraints. This call has
        full SD domain knowledge baked in. Falls back to initial_prompts on
        any failure so the run is never blocked by this step.

        Key rules enforced:
        - NEVER use hands/fingers as the main close-up subject (SD artifact hell)
        - Specific concrete subjects, not vague "person thinking about money"
        - Vary shot types across slides for visual interest
        - One recurring visual element for continuity
        - Required suffix on every prompt
        """
        lines_text    = "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))
        initial_text  = "\n".join(f"{i+1}. {p}" for i, p in enumerate(initial_prompts))

        system_prompt = """You are an expert Stable Diffusion prompt engineer for cinematic 9:16 portrait reels.
You know exactly what SD renders well versus what triggers artifacts.

SD RENDERS WELL — USE THESE:
• Environments: modern Indian office, home study, coffee shop, bedroom, city street, apartment balcony
• Objects in context: smartphone on wooden desk, open laptop, notebook, document, wallet, tea cup, coins
• Single person in environment: young Indian man/woman seen from mid-body up, clearly in a setting
• Abstract/atmospheric: light rays through window, bokeh backgrounds, silhouettes, textured surfaces

SD RENDERS POORLY — NEVER USE THESE:
• Hands as the MAIN CLOSE-UP SUBJECT → always fused fingers, extra limbs, anatomical nightmare
• "Analyzing data" with no specific physical object anchor
• Multiple people interacting at close range
• Text, numbers, or financial charts IN the image itself

SHOT VARIETY (must vary across images):
• Extreme close-up: single object macro, face expression detail
• Close-up: face + shoulders, object lying on a surface
• Medium shot: person waist-up in their environment
• Wide shot: full room/environment, person small in frame

END EVERY PROMPT WITH THIS EXACT SUFFIX:
"35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

GOOD EXAMPLES:
"Medium shot of young Indian man in grey t-shirt at wooden desk with open laptop, warm desk lamp, contemplative expression, shallow depth of field, 35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

"Extreme close-up of smartphone screen showing investment app lying on wooden surface, golden hour side light, shallow bokeh background, 35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

BAD EXAMPLES (DO NOT USE):
"Close-up of hands analyzing financial data" - hands close-up = artifact disaster
"Person thinking about money" - too vague, SD will hallucinate
"Hands holding financial documents with numbers" - hands again"""

        prompt = f"""Rewrite these {num_images} image prompts for Stable Diffusion.
Story topic: {strategy.topic}

STORY CAPTIONS (each image must visually support its caption):
{lines_text}

INITIAL PROMPTS (rewrite to fix SD issues):
{initial_text}

REQUIREMENTS:
1. Specific concrete subject — not "person thinking" but "young Indian woman in navy kurta at wooden desk"
2. NEVER use hands as the main close-up subject
3. Vary shot types — avoid repeating the same shot type more than once
4. Visual continuity: ONE recurring element across all {num_images} images (same person OR same location OR same key object)
5. End every prompt with: "35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

Return JSON:
{{"refined_prompts": ["full prompt 1", "full prompt 2", ...]}}

Exactly {num_images} prompts. JSON only."""

        try:
            response = self.generator._generate_text(prompt, system_prompt=system_prompt)
            data     = self.generator._parse_json_response(response)
            refined  = data.get("refined_prompts", [])

            if len(refined) == num_images:
                logger.info("=" * 60)
                logger.info("SD PROMPTS REFINED:")
                for i, p in enumerate(refined, 1):
                    logger.info("%d. %s", i, p[:130])
                logger.info("=" * 60)
                return refined

            logger.warning(
                "SD prompt refinement returned wrong count (%d vs %d), using initial prompts",
                len(refined), num_images,
            )
        except Exception as e:
            logger.warning("SD prompt refinement failed (%s), using initial prompts", e)

        return initial_prompts
