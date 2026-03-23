"""
Cinematic Reel Generator - Creates short 15-30s mood Reels from AI images.

Format: 2-4 cinematic AI-generated images, caption burned at bottom with
gradient fade, background music, fast cuts. No voice narration.

This is a separate lightweight pipeline from the narrated Reel generator.
It produces a different feel — atmospheric and emotional rather than
educational and structured.

Pipeline:
  1. Generate script: 2-4 punchy lines (8-12 words each), persona-driven
  2. Generate image prompts: cinematic human moment per line
  3. Generate images via SD WebUI (portrait 1080x1920)
  4. Burn captions onto images using Pillow
  5. Stitch into Reel with FFmpeg + background music
"""

import base64
import io
import logging
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from src.config import settings
from src.models import ContentStrategy, ChannelConfig, GeneratedContent
from src.agents.content_generator import ContentGenerator


logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Layout constants
# ------------------------------------------------------------------

REEL_W = 1080
REEL_H = 1920
FPS    = 25

# Gradient fade height at bottom of image (pixels)
GRADIENT_HEIGHT = 420

# Caption zone within gradient
CAPTION_BOTTOM_MARGIN  = 100   # from bottom of image
CAPTION_SIDE_MARGIN    = 80    # from left/right edges
CAPTION_MAX_WIDTH      = REEL_W - (CAPTION_SIDE_MARGIN * 2)

# Font sizes
CAPTION_FONT_SIZE      = 72
CHANNEL_FONT_SIZE      = 32

# How long each image holds on screen (seconds)
# Final duration = image_hold * num_images + music tail
IMAGE_HOLD_SECONDS     = 4.0
MUSIC_VOLUME           = 0.18   # slightly louder than narrated reel — no voice competing


