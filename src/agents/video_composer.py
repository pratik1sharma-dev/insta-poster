import logging
import re
import shutil
import subprocess
import textwrap
import tempfile
import threading
import os
import uuid
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

    # Normalize Unicode typographic characters to ASCII before passing to FFmpeg drawtext
    _UNICODE_NORMALIZE = str.maketrans({
        '\u2018': "'",    # left single quotation mark
        '\u2019': "'",    # right single quotation mark
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
            # Slow zoom from 1.0 to 1.15
            rate = 0.15 / frames
            return (
                f"scale={W*2}:{H*2},"  # upscale first to avoid quality loss during crop
                f"zoompan=z='min(1+on*{rate:.6f},1.15)':"
                f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        elif motion == "zoom_out":
            # Slow zoom from 1.15 to 1.0
            rate = 0.15 / frames
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='max(1.15-on*{rate:.6f},1.0)':"
                f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        elif motion == "pan_right":
            # Pan from left to right, zoom at 1.1
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='1.1':"
                f"x='(iw-iw/zoom)*on/{frames}':"
                f"y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        elif motion == "pan_left":
            # Pan from right to left, zoom at 1.1
            return (
                f"scale={W*2}:{H*2},"
                f"zoompan=z='1.1':"
                f"x='(iw-iw/zoom)*(1-on/{frames})':"
                f"y='(ih-ih/zoom)/2':"
                f"d={frames}:s={W}x{H}:fps={fps}"
            )
        else:
            # static — just scale
            return f"scale={W}:{H},setsar=1"

    # ------------------------------------------------------------------
    # Text Animation
    # ------------------------------------------------------------------

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
        # If the input contains explicit newlines, preserve the whole block
        # as a single textfile (FIFO) so the visual text matches the input
        # exactly (including line breaks). Otherwise fall back to wrapping.
        normalized_text = text.replace('\r\n', '\n').replace('\r', '\n')
        if '\n' in normalized_text:
            wrapped_lines = [normalized_text]
            preserve_block = True
        else:
            wrapped_lines = textwrap.wrap(text, width=24) or [text]
            preserve_block = False

        FONTSIZE = 56
        LINE_HEIGHT = int(FONTSIZE * 1.25)  # ~70px per line
        LINE_GAP = 12
        BORDER = 30
        font = self.FONT_BOLD_PATH if bold else self.FONT_PATH

        def _escape(s: str) -> str:
            s = s.translate(self._UNICODE_NORMALIZE)
            # Escape for ffmpeg drawtext filter expressions (not shell quoting).
            # - backslash must be doubled
            # - single quote must be escaped as \' inside single-quoted drawtext strings
            # - percent signs are special in drawtext (used for expansions) and should be escaped as \%
            # - colon separates drawtext parameters and must be escaped as \:
            # Replace CR/LF with explicit \n sequences (drawtext understands \n)
            s = s.replace('\r\n', '\n').replace('\r', '\n')
            # Remove other non-printable/control chars (except newline)
            s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', s)
            return (
                s.replace('\\', '\\\\')
                 .replace("'", "\\'")
                 # Use double-percent (%%) so drawtext prints a single '%' literal
                 .replace('%', '%%')
                 # Escape backticks and dollar signs to avoid any parser/shell surprises
                 .replace('`', '\\`')
                 .replace('$', '\\$')
                 .replace(':', '\\:')
                 .replace('\n', '\\n')
            )

        def _build_stacked(lines: list, alpha_expr: str, x_expr: str = "(w-text_w)/2") -> str:
            """Build one drawtext filter per line, vertically centered as a block."""
            total_h = len(lines) * LINE_HEIGHT + (len(lines) - 1) * LINE_GAP
            # Position block in lower-center (offset +200 from true center)
            block_top = f"(h-{total_h})/2+200"
            parts = []
            for i, ln in enumerate(lines):
                y = f"({block_top})+{i * (LINE_HEIGHT + LINE_GAP)}"
                # Try to create a named pipe (FIFO) and register the text to be written
                # to it. Using drawtext=textfile=<fifo> lets ffmpeg read UTF-8 content
                # directly and avoids complex escaping. If FIFO creation fails, fall
                # back to inline-escaped text.
                fifo_path = None
                try:
                    fifo_path = os.path.join(tempfile.gettempdir(), f"vc_text_{uuid.uuid4().hex}.fifo")
                    os.mkfifo(fifo_path)
                    # register content to be written later by the caller
                    pending = getattr(self, '_pending_fifos', None)
                    if pending is None:
                        # If preserving the whole block, write the entire normalized
                        # block into a single FIFO entry so drawtext shows exact input.
                        if preserve_block:
                            self._pending_fifos = [(fifo_path, wrapped_lines[0])]
                        else:
                            self._pending_fifos = [(fifo_path, ln)]
                    else:
                        if preserve_block:
                            pending.append((fifo_path, wrapped_lines[0]))
                        else:
                            pending.append((fifo_path, ln))
                except Exception:
                    fifo_path = None

                if fifo_path:
                    parts.append(
                        f"drawtext=textfile='{fifo_path}':"
                        f"fontfile='{font}':"
                        f"fontcolor=white:fontsize={FONTSIZE}:"
                        f"x='{x_expr}':y='{y}':"
                        f"box=1:boxcolor=black@0.5:boxborderw={BORDER}:"
                        f"fix_bounds=1:"
                        f"alpha='{alpha_expr}'"
                    )
                else:
                    parts.append(
                        f"drawtext=text='{_escape(ln)}':"
                        f"fontfile='{font}':"
                        f"fontcolor=white:fontsize={FONTSIZE}:"
                        f"x='{x_expr}':y='{y}':"
                        f"box=1:boxcolor=black@0.5:boxborderw={BORDER}:"
                        f"fix_bounds=1:"
                        f"alpha='{alpha_expr}'"
                    )
            return ",".join(parts)

        # Animation speed configuration
        speed_multipliers = {
            'slow': 1.5,
            'medium': 1.0,
            'fast': 0.7,
        }
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
            # Numbers are usually one short line; scale effect on fontsize
            scale_duration = 0.4 * multiplier
            max_scale = 1.15
            total_h = len(wrapped_lines) * LINE_HEIGHT + (len(wrapped_lines) - 1) * LINE_GAP
            block_top = f"(h-{total_h})/2+200"
            parts = []
            for i, ln in enumerate(wrapped_lines):
                y = f"({block_top})+{i * (LINE_HEIGHT + LINE_GAP)}"
                parts.append(
                    f"drawtext=text='{_escape(ln)}':"
                    f"fontfile='{font}':"
                    f"fontcolor=white:"
                    f"fontsize='{FONTSIZE}*if(lt(t,{scale_duration}),1+{max_scale-1}*(1-t/{scale_duration}),1)':"
                    f"x='(w-text_w)/2':y='{y}':"
                    f"box=1:boxcolor=black@0.5:boxborderw={BORDER}:"
                    f"fix_bounds=1:"
                    f"alpha='if(lt(t,0.2),t/0.2,1)'"
                )
            return ",".join(parts)

        elif style == 'insight':
            reveal_duration = min(duration * 0.7, 2.5 * multiplier)
            return _build_stacked(wrapped_lines, f"if(lt(t,{reveal_duration}),t/{reveal_duration},1)")

        else:
            # Default: simple fade in
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
        audio_index = 0  # running index across all lines

        # Flatten total count for logging
        total_lines = sum(len(sc["lines"]) for sc in scenes)
        clip_number = 0

        for scene_idx, scene in enumerate(scenes):
            img = scene["image_path"]
            motion = scene.get("motion", "zoom_in")
            is_last_scene = (scene_idx == len(scenes) - 1)

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

                # Build motion filter for this clip
                motion_filter = self._build_motion_filter(motion, clip_dur)

                # Build text overlay
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
                    logger.info("[Clip %d] Scene %d, motion=%s, style=%s, bold=%s", clip_number, scene_idx + 1, motion, text_style, use_bold)
                    drawtext_filter = self._create_kinetic_text_overlay(text, text_style, slide_dur, clip_number, total_lines, bold=use_bold)
                    # Log the generated drawtext filter for debugging (trim long filters)
                    try:
                        logger.debug("[Clip %d] drawtext_filter: %s", clip_number, (drawtext_filter[:1000] + '...') if len(drawtext_filter) > 1000 else drawtext_filter)
                    except Exception:
                        logger.debug("[Clip %d] drawtext_filter: <unprintable>", clip_number)
                else:
                    # Animation disabled — use same stacked-drawtext approach for consistent wrapping
                    drawtext_filter = self._create_kinetic_text_overlay(text, 'hook', slide_dur, clip_number, total_lines, bold=True)
                    try:
                        logger.debug("[Clip %d] drawtext_filter (animation disabled): %s", clip_number, (drawtext_filter[:1000] + '...') if len(drawtext_filter) > 1000 else drawtext_filter)
                    except Exception:
                        logger.debug("[Clip %d] drawtext_filter: <unprintable>", clip_number)

                # Build FFmpeg command
                if audio_paths and audio_index < len(audio_paths):
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
                        "-t", str(round(clip_dur, 3)),  # output cap: zoompan can exceed input -t
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
                        "-t", str(round(clip_dur, 3)),  # output cap: zoompan can exceed input -t
                        str(clip_path),
                    ]

                logger.info("[Cinematic Clip %d/%d] Rendering...", clip_number, total_lines)
                # If FIFOs were created for this clip's text, start writer threads
                fifo_threads = []
                pending = getattr(self, '_pending_fifos', None)
                if pending:
                    # Start a thread per FIFO that will open the FIFO for writing
                    # and write the UTF-8 content. Starting writers before ffmpeg
                    # is fine — they will block until ffmpeg opens the FIFO for
                    # reading.
                    def _writer(path: str, content: str):
                        try:
                            # Double percent signs so ffmpeg drawtext treats them as
                            # literals (%% -> prints %). This preserves visual '%' while
                            # avoiding expansion sequences.
                            safe = content.replace('%', '%%')
                            with open(path, 'wb') as w:
                                w.write(safe.encode('utf-8'))
                        except Exception:
                            # ignore writer errors; ffmpeg will raise if it needs the file
                            pass

                    for path, content in pending:
                        # Log FIFO path and a safe preview of content
                        try:
                            preview = (content[:200] + '...') if len(content) > 200 else content
                            logger.debug("[Clip %d] registering FIFO %s -> %r", clip_number, path, preview)
                        except Exception:
                            logger.debug("[Clip %d] registering FIFO %s", clip_number, path)
                        t = threading.Thread(target=_writer, args=(path, content), daemon=True)
                        t.start()
                        fifo_threads.append((t, path))
                    # clear pending list so subsequent clips don't reuse same FIFOs
                    delattr = False
                    try:
                        del self._pending_fifos
                    except Exception:
                        pass

                try:
                    result = subprocess.run(cmd, capture_output=True, check=True)
                finally:
                    # Ensure FIFO writer threads are joined and FIFOs removed
                    if fifo_threads:
                        for t, path in fifo_threads:
                            try:
                                t.join(timeout=5)
                            except Exception:
                                pass
                            try:
                                if os.path.exists(path):
                                    os.remove(path)
                            except Exception:
                                pass
                ffmpeg_warnings = list(dict.fromkeys(
                    line for line in result.stderr.decode(errors="replace").splitlines()
                    if any(kw in line for kw in ("drawtext", "error", "warning", "invalid", "unable"))
                    and "Stray %%" not in line  # %% -> % is expected/harmless, suppress per-frame noise
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
        """
        Return True only when a BIG financial figure is the primary point of the line.
        Avoids 'number' zoom style on narrative lines that merely mention a year or ID.
        Triggers on: ₹ amounts, lakh/crore, percentages, or a standalone 5+ digit number.
        """
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

    # ------------------------------------------------------------------
    # Debug / verification helpers
    # ------------------------------------------------------------------
    def simulate_drawtext_output(self, text: str) -> dict:
        """
        Simulate what will be written to drawtext (FIFO or inline) and what
        FFmpeg will visually render. This helps verify that the visible
        text after drawtext will match the original input.

        Returns a dict with keys:
            - preserve_block: bool (True when newlines are preserved as a block)
            - normalized_input: str (CRLF normalized)
            - wrapped_lines: List[str] (how the text would be wrapped)
            - simulated_pending_writes: List[str] (what writers will write to FIFOs)
            - simulated_visible: str (what FFmpeg should render visually)
            - matches_input: bool (True when simulated_visible == normalized_input)
        """
        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        if '\n' in normalized:
            # Whole block preserved in one FIFO/textfile
            preserve_block = True
            wrapped_lines = [normalized]
        else:
            preserve_block = False
            wrapped_lines = textwrap.wrap(text, width=24) or [text]

        simulated_pending = []
        if preserve_block:
            # Writer doubles percent signs; simulate write content (what gets written)
            write_content = wrapped_lines[0].replace('%', '%%')
            simulated_pending.append(write_content)
            # FFmpeg will render a single '%' for each doubled '%%'
            simulated_visible = write_content.replace('%%', '%')
        else:
            for ln in wrapped_lines:
                write_content = ln.replace('%', '%%')
                simulated_pending.append(write_content)
            # Visible text will be the wrapped pieces joined with newlines
            simulated_visible = '\n'.join(p.replace('%%', '%') for p in simulated_pending)

        matches = (simulated_visible == normalized)
        return {
            'preserve_block': preserve_block,
            'normalized_input': normalized,
            'wrapped_lines': wrapped_lines,
            'simulated_pending_writes': simulated_pending,
            'simulated_visible': simulated_visible,
            'matches_input': matches,
        }

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
