import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
import time
import requests
import base64
import io

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
    ) -> Path:
        """
        Full pipeline: generate script → generate 9:16 images → 
        overlay text → blend → music.
        """
        logger.info("Starting Cinematic Reel: %s", strategy.topic)

        # 1. Generate Script and Prompts
        lines, prompts = self._generate_script_and_prompts(
            strategy, channel_config, num_images
        )

        # 2. Generate Cinematic Images (9:16)
        image_dir = self.temp_dir / "images"
        image_dir.mkdir(exist_ok=True)
        image_paths = self._generate_cinematic_images(prompts, image_dir)

        # 3. Build Clips with Text Overlays
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)
        
        slide_duration = getattr(settings, "cinematic_slide_duration", 4.0)
        transition_dur = getattr(settings, "cinematic_transition_duration", 0.6)
        
        clip_paths = self._build_cinematic_clips(
            image_paths, lines, video_dir, slide_duration, transition_dur
        )

        # 4. Blend Clips
        blended = self._blend_clips(clip_paths, video_dir, transition_dur)

        # 5. Add Music
        music_volume = getattr(settings, "cinematic_music_volume", 0.15)
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
        """Generate 9:16 cinematic images using the configured provider."""
        image_paths = []

        for i, prompt in enumerate(prompts, 1):
            logger.info("[Cinematic Image %d/%d] Generating via %s...", i, len(prompts), self.provider)
            
            try:
                path = None
                if self.provider == "replicate":
                    path = self._generate_replicate_image(prompt, i, output_dir)
                elif self.provider == "sd":
                    path = self._generate_sd_image(prompt, i, output_dir)
                elif self.provider == "gemini":
                    path = self._generate_gemini_image(prompt, i, output_dir)
                else:
                    logger.error("Unsupported image provider: %s", self.provider)

                if path:
                    image_paths.append(path)
                else:
                    raise Exception(f"Failed to generate image {i}")
                    
            except Exception as e:
                logger.error("Failed to generate cinematic image %d: %s", i, e)
                # Fallback: could use a solid color or previous image
                if image_paths:
                    image_paths.append(image_paths[-1])

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
        payload = {
            "prompt": prompt,
            "negative_prompt": settings.sd_negative_prompt,
            "steps": settings.sd_steps,
            "width": 1080,
            "height": 1920, # Native portrait for cinematic reel
        }
        
        response = requests.post(settings.sd_api_url, json=payload, timeout=settings.sd_timeout)
        response.raise_for_status()
        r = response.json()
        
        image_data = base64.b64decode(r['images'][0])
        p = output_dir / f"image_{index:02d}.png"
        with open(p, 'wb') as f:
            f.write(image_data)
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
    # Video Building
    # ------------------------------------------------------------------

    def _build_cinematic_clips(
        self,
        image_paths: List[Path],
        lines: List[str],
        output_dir: Path,
        duration: float,
        transition_dur: float,
    ) -> List[Path]:
        """Overlay text on images using FFmpeg drawtext."""
        clip_paths = []
        n = len(image_paths)

        for i, (img, text) in enumerate(zip(image_paths, lines), 1):
            is_last = (i == n)
            clip_dur = duration + (0 if is_last else transition_dur)
            clip_path = output_dir / f"clip_{i:02d}.mp4"

            # Escape text for FFmpeg
            clean_text = text.replace("'", "").replace(":", "\\:")
            
            # drawtext filter: centered, wrapped, high-end typography feel
            filter_complex = (
                f"scale={self.REEL_W}:{self.REEL_H},"
                f"drawtext=text='{clean_text}':fontcolor=white:fontsize=64:"
                f"x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.4:boxborderw=20:"
                f"line_spacing=10:fix_bounds=1"
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
    # Script Generation
    # ------------------------------------------------------------------

    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> Tuple[List[str], List[str]]:
        """
        Generate caption lines and matching SD image prompts in one call.

        Caption lines: 8-12 words, second-person, emotionally charged.
        Image prompts: cinematic human moment, portrait 9:16, no text.
        """
        system_prompt = (
            f"You are the Visionary Creative Director for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Brand Mission: {channel_config.brand_mission}\n"
            f"Target Audience: {channel_config.target_audience}\n"
            f"Cultural Context: {channel_config.cultural_context}\n\n"
            "Your goal is to create a 'Mood Film' Reel. We don't explain; we reveal. "
            "We use 'spiky' insights—statements that are bold, slightly polarizing, or deeply personal—"
            "to stop the scroll. Avoid generic advice."
        )

        prompt = f"""### TOPIC TO TRANSFORM: {strategy.topic}
### CORE ANGLE: {strategy.angle}
### STRATEGY INSIGHT: {strategy.target_audience_insight}

### TASK:
Create a {num_images}-image cinematic Reel. This is a high-end visual narrative.

### CAPTION RULES (8-12 words):
- Use 'Spiky' Statements: Bold, counter-intuitive, or visceral.
- No 'Intro' or 'Summary' lines. Every line must hit like a realization.
- Tone: Cold, objective, and deeply observant.
- Progression: Start with a common lie/behavior, end with a harsh but empowering truth.

### IMAGE PROMPT RULES (Stable Diffusion):
- AVOID generic scenes like 'person thinking' or 'laptop on desk'.
- USE Concrete Visual Metaphors: 
  - Instead of 'Stress', use 'A single lit cigarette in a dark room with heavy smoke' or 'Clenched fists underwater'.
  - Instead of 'Growth', use 'A single green sprout breaking through cracked concrete'.
- STYLE: Cinematic noir, neo-realism, moody lighting (chiaroscuro), 35mm film grain, 9:16 portrait.
- ABSOLUTE: No text or typographic elements in the scene.

### OUTPUT FORMAT (JSON):
{{
  "lines": [
    "Spiky Line 1",
    "Spiky Line 2",
    ...
  ],
  "image_prompts": [
    "Concrete Visual Metaphor 1",
    "Concrete Visual Metaphor 2",
    ...
  ]
}}

Respond with ONLY valid JSON. Exactly {num_images} lines and {num_images} image_prompts."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        
        # Log Prompts
        logger.debug("Cinematic Script System Prompt: %s", system_prompt)
        logger.debug("Cinematic Script User Prompt: %s", prompt)
        logger.debug("Cinematic Script Raw Response: %s", response)

        try:
            data    = self.generator._parse_json_response(response)
            lines   = data.get("lines", [])
            prompts = data.get("image_prompts", [])

            # Validate counts
            if len(lines) != num_images or len(prompts) != num_images:
                logger.warning(
                    "Count mismatch (lines=%d, prompts=%d, expected=%d)",
                    len(lines), len(prompts), num_images
                )
                # Pad or trim to match
                while len(lines)   < num_images: lines.append(strategy.topic)
                while len(prompts) < num_images: prompts.append(
                    f"Cinematic portrait of a person in thought, natural light, "
                    f"film grain, shallow depth of field, 9:16"
                )
                lines   = lines[:num_images]
                prompts = prompts[:num_images]

            # Enforce word count on captions
            trimmed_lines = []
            for line in lines:
                words = str(line).split()
                if len(words) > 14:
                    line = " ".join(words[:12]) + "."
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

            return trimmed_lines, clean_prompts

        except Exception as e:
            logger.error("Script generation failed: %s", e)
            # Fallback: use topic as single caption
            fallback_line   = [strategy.topic[:60]] * num_images
            fallback_prompt = [
                "Cinematic portrait, person sitting alone in soft light, "
                "film grain, shallow depth of field, 9:16, no text"
            ] * num_images
            return fallback_line, fallback_prompt
