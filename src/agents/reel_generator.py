"""
Reel Generator Agent - Transforms carousel content into portrait Instagram Reels.

Key design decisions:
- Renders slides natively at 1080x1920 using portrait HTML templates
  (no square→portrait conversion, no blurred padding hacks)
- No Ken Burns — slides are information-dense, zoom distorts readability
- Narration strictly capped at 12-18 words per slide → 45-60s total
- Slide duration driven by actual audio length + configurable tail
- Sequential cross-fade blend safe for 4GB RAM
- TTS: edge (default, free, good quality) → elevenlabs → gtts fallback
"""

import asyncio
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from gtts import gTTS

from jinja2 import Template
from html2image import Html2Image
from PIL import Image

from src.models import CarouselSlide, ContentStrategy, ChannelConfig, GeneratedContent
from src.config import settings
from src.agents.content_generator import ContentGenerator


logger = logging.getLogger(__name__)


class ReelGenerator:
    """
    Converts carousel slides into a portrait 1080x1920 Instagram Reel.

    Pipeline:
      1. Select best N slides (hook + strongest content + CTA)
      2. Render each slide as a native 1080x1920 portrait PNG
      3. Generate short narration script (12-18 words per slide)
      4. Synthesise audio per slide
      5. Build individual video clips (static slide + audio)
      6. Sequential cross-fade blend
      7. Mix background music
    """

    REEL_W = 1080
    REEL_H = 1920
    FPS    = 25

    def __init__(self):
        self.generator  = ContentGenerator()
        self.temp_dir   = Path("temp_reel")
        self.temp_dir.mkdir(exist_ok=True)

        # html2image renderer for portrait slides
        self.hti = Html2Image(size=(self.REEL_W, self.REEL_H))
        self.hti.browser.flags = [
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-gpu", "--hide-scrollbars",
            f"--window-size={self.REEL_W},{self.REEL_H}",
            "--force-device-scale-factor=1",
            "--disable-dev-shm-usage",
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_reel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        image_paths: List[Path],        # carousel square images (for blurred_hook bg)
        output_path: Path,
    ) -> Path:
        """
        Full pipeline: select slides → render portrait PNGs → narrate →
        audio → clips → blend → music → reel.mp4
        """
        logger.info("Starting Reel: %s", strategy.topic)

        max_slides       = getattr(settings, "reel_max_slides", 5)
        transition_dur   = getattr(settings, "reel_transition_duration", 0.4)
        slide_tail       = getattr(settings, "reel_slide_tail", 0.3)
        music_volume     = getattr(settings, "reel_music_volume", 0.10)

        # ── 1. Select slides ──────────────────────────────────────────
        selected_slides, selected_sq_images = self._select_slides(
            content.slides, image_paths, max_slides
        )
        logger.info(
            "Selected slides: %s", [s.slide_number for s in selected_slides]
        )

        # ── 2. Extract colors from strategy ──────────────────────────
        bg_color     = self._extract_color(strategy.color_palette, "background", "#111827")
        text_color   = self._extract_color(strategy.color_palette, "text", None) or \
                       self._contrast(bg_color)
        accent_color = self._extract_color(strategy.color_palette, "accent", "#3b82f6")

        # ── 3. Render portrait slides ─────────────────────────────────
        reel_frames_dir = self.temp_dir / "frames"
        reel_frames_dir.mkdir(exist_ok=True)

        # The hook image (slide 1 square PNG) is used as blurred background
        hook_image_path = selected_sq_images[0] if selected_sq_images else None

        reel_image_paths = self._render_portrait_slides(
            slides=selected_slides,
            strategy=strategy,
            channel_config=channel_config,
            bg_color=bg_color,
            text_color=text_color,
            accent_color=accent_color,
            hook_image_path=hook_image_path,
            output_dir=reel_frames_dir,
        )

        # ── 4. Generate narration script ──────────────────────────────
        script_segments = self._generate_narration_script(
            selected_slides, strategy, channel_config
        )

        # ── 5. Synthesise audio ───────────────────────────────────────
        audio_dir = self.temp_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        audio_paths = self._create_audio_segments(
            script_segments, audio_dir, channel_config
        )

        # ── 6. Build clips ────────────────────────────────────────────
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)
        clip_paths = self._build_clips(
            reel_image_paths, audio_paths, video_dir,
            slide_tail, transition_dur
        )

        # ── 7. Blend ──────────────────────────────────────────────────
        blended = self._blend_clips(clip_paths, video_dir, transition_dur)

        # ── 8. Music ──────────────────────────────────────────────────
        self._mix_music(blended, output_path, music_volume)

        logger.info("Reel complete: %s", output_path)
        return output_path

    def cleanup(self):
        """Remove all temporary files."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # ------------------------------------------------------------------
    # Slide selection
    # ------------------------------------------------------------------

    def _select_slides(
        self,
        slides: List[CarouselSlide],
        image_paths: List[Path],
        max_slides: int,
    ) -> Tuple[List[CarouselSlide], List[Path]]:
        """
        Select best slides capped at max_slides.
        Always includes: hook (slide 1) + CTA (last) + best middle slides.
        Middle priority: big_fact > split_comparison > standard.
        """
        path_by_num = {s.slide_number: p for s, p in zip(slides, image_paths)}

        if len(slides) <= max_slides:
            return slides, [path_by_num[s.slide_number] for s in slides]

        hook   = [s for s in slides if s.slide_number == 1]
        cta    = [s for s in slides if s.purpose.value == "cta"]
        middle = [s for s in slides if s.slide_number != 1 and s.purpose.value != "cta"]

        priority = {"big_fact": 0, "split_comparison": 1, "standard": 2}
        middle_sorted = sorted(
            middle,
            key=lambda s: (priority.get(s.template_name or "standard", 2), s.slide_number)
        )

        slots    = max_slides - len(hook) - len(cta)
        selected = sorted(hook + middle_sorted[:slots] + cta, key=lambda s: s.slide_number)

        return selected, [path_by_num[s.slide_number] for s in selected]

    # ------------------------------------------------------------------
    # Portrait slide rendering
    # ------------------------------------------------------------------

    def _render_portrait_slides(
        self,
        slides: List[CarouselSlide],
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        bg_color: str,
        text_color: str,
        accent_color: str,
        hook_image_path: Optional[Path],
        output_dir: Path,
    ) -> List[Path]:
        """
        Render each slide as a native 1080x1920 portrait PNG using
        reel-specific HTML templates in src/templates/reel/.
        """
        import base64, io as _io
        from PIL import ImageFilter, ImageEnhance

        # Pre-build blurred hook b64 once (used by blurred_hook slides)
        bg_image_b64 = None
        if hook_image_path and hook_image_path.exists():
            with Image.open(hook_image_path) as img:
                blurred  = img.filter(ImageFilter.GaussianBlur(radius=35))
                darkened = ImageEnhance.Brightness(blurred).enhance(0.35)
                buf = _io.BytesIO()
                darkened.save(buf, format="PNG")
                bg_image_b64 = "data:image/png;base64," + \
                               base64.b64encode(buf.getvalue()).decode()

        total = len(slides)
        image_paths: List[Path] = []

        for idx, slide in enumerate(slides, 1):
            template_name = slide.template_name or "standard"
            bg_style      = slide.background_style or "solid"

            # Load reel template
            template_file = Path(f"src/templates/reel/{template_name}.html")
            if not template_file.exists():
                logger.warning("Reel template '%s' not found, using standard", template_name)
                template_file = Path("src/templates/reel/standard.html")
            if not template_file.exists():
                raise FileNotFoundError(f"No reel template at {template_file}")

            with open(template_file) as f:
                jinja_tpl = Template(f.read())

            # Derive action_text for CTA slide
            action_text = slide.action_text or (
                "Comment below" if slide.purpose.value == "cta" else None
            )

            # slide_label: short descriptor shown above topic title
            slide_labels = {
                "hook": "Mind check",
                "content": "Deep dive",
                "cta": "Your turn",
            }
            slide_label = slide_labels.get(slide.purpose.value, "")

            html = jinja_tpl.render(
                bg_color=bg_color,
                text_color=text_color,
                accent_color=accent_color,
                bg_style=bg_style,
                bg_image_b64=bg_image_b64 if bg_style == "blurred_hook" else None,
                channel_name=channel_config.name,
                topic_title=strategy.topic,
                slide_label=slide_label,
                current_slide=idx,
                total_slides=total,
                headline=slide.headline,
                subtext=slide.subtext,
                pre_label=slide.pre_label,
                left_content=slide.left_content,
                right_content=slide.right_content,
                action_text=action_text,
                text_overlay=slide.text_overlay,
            )

            temp_name = f"reel_frame_{idx:02d}.png"
            self.hti.screenshot(
                html_str=html,
                save_as=temp_name,
                size=(self.REEL_W, self.REEL_H),
            )

            temp_path = Path(temp_name)
            out_path  = output_dir / f"frame_{idx:02d}.png"

            if not temp_path.exists():
                raise FileNotFoundError(f"html2image failed for reel frame {idx}")

            # Ensure exact dimensions
            img = Image.open(temp_path)
            if img.size != (self.REEL_W, self.REEL_H):
                logger.info("Cropping reel frame %d from %s", idx, img.size)
                if img.size[0] >= self.REEL_W and img.size[1] >= self.REEL_H:
                    l = (img.size[0] - self.REEL_W) // 2
                    t = (img.size[1] - self.REEL_H) // 2
                    img = img.crop((l, t, l + self.REEL_W, t + self.REEL_H))
            img.save(temp_path)
            temp_path.replace(out_path)
            image_paths.append(out_path)
            logger.info("Reel frame %d/%d rendered: %s", idx, total, out_path)

        return image_paths

    # ------------------------------------------------------------------
    # Narration script
    # ------------------------------------------------------------------

    def _generate_narration_script(
        self,
        slides: List[CarouselSlide],
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
    ) -> List[str]:
        """
        Generate ultra-short narration — 12-18 words per slide max.
        Total target: 45-60 seconds.
        """
        slides_text = "\n".join(
            f"Slide {s.slide_number}: {s.text_overlay}" for s in slides
        )

        system_prompt = (
            f"You are a voiceover writer for '{channel_config.name}' Instagram Reels. "
            "You write ultra-short, punchy spoken lines — not paragraphs. "
            "Every line must be under 18 words."
        )

        prompt = f"""### SLIDES:
{slides_text}

