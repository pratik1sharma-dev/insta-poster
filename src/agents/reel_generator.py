"""
Reel Generator Agent - Transforms carousel slides into high-impact Instagram Reels.

Key improvements:
- Hard 60-second cap: selects best 5 slides, writes 5-7 second narration per slide
- Ken Burns zoom effect on every slide — no more static slideshow feel
- Slide duration driven by actual audio length, not fixed seconds
- ElevenLabs support ready (set tts_provider=elevenlabs in config)
- gTTS kept as free fallback with Indian English accent
- Portrait 1080x1920 output for Reels
"""

import os
import asyncio
import subprocess
import shutil
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple
from gtts import gTTS

from src.models import CarouselSlide, ContentStrategy, ChannelConfig, GeneratedContent
from src.config import settings
from src.agents.content_generator import ContentGenerator


logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Maximum number of slides to include in the Reel.
# Keeping this at 5 targets ~45-60 seconds total.
MAX_REEL_SLIDES = 5

# Pause between narration ending and slide transition (seconds)
SLIDE_TAIL = 0.3

# Cross-fade transition duration (seconds)
TRANSITION_DURATION = 0.4

# Ken Burns zoom: start scale and end scale (subtle zoom in)
KB_SCALE_START = 1.05
KB_SCALE_END   = 1.15

# Background music volume (0.0 - 1.0)
MUSIC_VOLUME = 0.10

# Output resolution
REEL_WIDTH  = 1080
REEL_HEIGHT = 1920

# Square slide size when centred in portrait frame
SLIDE_SIZE  = 1080


class ReelGenerator:
    """
    Converts carousel slides + narration into a portrait Instagram Reel.

    Pipeline:
      1. Select best 5 slides from the carousel
      2. Generate short narration script (5-7 sec per slide)
      3. Synthesise audio per slide (gTTS or ElevenLabs)
      4. Build individual video clips with Ken Burns zoom
      5. Sequential cross-fade blend (safe for 4 GB RAM)
      6. Mix in background music
    """

    def __init__(self):
        self.generator = ContentGenerator()
        self.temp_dir = Path("temp_reel")
        self.temp_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_reel(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        image_paths: List[Path],
        output_path: Path,
    ) -> Path:
        """
        Full pipeline: slides → narration → audio → video → reel.

        Args:
            content:        Generated carousel content (slides, CTA etc.)
            strategy:       Content strategy (topic, angle etc.)
            channel_config: Channel config (name, voice settings etc.)
            image_paths:    Paths to rendered slide PNGs (in slide order)
            output_path:    Where to save the final .mp4

        Returns:
            Path to the generated Reel .mp4
        """
        logger.info("Starting Reel generation: %s", strategy.topic)

        # ── 1. Select slides ───────────────────────────────────────────
        selected_slides, selected_images = self._select_slides(
            content.slides, image_paths
        )
        logger.info(
            "Selected %d slides for Reel: %s",
            len(selected_slides),
            [s.slide_number for s in selected_slides],
        )

        # ── 2. Generate narration script ───────────────────────────────
        script_segments = self._generate_narration_script(
            selected_slides, strategy, channel_config
        )

        # ── 3. Synthesise audio ────────────────────────────────────────
        audio_dir = self.temp_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        audio_paths = self._create_audio_segments(
            script_segments, audio_dir, channel_config
        )

        # ── 4. Build individual clips with Ken Burns ───────────────────
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)
        clip_paths = self._build_clips(selected_images, audio_paths, video_dir)

        # ── 5. Cross-fade blend ────────────────────────────────────────
        blended = self._blend_clips(clip_paths, video_dir)

        # ── 6. Add background music ────────────────────────────────────
        self._mix_music(blended, output_path)

        logger.info("Reel generated: %s", output_path)
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
    ) -> Tuple[List[CarouselSlide], List[Path]]:
        """
        Pick the best slides for the Reel, capped at MAX_REEL_SLIDES.

        Strategy:
        - Always include slide 1 (hook)
        - Always include the last slide (CTA)
        - Fill the middle with the highest-value content slides
          (currently: first N content slides after hook)
        """
        if len(slides) <= MAX_REEL_SLIDES:
            return slides, image_paths[:len(slides)]

        # Build a path lookup keyed by slide number
        path_by_num = {}
        for slide, path in zip(slides, image_paths):
            path_by_num[slide.slide_number] = path

        hook   = [s for s in slides if s.slide_number == 1]
        cta    = [s for s in slides if s.purpose.value == "cta"]
        middle = [
            s for s in slides
            if s.slide_number != 1 and s.purpose.value != "cta"
        ]

        # Take the strongest middle slides (favour big_fact and split_comparison)
        priority_order = {"big_fact": 0, "split_comparison": 1, "standard": 2}
        middle_sorted = sorted(
            middle,
            key=lambda s: (priority_order.get(s.template_name or "standard", 2), s.slide_number)
        )

        slots = MAX_REEL_SLIDES - len(hook) - len(cta)
        selected = hook + middle_sorted[:slots] + cta

        # Re-sort by original slide number to preserve story order
        selected.sort(key=lambda s: s.slide_number)

        selected_paths = [path_by_num[s.slide_number] for s in selected]
        return selected, selected_paths

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
        Generate ultra-short narration per slide (5-7 seconds = ~15-20 words).

        The key difference from the old version: we enforce a strict word
        count so the total Reel stays under 60 seconds.
        """
        slides_text = "\n".join(
            f"Slide {s.slide_number}: {s.text_overlay}" for s in slides
        )

        system_prompt = (
            f"You are a voiceover writer for '{channel_config.name}' Instagram Reels. "
            "You write ultra-short, punchy spoken lines — not paragraphs."
        )

        prompt = f"""### SLIDES:
{slides_text}