class CinematicReelGenerator:
    """
    Generates a short cinematic Reel from 2-4 AI images with burned captions.

    Usage:
        gen = CinematicReelGenerator()
        reel_path = gen.generate(
            content=content,
            strategy=strategy,
            channel_config=channel_config,
            output_path=Path("output/reel_cinematic.mp4"),
            num_images=4,      # 2-4
        )
    """

    def __init__(self):
        self.generator = ContentGenerator()
        self.temp_dir  = Path("temp_cinematic")
        self.temp_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        output_path: Path,
        num_images: int = 4,
    ) -> Path:
        """
        Full pipeline: script → image prompts → SD images →
        caption burn → stitch → music → reel.mp4
        """
        num_images = max(2, min(4, num_images))
        logger.info(
            "Cinematic Reel: %s (%d images)", strategy.topic, num_images
        )

        # ── 1. Generate script + image prompts ───────────────────────
        lines, image_prompts = self._generate_script_and_prompts(
            strategy, channel_config, num_images
        )

        # ── 2. Generate images via SD WebUI ──────────────────────────
        images_dir = self.temp_dir / "images"
        images_dir.mkdir(exist_ok=True)
        raw_image_paths = self._generate_sd_images(
            image_prompts, images_dir
        )

        # ── 3. Burn captions onto images ──────────────────────────────
        captioned_dir = self.temp_dir / "captioned"
        captioned_dir.mkdir(exist_ok=True)
        captioned_paths = self._burn_captions(
            raw_image_paths, lines, channel_config, captioned_dir
        )

        # ── 4. Stitch into video ──────────────────────────────────────
        stitched = self.temp_dir / "stitched.mp4"
        self._stitch_images(captioned_paths, stitched)

        # ── 5. Add music ──────────────────────────────────────────────
        self._mix_music(stitched, output_path)

        logger.info("Cinematic Reel complete: %s", output_path)
        return output_path

    def cleanup(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # ------------------------------------------------------------------
    # Script + image prompt generation
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
            f"You are a creative director for '{channel_config.name}' "
            "Instagram Reels. You create short cinematic mood content — "
            "powerful images with one line of text that makes someone stop "
            "and feel something."
        )

        prompt = f"""### TOPIC: {strategy.topic}
### ANGLE: {strategy.angle}
### CHANNEL TONE: {channel_config.tone}

### TASK:
Create a {num_images}-image cinematic Instagram Reel.

Each image gets:
1. ONE caption line (the text that appears on screen)
2. ONE image prompt (what SD generates as the visual)

### CAPTION RULES:
- 8-12 words MAXIMUM per line — count them
- Second person ("you", "your") or observation style
- Emotionally resonant — make the viewer feel seen
- Progressive: each line builds on the previous one
- No hashtags, no emojis, no punctuation except "." and "..."
- Line {num_images} is always the insight/resolution

### IMAGE PROMPT RULES:
- Cinematic human moments: real people, hands, emotions, everyday scenes
- Portrait orientation (9:16 vertical)
- Photorealistic, film grain, shallow depth of field, natural light
- NO text, logos, watermarks, or typography anywhere in the scene
- Each scene must visually match its caption line
- Vary the scenes — do not repeat the same setting

### GOOD CAPTION EXAMPLES:
- "You stayed longer than you should have." (8 words)
- "Your brain made it feel like loyalty." (8 words)
- "That's not commitment. That's sunk cost." (6 words)
- "You already know. You're just not ready." (8 words)

### OUTPUT FORMAT (JSON):
{{
  "lines": [
    "Caption line 1",
    "Caption line 2",
    ...
  ],
  "image_prompts": [
    "Cinematic scene for image 1...",
    "Cinematic scene for image 2...",
    ...
  ]
}}

Respond with ONLY valid JSON. Exactly {num_images} lines and {num_images} image_prompts."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)

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
                        ", cinematic, photorealistic, film grain, "
                        "shallow depth of field, natural lighting, "
                        "9:16 portrait, NO text NO watermarks NO logos"
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

    # ------------------------------------------------------------------
    # SD image generation
    # ------------------------------------------------------------------

    def _generate_sd_images(
        self,
        prompts: List[str],
        output_dir: Path,
    ) -> List[Path]:
        """
        Generate portrait 1080x1920 images via SD WebUI API.
        Uses settings.sd_api_url and settings.sd_negative_prompt.
        """
        api_url  = getattr(settings, "sd_api_url",
                           "http://localhost:7860/sdapi/v1/txt2img")
        steps    = getattr(settings, "sd_steps", 25)
        neg      = getattr(
            settings, "sd_negative_prompt",
            "text, watermark, logo, blurry, low quality, distorted"
        )

        paths: List[Path] = []

        for i, prompt_text in enumerate(prompts, 1):
            payload = {
                "prompt":          prompt_text,
                "negative_prompt": neg,
                "steps":           steps,
                "width":           REEL_W,
                "height":          REEL_H,
                "cfg_scale":       7.0,
                "sampler_name":    "DPM++ 2M Karras",
            }

            logger.info("[SD Image %d/%d] Generating...", i, len(prompts))

            try:
                r = requests.post(api_url, json=payload, timeout=180)
                r.raise_for_status()
                img_b64  = r.json()["images"][0]
                img_data = base64.b64decode(img_b64)
                img_path = output_dir / f"raw_{i:02d}.png"

                with open(img_path, "wb") as f:
                    f.write(img_data)

                # Ensure exact portrait dimensions
                img = Image.open(img_path)
                if img.size != (REEL_W, REEL_H):
                    img = img.resize((REEL_W, REEL_H), Image.LANCZOS)
                    img.save(img_path)

                paths.append(img_path)
                logger.info("[SD Image %d] Saved: %s", i, img_path)

            except Exception as e:
                logger.error("[SD Image %d] Failed: %s", i, e)
                # Generate a solid color placeholder
                placeholder = Image.new("RGB", (REEL_W, REEL_H), color=(20, 20, 30))
                img_path = output_dir / f"raw_{i:02d}.png"
                placeholder.save(img_path)
                paths.append(img_path)

        return paths

    # ------------------------------------------------------------------
    # Caption burning
    # ------------------------------------------------------------------

    def _burn_captions(
        self,
        image_paths: List[Path],
        lines: List[str],
        channel_config: ChannelConfig,
        output_dir: Path,
    ) -> List[Path]:
        """
        Burn caption text onto each image with a bottom gradient fade.

        Layout:
        - Full image fills 1080x1920
        - Bottom gradient: transparent → black over GRADIENT_HEIGHT pixels
        - Caption text: bold white, centered, wraps to 2 lines max
        - Channel name: small, bottom-right corner
        """
        output_paths: List[Path] = []

        for i, (img_path, line) in enumerate(zip(image_paths, lines), 1):
            img = Image.open(img_path).convert("RGBA")

            # ── Draw gradient overlay ──────────────────────────────────
            gradient = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
            draw_grad = ImageDraw.Draw(gradient)

            grad_top = REEL_H - GRADIENT_HEIGHT
            for y in range(GRADIENT_HEIGHT):
                # Alpha: 0 at top of gradient → 220 at bottom
                alpha = int((y / GRADIENT_HEIGHT) ** 1.5 * 220)
                draw_grad.line(
                    [(0, grad_top + y), (REEL_W, grad_top + y)],
                    fill=(0, 0, 0, alpha)
                )

            img = Image.alpha_composite(img, gradient)
            draw = ImageDraw.Draw(img)

            # ── Load fonts ─────────────────────────────────────────────
            caption_font  = self._load_font(CAPTION_FONT_SIZE,  bold=True)
            channel_font  = self._load_font(CHANNEL_FONT_SIZE,  bold=False)

            # ── Wrap caption text ──────────────────────────────────────
            wrapped_lines = self._wrap_text(line, caption_font, CAPTION_MAX_WIDTH)

            # Calculate total text block height
            line_height = CAPTION_FONT_SIZE + 16
            block_height = len(wrapped_lines) * line_height
            text_y = REEL_H - CAPTION_BOTTOM_MARGIN - block_height

            # ── Draw caption lines ─────────────────────────────────────
            for j, text_line in enumerate(wrapped_lines):
                y = text_y + j * line_height

                # Shadow pass
                for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2),(0,3),(0,-3)]:
                    draw.text(
                        (REEL_W // 2 + dx, y + dy),
                        text_line,
                        font=caption_font,
                        fill=(0, 0, 0, 180),
                        anchor="mm",
                    )

                # Main text
                draw.text(
                    (REEL_W // 2, y),
                    text_line,
                    font=caption_font,
                    fill=(255, 255, 255, 255),
                    anchor="mm",
                )

            # ── Channel name bottom-left ───────────────────────────────
            channel_text = f"@{channel_config.name.lower().replace(' ', '')}"
            draw.text(
                (CAPTION_SIDE_MARGIN, REEL_H - 55),
                channel_text,
                font=channel_font,
                fill=(255, 255, 255, 160),
                anchor="lm",
            )

            # ── Save ───────────────────────────────────────────────────
            out_path = output_dir / f"captioned_{i:02d}.png"
            img.convert("RGB").save(out_path, "PNG")
            output_paths.append(out_path)
            logger.info("Caption burned: image %d — '%s'", i, line[:40])

        return output_paths

    def _wrap_text(
        self, text: str, font: ImageFont.FreeTypeFont, max_width: int
    ) -> List[str]:
        """Wrap text to fit within max_width pixels."""
        words  = text.split()
        lines  = []
        current = ""

        # Use a temporary draw surface for measuring
        tmp_img  = Image.new("RGB", (1, 1))
        tmp_draw = ImageDraw.Draw(tmp_img)

        for word in words:
            test = (current + " " + word).strip()
            bbox = tmp_draw.textbbox((0, 0), test, font=font)
            w    = bbox[2] - bbox[0]
            if w <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word

        if current:
            lines.append(current)

        # Max 3 lines — truncate with ellipsis if needed
        if len(lines) > 3:
            lines = lines[:3]
            lines[-1] = lines[-1].rstrip(".") + "..."

        return lines

    def _load_font(
        self, size: int, bold: bool = False
    ) -> ImageFont.FreeTypeFont:
        """
        Load a font. Tries common system paths then falls back to default.
        Add your preferred font path here.
        """
        candidates = []

        if bold:
            candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            ]
        else:
            candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            ]

        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue

        # PIL default bitmap font — always available but no size control
        logger.warning("No TTF font found, using PIL default (no size control)")
        return ImageFont.load_default()

    # ------------------------------------------------------------------
    # Video stitching
    # ------------------------------------------------------------------

    def _stitch_images(
        self, image_paths: List[Path], output_path: Path
    ) -> None:
        """
        Stitch captioned images into a silent video.
        Each image holds for IMAGE_HOLD_SECONDS with a fade transition.
        """
        n = len(image_paths)

        if n == 1:
            # Single image — just loop it
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(FPS),
                "-t", str(IMAGE_HOLD_SECONDS),
                "-i", str(image_paths[0]),
                "-vf", f"scale={REEL_W}:{REEL_H},format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                str(output_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            return

        # Build individual clips then cross-fade blend
        clip_dir = self.temp_dir / "clips"
        clip_dir.mkdir(exist_ok=True)
        clip_paths = []

        transition_dur = 0.5

        for i, img_path in enumerate(image_paths, 1):
            is_last   = (i == n)
            hold      = IMAGE_HOLD_SECONDS + (0 if is_last else transition_dur)
            clip_path = clip_dir / f"clip_{i:02d}.mp4"

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(FPS),
                "-t", str(hold),
                "-i", str(img_path),
                "-vf", f"scale={REEL_W}:{REEL_H},format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                "-an",   # no audio — music added later
                str(clip_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            clip_paths.append(clip_path)

        # Sequential cross-fade blend
        current = clip_paths[0]
        for i in range(1, len(clip_paths)):
            blended = clip_dir / f"blend_{i:02d}.mp4"
            dur     = self._get_duration(current)
            offset  = max(0.0, dur - transition_dur)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(current), "-i", str(clip_paths[i]),
                "-filter_complex",
                (
                    f"[0:v][1:v]xfade=transition=fade"
                    f":duration={transition_dur}:offset={offset:.3f},"
                    f"format=yuv420p[v]"
                ),
                "-map", "[v]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                "-an",
                str(blended),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error("Blend error:\n%s", r.stderr[-300:])
                raise RuntimeError(f"Blend failed at step {i}")
            current = blended

        shutil.copy(current, output_path)

    def _mix_music(
        self, video_path: Path, output_path: Path
    ) -> None:
        """Add background music. Slightly louder than narrated reel (no voice competing)."""
        music = Path("assets/music/background.mp3")

        if not music.exists():
            logger.info("No background music found")
            shutil.copy(video_path, output_path)
            return

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path), "-i", str(music),
            "-filter_complex",
            (
                f"[1:a]aloop=loop=-1:size=100M,"
                f"volume={MUSIC_VOLUME},"
                f"afade=t=out:st={self._get_duration(video_path)-1.5}:d=1.5[bg];"
                f"[bg]aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
            ),
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            logger.warning("Music mix failed, saving without music")
            shutil.copy(video_path, output_path)

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
            return IMAGE_HOLD_SECONDS