### TOPIC: {strategy.topic}
### ANGLE: {strategy.angle}

### TASK:
Write ONE spoken line per slide for a 45-60 second Instagram Reel.

STRICT RULES:
1. MAXIMUM 18 WORDS PER LINE — count every word before submitting.
2. Write how a person actually talks, not how they write.
3. Use natural rhythm: short sentences, pauses with "..."
4. NO filler: no "In this video", "Today we explore", "Stay tuned"
5. Slide 1 hook line: create immediate curiosity in under 5 seconds.
6. CTA line: ask ONE specific question the viewer wants to answer in comments.

GOOD examples (word count shown):
- "Your brain is lying to you right now. It calls that loyalty." (13)
- "Here's what nobody tells you about sunk cost." (8)
- "The number that changed how I think about saving." (9)
- "What's the one thing you'd do differently?" (8)

BAD examples (too long — DO NOT do this):
- "In today's video we're going to explore the fascinating psychology behind why humans continue..."
- "This is a really interesting concept that many people don't fully understand or appreciate..."

Return exactly {len(slides)} lines as JSON:
{{"segments": ["line 1", "line 2", ...]}}

Respond with ONLY JSON. Count your words."""

        response_text = self.generator._generate_text(
            prompt, system_prompt=system_prompt
        )

        try:
            data     = self.generator._parse_json_response(response_text)
            segments = data.get("segments", [])

            trimmed = []
            for i, seg in enumerate(segments):
                words = str(seg).split()
                if len(words) > 20:
                    logger.warning(
                        "Segment %d too long (%d words), trimming", i + 1, len(words)
                    )
                    seg = " ".join(words[:18]) + "."
                trimmed.append(str(seg))

            if len(trimmed) != len(slides):
                logger.warning(
                    "Segment count mismatch (%d vs %d), using slide text fallback",
                    len(trimmed), len(slides)
                )
                return [self._shorten(s.text_overlay) for s in slides]

            return trimmed

        except Exception as e:
            logger.error("Narration parse failed: %s", e)
            return [self._shorten(s.text_overlay) for s in slides]

    def _shorten(self, text: str, max_words: int = 15) -> str:
        words = text.split()
        return text if len(words) <= max_words else " ".join(words[:max_words]) + "."

    # ------------------------------------------------------------------
    # Audio synthesis
    # ------------------------------------------------------------------

    def _create_audio_segments(
        self,
        segments: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        provider = getattr(settings, "tts_provider", "edge").lower()

        if provider == "elevenlabs":
            return self._tts_elevenlabs(segments, output_dir, channel_config)
        elif provider == "edge":
            return self._tts_edge(segments, output_dir, channel_config)
        else:
            return self._tts_gtts(segments, output_dir)

    def _tts_edge(
        self,
        segments: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """Microsoft Edge TTS — free, good Indian English quality."""
        try:
            import edge_tts
        except ImportError:
            logger.warning("edge-tts not installed, falling back to gTTS")
            return self._tts_gtts(segments, output_dir)

        voice = (
            getattr(channel_config, "voice_id", None)
            or getattr(settings, "edge_tts_voice", "en-IN-PrabhatNeural")
        )
        paths: List[Path] = []

        async def _gen():
            for i, text in enumerate(segments, 1):
                p = output_dir / f"audio_{i:02d}.mp3"
                await edge_tts.Communicate(text, voice).save(str(p))
                paths.append(p)
                logger.info("Edge-TTS %d: %s", i, p)

        asyncio.run(_gen())
        return paths

    def _tts_gtts(self, segments: List[str], output_dir: Path) -> List[Path]:
        paths = []
        for i, text in enumerate(segments, 1):
            p = output_dir / f"audio_{i:02d}.mp3"
            gTTS(text=text, lang="en", tld="co.in").save(str(p))
            paths.append(p)
            logger.info("gTTS %d: %s", i, p)
        return paths

    def _tts_elevenlabs(
        self,
        segments: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import save as el_save
        except ImportError:
            logger.warning("elevenlabs not installed, falling back to gTTS")
            return self._tts_gtts(segments, output_dir)

        api_key  = getattr(settings, "elevenlabs_api_key", "")
        voice_id = (
            getattr(channel_config, "voice_id", None)
            or getattr(settings, "elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        )

        if not api_key:
            logger.warning("elevenlabs_api_key not set, falling back to gTTS")
            return self._tts_gtts(segments, output_dir)

        client = ElevenLabs(api_key=api_key)
        paths: List[Path] = []

        for i, text in enumerate(segments, 1):
            p = output_dir / f"audio_{i:02d}.mp3"
            try:
                audio = client.text_to_speech.convert(
                    voice_id=voice_id, text=text,
                    model_id="eleven_multilingual_v2",
                )
                el_save(audio, str(p))
                paths.append(p)
                logger.info("ElevenLabs %d: %s", i, p)
            except Exception as e:
                logger.error("ElevenLabs segment %d failed: %s", i, e)
                gTTS(text=text, lang="en", tld="co.in").save(str(p))
                paths.append(p)

        return paths

    # ------------------------------------------------------------------
    # Video clip building
    # ------------------------------------------------------------------

    def _get_duration(self, path: Path, default: float = 5.0) -> float:
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
            return default

    def _build_clips(
        self,
        image_paths: List[Path],
        audio_paths: List[Path],
        output_dir: Path,
        slide_tail: float,
        transition_dur: float,
    ) -> List[Path]:
        """
        Build one video clip per slide.
        Portrait frame comes directly from the rendered 1080x1920 PNG —
        no scaling or padding needed.
        Slide stays static (no Ken Burns — text must remain readable).
        """
        clip_paths = []
        n = len(image_paths)

        for i, (img, audio) in enumerate(zip(image_paths, audio_paths), 1):
            is_last  = (i == n)
            audio_dur = self._get_duration(audio)
            clip_dur  = audio_dur + slide_tail + (0 if is_last else transition_dur)

            clip_path = output_dir / f"clip_{i:02d}.mp4"

            # Simple filter: static portrait image + normalised audio
            filter_complex = (
                f"[0:v]scale={self.REEL_W}:{self.REEL_H},"
                f"format=yuv420p[v];"
                f"[1:a]aresample=44100,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(self.FPS),
                "-t", str(clip_dur),
                "-i", str(img),
                "-i", str(audio),
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(clip_path),
            ]

            logger.info("[Clip %d/%d] %.1fs — %s", i, n, clip_dur, img.name)
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error("FFmpeg clip %d error:\n%s", i, r.stderr[-500:])
                raise RuntimeError(f"FFmpeg failed for clip {i}")

            clip_paths.append(clip_path)

        return clip_paths

    # ------------------------------------------------------------------
    # Cross-fade blending
    # ------------------------------------------------------------------

    def _blend_clips(
        self,
        clip_paths: List[Path],
        output_dir: Path,
        transition_dur: float,
    ) -> Path:
        """Sequential cross-fade — processes one pair at a time (4GB RAM safe)."""
        if len(clip_paths) == 1:
            return clip_paths[0]

        current = clip_paths[0]

        for i in range(1, len(clip_paths)):
            blended = output_dir / f"blend_{i:02d}.mp4"
            dur     = self._get_duration(current)
            offset  = max(0.0, dur - transition_dur)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(current), "-i", str(clip_paths[i]),
                "-filter_complex",
                (
                    f"[0:v][1:v]xfade=transition=fade"
                    f":duration={transition_dur}:offset={offset:.3f},"
                    f"format=yuv420p[v];"
                    f"[0:a][1:a]acrossfade=d={transition_dur}[a]"
                ),
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                str(blended),
            ]

            logger.info("[Blend %d/%d]", i, len(clip_paths) - 1)
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error("FFmpeg blend error:\n%s", r.stderr[-500:])
                raise RuntimeError(f"FFmpeg blend failed at step {i}")

            current = blended

        return current

    # ------------------------------------------------------------------
    # Music mixing
    # ------------------------------------------------------------------

    def _mix_music(
        self, video_path: Path, output_path: Path, volume: float
    ) -> None:
        music = Path("assets/music/background.mp3")

        if not music.exists():
            logger.info("No background music, skipping mix")
            shutil.copy(video_path, output_path)
            return

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path), "-i", str(music),
            "-filter_complex",
            (
                f"[1:a]aloop=loop=-1:size=100M,volume={volume}[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first[a]"
            ),
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            logger.error("Music mix failed, copying without music")
            shutil.copy(video_path, output_path)

    # ------------------------------------------------------------------
    # Color utilities
    # ------------------------------------------------------------------

    def _extract_color(
        self, palette, key: str, fallback: Optional[str]
    ) -> Optional[str]:
        import json, re
        if isinstance(palette, dict):
            val = palette.get(key)
            if val and str(val).startswith("#"):
                return val
            aliases = {
                "background": ["bg", "background_color"],
                "text": ["primary", "text_color", "foreground"],
                "accent": ["secondary", "highlight", "accent_color"],
            }
            for alias in aliases.get(key, []):
                val = palette.get(alias)
                if val and str(val).startswith("#"):
                    return val
        if isinstance(palette, str):
            try:
                return self._extract_color(json.loads(palette), key, fallback)
            except Exception:
                pass
            if key == "background":
                m = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}", palette)
                if m:
                    return m.group(0)
        return fallback

    def _contrast(self, hex_color: str) -> str:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#000000" if (0.299*r + 0.587*g + 0.114*b) / 255 > 0.5 else "#ffffff"