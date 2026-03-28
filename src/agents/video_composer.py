import logging
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


class VideoComposer:
    """
    Handles all FFmpeg-based video composition: building per-clip videos with
    motion and kinetic text, blending them together with crossfades, and mixing
    background music.
    """

    REEL_W = 1080
    REEL_H = 1920
    FPS = 25

    @property
    def FONT_PATH(self) -> str:
        return settings.cinematic_font_path

    @property
    def FONT_BOLD_PATH(self) -> str:
        return settings.cinematic_font_bold_path

    # Normalize characters that have special meaning in FFmpeg drawtext / filter graph.
    # ASCII apostrophe (0x27) is the filter-graph quote delimiter — replace with U+2019
    # which is visually identical but has no special meaning in FFmpeg.
    _UNICODE_NORMALIZE = str.maketrans({
        "'": '\u2019',    # ASCII apostrophe → right single quote (safe in FFmpeg)
        '\u2018': '\u2019',  # left single quotation mark → right single quote
        '\u201c': '"',    # left double quotation mark
        '\u201d': '"',    # right double quotation mark
        '\u2014': ' - ',  # em dash
        '\u2013': '-',    # en dash
        '\u2026': '...',  # ellipsis
    })

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_clips(
        self,
        scenes: List[dict],
        output_dir: Path,
        transition_dur: float,
        audio_paths: Optional[List[Path]] = None,
    ) -> List[Path]:
        """Build one video clip per text line across all scenes."""
        return self._build_cinematic_clips(scenes, output_dir, transition_dur, audio_paths)

    def blend_clips(
        self,
        clip_paths: List[Path],
        output_dir: Path,
        transition_dur: float,
    ) -> Path:
        """Blend a list of clip paths into a single video with crossfade transitions."""
        return self._blend_clips(clip_paths, output_dir, transition_dur)

    def mix_music(self, video_path: Path, output_path: Path, volume: float) -> None:
        """Mix background music into the video at the given volume."""
        self._mix_music(video_path, output_path, volume)

    # ------------------------------------------------------------------
    # Motion filter
    # ------------------------------------------------------------------

    def _build_motion_filter(self, motion: str, clip_dur: float) -> str:
        """
        Build an FFmpeg filter string for Ken Burns / pan motion effects.
        Applied to looped PNG input before text overlay.
        """
        frames = max(1, int(clip_dur * self.FPS))
        W, H = self.REEL_W, self.REEL_H
        fps = self.FPS

        if motion == "zoom_in":
            rate = 0.15 / frames
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='min(1+on*{rate:.6f},1.15)':"
                f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        elif motion == "zoom_out":
            rate = 0.15 / frames
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='max(1.15-on*{rate:.6f},1.0)':"
                f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        elif motion == "pan_right":
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='1.1':"
                f"x='(iw-iw/zoom)*on/{frames}':"
                f"y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        elif motion == "pan_left":
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='1.1':"
                f"x='(iw-iw/zoom)*(1-on/{frames})':"
                f"y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        else:
            return f"scale={W}:{H},setsar=1"

    # ------------------------------------------------------------------
    # Text escape + animation
    # ------------------------------------------------------------------

    def _escape(self, s: str) -> str:
        """Escape text for safe use in FFmpeg drawtext filter.

        _UNICODE_NORMALIZE converts ASCII apostrophe to U+2019 (right single quote)
        so no quote escaping is needed here. Documented FFmpeg drawtext escapes only:
        - Backslash must be doubled: \\ -> \\\\
        - Percent sign: % -> %%  (drawtext text expansion engine)
        - Colon must be escaped: : -> \\:  (filter graph option separator)
        """
        s = s.translate(self._UNICODE_NORMALIZE)
        s = s.replace('\r\n', '\n').replace('\r', '\n')
        s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', s)
        return (
            s.replace('\\', '\\\\')
             .replace('%', '%%')    # drawtext text expansion escape (documented)
             .replace(':', '\\:')   # filter graph option separator
             .replace('\n', '\\n')
        )

    def _create_kinetic_text_overlay(
        self,
        text: str,
        style: str,
        duration: float,
        index: int = 1,
        total: int = 4,
        bold: bool = False,
    ) -> str:
        """
        Generate FFmpeg drawtext filter string with kinetic text animations.

        Styles:
            hook    — fast fade in
            main    — fade + slide from left
            number  — scale emphasis (zoom in on the stat)
            insight — slow reveal
        """
        wrapped_lines = textwrap.wrap(text, width=24) or [text]

        FONTSIZE = 56
        LINE_HEIGHT = int(FONTSIZE * 1.25)  # ~70px per line
        LINE_GAP = 12
        BORDER = 30
        font = self.FONT_BOLD_PATH if bold else self.FONT_PATH

        def _build_stacked(
            lines: list,
            alpha_expr: str,
            x_expr: str = "(w-text_w)/2",
            fontsize_expr: str = str(FONTSIZE),
        ) -> str:
            """Build one drawtext filter per line, vertically centered as a block."""
            total_h = len(lines) * LINE_HEIGHT + (len(lines) - 1) * LINE_GAP
            block_top = f"(h-{total_h})/2+200"
            parts = []
            for i, ln in enumerate(lines):
                y = f"({block_top})+{i * (LINE_HEIGHT + LINE_GAP)}"
                parts.append(
                    f"drawtext=text='{self._escape(ln)}':"
                    f"fontfile='{font}':"
                    f"fontcolor=white:fontsize={fontsize_expr}:"
                    f"x='{x_expr}':y='{y}':"
                    f"box=1:boxcolor=black@0.5:boxborderw={BORDER}:"
                    f"fix_bounds=1:"
                    f"alpha='{alpha_expr}'"
                )
            return ",".join(parts)

        speed_multipliers = {'slow': 1.5, 'medium': 1.0, 'fast': 0.7}
        speed = getattr(settings, "cinematic_animation_speed", "medium")
        multiplier = speed_multipliers.get(speed, 1.0)

        if style == 'hook':
            reveal_duration = 0.5 * multiplier
            return _build_stacked(wrapped_lines, f"if(lt(t,{reveal_duration}),t/{reveal_duration},1)")

        elif style == 'main':
            fade_duration = 0.5 * multiplier
            slide_distance = 50
            x_expr = f"if(lt(t,{fade_duration}),(w-text_w)/2-{slide_distance}*(1-t/{fade_duration}),(w-text_w)/2)"
            return _build_stacked(wrapped_lines, f"if(lt(t,{fade_duration}),t/{fade_duration},1)", x_expr)

        elif style == 'number':
            # Use a static larger fontsize — dynamic fontsize expressions with `t`
            # can silently fail on some FFmpeg builds, making the entire drawtext
            # filter invisible. The emphasis effect comes from size + fast fade-in.
            return _build_stacked(
                wrapped_lines,
                alpha_expr="if(lt(t,0.2),t/0.2,1)",
                fontsize_expr=str(int(FONTSIZE * 1.15)),
            )

        elif style == 'insight':
            reveal_duration = min(duration * 0.7, 2.5 * multiplier)
            return _build_stacked(wrapped_lines, f"if(lt(t,{reveal_duration}),t/{reveal_duration},1)")

        else:
            fade_duration = 0.3 * multiplier
            return _build_stacked(wrapped_lines, f"if(lt(t,{fade_duration}),t/{fade_duration},1)")

    # ------------------------------------------------------------------
    # Clip building
    # ------------------------------------------------------------------

    def _build_cinematic_clips(
        self,
        scenes: List[dict],
        output_dir: Path,
        transition_dur: float,
        audio_paths: Optional[List[Path]] = None,
    ) -> List[Path]:
        """
        Build one video clip per text line.
        Lines within the same scene share the same image + motion effect.
        """
        clip_paths = []
        audio_index = 0

        total_lines = sum(len(sc["lines"]) for sc in scenes)
        clip_number = 0

        for scene_idx, scene in enumerate(scenes):
            img = scene["image_path"]
            motion = scene.get("motion", "zoom_in")

            for line_idx, text in enumerate(scene["lines"]):
                clip_number += 1
                is_last_clip = (clip_number == total_lines)
                clip_path = output_dir / f"clip_{clip_number:02d}.mp4"

                # Determine clip duration
                if audio_paths and audio_index < len(audio_paths):
                    audio_dur = self._get_duration(audio_paths[audio_index])
                    slide_dur = audio_dur + 0.3
                    logger.info("[Clip %d] Voice mode: audio %.1fs + 0.3s tail", clip_number, audio_dur)
                else:
                    word_count = len(text.split())
                    slide_dur = max(3.5, (word_count / 3.5) + 1.5)
                    logger.info("[Clip %d] Text mode: %d words → %.1fs duration", clip_number, word_count, slide_dur)

                clip_dur = slide_dur + (0 if is_last_clip else transition_dur)
                motion_filter = self._build_motion_filter(motion, clip_dur)

                # Determine text style
                animation_enabled = getattr(settings, "cinematic_text_animation_enabled", True)
                if animation_enabled:
                    if clip_number == 1:
                        text_style = 'hook'
                    elif is_last_clip:
                        text_style = 'insight'
                    elif self._is_punchline_number(text):
                        text_style = 'number'
                    else:
                        text_style = 'main'
                    use_bold = text_style in ('hook', 'number', 'insight')
                else:
                    text_style = 'hook'
                    use_bold = True

                logger.info("[Clip %d] Scene %d, motion=%s, style=%s, bold=%s",
                            clip_number, scene_idx + 1, motion, text_style, use_bold)

                drawtext_filter = self._create_kinetic_text_overlay(
                    text, text_style, slide_dur, clip_number, total_lines, bold=use_bold
                )

                # Build FFmpeg command
                has_audio = bool(audio_paths and audio_index < len(audio_paths))
                if has_audio:
                    filter_complex = (
                        f"[0:v]{motion_filter},{drawtext_filter},format=yuv420p[v];"
                        f"[1:a]volume=1.0[a]"
                    )
                    cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1", "-framerate", str(self.FPS),
                        "-t", str(clip_dur),
                        "-i", str(img),
                        "-i", str(audio_paths[audio_index]),
                        "-filter_complex", filter_complex,
                        "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "192k",
                        "-t", str(round(clip_dur, 3)),
                        "-shortest",
                        str(clip_path),
                    ]
                else:
                    filter_complex = f"[0:v]{motion_filter},{drawtext_filter},format=yuv420p[v]"
                    cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1", "-framerate", str(self.FPS),
                        "-t", str(clip_dur),
                        "-i", str(img),
                        "-filter_complex", filter_complex,
                        "-map", "[v]",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-t", str(round(clip_dur, 3)),
                        str(clip_path),
                    ]

                logger.info("[Cinematic Clip %d/%d] Rendering...", clip_number, total_lines)
                result = subprocess.run(cmd, capture_output=True, check=True)

                ffmpeg_warnings = list(dict.fromkeys(
                    line for line in result.stderr.decode(errors="replace").splitlines()
                    if any(kw in line for kw in ("drawtext", "error", "warning", "invalid", "unable"))
                    and "Stray %%" not in line
                ))
                if ffmpeg_warnings:
                    logger.warning("[Clip %d] FFmpeg warnings detected:", clip_number)
                    for line in ffmpeg_warnings:
                        logger.warning("[Clip %d] FFmpeg: %s", clip_number, line)
                    logger.warning("[Clip %d] filter_complex: %s", clip_number, filter_complex)

                clip_paths.append(clip_path)
                audio_index += 1

        return clip_paths

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_punchline_number(self, text: str) -> bool:
        """Return True when a big financial figure is the primary point of the line."""
        return bool(re.search(
            r'(₹\s*[\d,]+|[\d,]+\s*(lakh|crore|%|percent)|\b\d{5,}\b)',
            text, re.IGNORECASE,
        ))

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

    def _has_audio_stream(self, path: Path) -> bool:
        """Return True if the video file has an audio stream."""
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
        )
        return "audio" in r.stdout

    def _blend_clips(self, clip_paths: List[Path], output_dir: Path, transition_dur: float) -> Path:
        """Blend clips with crossfade transitions, preserving audio when present."""
        if len(clip_paths) == 1:
            return clip_paths[0]

        current = clip_paths[0]
        for i in range(1, len(clip_paths)):
            blended = output_dir / f"blend_{i:02d}.mp4"
            dur = self._get_duration(current)
            offset = max(0.0, dur - transition_dur)

            has_audio = self._has_audio_stream(current) and self._has_audio_stream(clip_paths[i])

            if has_audio:
                filter_complex = (
                    f"[0:v][1:v]xfade=transition=fade:duration={transition_dur}:offset={offset:.3f},format=yuv420p[v];"
                    f"[0:a][1:a]acrossfade=d={transition_dur}[a]"
                )
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(current), "-i", str(clip_paths[i]),
                    "-filter_complex", filter_complex,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    str(blended),
                ]
            else:
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
        """Mix background music into video. Blends with existing voice audio if present."""
        music = Path("assets/music/background.mp3")
        if not music.exists():
            shutil.copy(video_path, output_path)
            return

        has_voice = self._has_audio_stream(video_path)

        if has_voice:
            # Mix voice + background music — voice stays at full volume, music ducked
            filter_complex = (
                f"[1:a]volume={volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path), "-i", str(music),
                "-filter_complex", filter_complex,
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(output_path),
            ]
        else:
            # No voice — just add background music
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path), "-i", str(music),
                "-filter_complex", f"[1:a]volume={volume}[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(output_path),
            ]

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            logger.warning("Music mixing failed, copying video without music: %s", r.stderr[-200:])
            shutil.copy(video_path, output_path)