### TOPIC: {strategy.topic}
### ANGLE: {strategy.angle}

### TASK:
Write ONE spoken line per slide for a 45-60 second Instagram Reel.

STRICT RULES:
1. Each line must be 12-18 words MAXIMUM — this is non-negotiable.
   Count the words. If over 18 words, cut it.
2. Write how a person talks, not how they write.
3. Use natural spoken rhythm: short punchy sentences, natural pauses with "..."
4. NO filler phrases: no "In this video", "Today we'll explore", "Stay tuned"
5. The hook line (slide 1) must create immediate curiosity in under 5 seconds.
6. The CTA line must ask one specific question the viewer wants to answer.

GOOD examples (count the words — all under 18):
- "Your brain is lying to you right now. And it calls that loyalty." (15 words)
- "Here's what nobody tells you about sunk cost." (8 words)
- "The number that changed how I think about saving." (9 words)

BAD examples (too long):
- "In today's video we're going to explore the fascinating psychology behind why humans continue to invest..."
- "This is a really interesting concept that many people don't fully understand..."

Return exactly {len(slides)} lines as a JSON array:
{{"segments": ["line 1", "line 2", ...]}}

Respond with ONLY JSON."""

        response_text = self.generator._generate_text(prompt, system_prompt=system_prompt)

        try:
            data = self.generator._parse_json_response(response_text)
            segments = data.get("segments", [])

            # Validate and trim each segment to 18 words max as a safety net
            trimmed = []
            for i, seg in enumerate(segments):
                words = seg.split()
                if len(words) > 20:
                    logger.warning(
                        "Narration segment %d too long (%d words), trimming: %s",
                        i + 1, len(words), seg
                    )
                    seg = " ".join(words[:18]) + "."
                trimmed.append(seg)

            if len(trimmed) != len(slides):
                logger.warning(
                    "Segment count mismatch (%d vs %d), falling back to slide text",
                    len(trimmed), len(slides)
                )
                return [self._shorten_text(s.text_overlay) for s in slides]

            return trimmed

        except Exception as e:
            logger.error("Failed to parse narration script: %s", e)
            return [self._shorten_text(s.text_overlay) for s in slides]

    def _shorten_text(self, text: str, max_words: int = 15) -> str:
        """Trim text to max_words as a fallback for narration."""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + "."

    # ------------------------------------------------------------------
    # Audio synthesis
    # ------------------------------------------------------------------

    def _create_audio_segments(
        self,
        script_segments: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """
        Synthesise audio for each narration segment.

        Providers (set tts_provider in config):
          - elevenlabs  : Best quality, requires API key + Starter plan
          - edge        : Good quality, free (Microsoft Edge TTS)
          - gtts        : Free, robotic (default fallback)
        """
        provider = getattr(settings, "tts_provider", "gtts").lower()
        audio_paths: List[Path] = []

        if provider == "elevenlabs":
            audio_paths = self._synthesise_elevenlabs(
                script_segments, output_dir, channel_config
            )

        elif provider == "edge":
            audio_paths = self._synthesise_edge(
                script_segments, output_dir, channel_config
            )

        else:
            # gTTS — free, Indian English accent
            for i, text in enumerate(script_segments, 1):
                audio_path = output_dir / f"audio_{i:02d}.mp3"
                tts = gTTS(text=text, lang="en", tld="co.in")
                tts.save(str(audio_path))
                audio_paths.append(audio_path)
                logger.info("gTTS audio %d: %s", i, audio_path)

        return audio_paths

    def _synthesise_edge(
        self,
        segments: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """Microsoft Edge TTS — free, much better quality than gTTS."""
        try:
            import edge_tts
        except ImportError:
            logger.warning("edge-tts not installed, falling back to gTTS")
            return self._synthesise_gtts(segments, output_dir)

        voice = getattr(channel_config, "voice_id", None) or getattr(
            settings, "edge_tts_voice", "en-IN-NeerjaNeural"
        )
        audio_paths: List[Path] = []

        async def _gen():
            for i, text in enumerate(segments, 1):
                audio_path = output_dir / f"audio_{i:02d}.mp3"
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(audio_path))
                audio_paths.append(audio_path)
                logger.info("Edge-TTS audio %d: %s", i, audio_path)

        asyncio.run(_gen())
        return audio_paths

    def _synthesise_gtts(
        self,
        segments: List[str],
        output_dir: Path,
    ) -> List[Path]:
        """gTTS fallback."""
        audio_paths = []
        for i, text in enumerate(segments, 1):
            audio_path = output_dir / f"audio_{i:02d}.mp3"
            tts = gTTS(text=text, lang="en", tld="co.in")
            tts.save(str(audio_path))
            audio_paths.append(audio_path)
        return audio_paths

    def _synthesise_elevenlabs(
        self,
        segments: List[str],
        output_dir: Path,
        channel_config: ChannelConfig,
    ) -> List[Path]:
        """
        ElevenLabs TTS — best quality.
        Requires: pip install elevenlabs
                  settings.elevenlabs_api_key
                  settings.elevenlabs_voice_id  (or channel_config.voice_id)
        Commercial use requires Starter plan ($5/month minimum).
        """
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import save as el_save
        except ImportError:
            logger.warning("elevenlabs package not installed, falling back to gTTS")
            return self._synthesise_gtts(segments, output_dir)

        api_key  = getattr(settings, "elevenlabs_api_key", None)
        voice_id = (
            getattr(channel_config, "voice_id", None)
            or getattr(settings, "elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        )

        if not api_key:
            logger.warning("elevenlabs_api_key not set, falling back to gTTS")
            return self._synthesise_gtts(segments, output_dir)

        client = ElevenLabs(api_key=api_key)
        audio_paths: List[Path] = []

        for i, text in enumerate(segments, 1):
            audio_path = output_dir / f"audio_{i:02d}.mp3"
            try:
                audio = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=text,
                    model_id="eleven_multilingual_v2",
                )
                el_save(audio, str(audio_path))
                audio_paths.append(audio_path)
                logger.info("ElevenLabs audio %d: %s", i, audio_path)
            except Exception as e:
                logger.error("ElevenLabs failed for segment %d: %s", i, e)
                # Fallback for this segment
                tts = gTTS(text=text, lang="en", tld="co.in")
                tts.save(str(audio_path))
                audio_paths.append(audio_path)

        return audio_paths

    # ------------------------------------------------------------------
    # Video clip building
    # ------------------------------------------------------------------

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio duration via ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            logger.warning("Could not parse audio duration for %s, using 5.0s", audio_path)
            return 5.0

    def _build_clips(
        self,
        image_paths: List[Path],
        audio_paths: List[Path],
        output_dir: Path,
    ) -> List[Path]:
        """
        Build one video clip per slide with:
        - Portrait 1080x1920 frame
        - Square slide centred vertically (blurred version fills top/bottom)
        - Ken Burns slow zoom on the slide
        - Audio narration synced exactly
        """
        clip_paths = []
        n = len(image_paths)

        for i, (img_path, audio_path) in enumerate(zip(image_paths, audio_paths), 1):
            is_last = (i == n)
            audio_dur = self._get_audio_duration(audio_path)
            # Add tail for transition overlap on all but last slide
            clip_dur = audio_dur + SLIDE_TAIL + (0 if is_last else TRANSITION_DURATION)

            clip_path = output_dir / f"clip_{i:02d}.mp4"

            # ── FFmpeg filter chain ──────────────────────────────────────
            #
            # [bg]: blurred, darkened version of the slide fills 1080x1920
            #       (fills the top/bottom black bars with a matching blur)
            # [fg]: Ken Burns zoom on the actual slide (1080x1080)
            # Overlay fg centred vertically on bg
            #
            # Ken Burns: zoompan filter
            #   z = zoom level, d = total frames, x/y = pan offsets
            #   We zoom from KB_SCALE_START to KB_SCALE_END over the clip
            #   x/y kept at centre of the image

            fps = 25
            total_frames = int(clip_dur * fps)

            # zoompan zoom expression: linearly interpolate from start to end
            zoom_expr = (
                f"'min({KB_SCALE_START}+({KB_SCALE_END}-{KB_SCALE_START})*on/{total_frames},{KB_SCALE_END})'"
            )
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = "'ih/2-(ih/zoom/2)'"

            filter_complex = (
                # Background: scale slide to fill portrait frame, blur+darken
                f"[0:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={REEL_WIDTH}:{REEL_HEIGHT},"
                f"boxblur=25:5,"
                f"colorchannelmixer=rr=0.5:gg=0.5:bb=0.5[bg];"

                # Foreground: Ken Burns zoom on 1080x1080 slide
                f"[0:v]scale={SLIDE_SIZE}:{SLIDE_SIZE},"
                f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
                f":d={total_frames}:s={SLIDE_SIZE}x{SLIDE_SIZE}:fps={fps}[fg];"

                # Overlay fg centred on bg
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v];"

                # Audio: normalise format
                f"[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(fps),
                "-t", str(clip_dur),
                "-i", str(img_path),
                "-i", str(audio_path),
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(clip_path),
            ]

            logger.info("[Clip %d/%d] Building %.1fs clip with Ken Burns", i, n, clip_dur)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("FFmpeg clip error (slide %d):\n%s", i, result.stderr[-500:])
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
    ) -> Path:
        """
        Sequential cross-fade blend — safe for 4 GB RAM.
        Processes one pair at a time instead of all clips simultaneously.
        """
        if len(clip_paths) == 1:
            return clip_paths[0]

        current = clip_paths[0]

        for i in range(1, len(clip_paths)):
            next_clip = clip_paths[i]
            blended = output_dir / f"blend_{i:02d}.mp4"

            # Get current clip duration for xfade offset
            dur = self._get_video_duration(current)
            offset = max(0.0, dur - TRANSITION_DURATION)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(current),
                "-i", str(next_clip),
                "-filter_complex",
                (
                    f"[0:v][1:v]xfade=transition=fade"
                    f":duration={TRANSITION_DURATION}:offset={offset:.3f},"
                    f"format=yuv420p[v];"
                    f"[0:a][1:a]acrossfade=d={TRANSITION_DURATION}[a]"
                ),
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                str(blended),
            ]

            logger.info("[Blend %d/%d] Cross-fading clips", i, len(clip_paths) - 1)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("FFmpeg blend error:\n%s", result.stderr[-500:])
                raise RuntimeError(f"FFmpeg blend failed at step {i}")

            current = blended

        return current

    # ------------------------------------------------------------------
    # Music mixing
    # ------------------------------------------------------------------

    def _mix_music(self, video_path: Path, output_path: Path) -> None:
        """
        Mix background music into the final video at low volume.
        Falls back to copying the video if music file is missing.
        """
        music_path = Path("assets/music/background.mp3")

        if not music_path.exists():
            logger.info("No background music found, skipping mix")
            shutil.copy(video_path, output_path)
            return

        logger.info("Mixing background music at volume %.2f", MUSIC_VOLUME)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex",
            (
                f"[1:a]aloop=loop=-1:size=100M,"
                f"volume={MUSIC_VOLUME}[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first[a]"
            ),
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(
                "Music mix failed, copying unmixed video:\n%s",
                result.stderr[-300:]
            )
            shutil.copy(video_path, output_path)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _get_video_duration(self, video_path: Path) -> float:
        """Get video duration via ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0