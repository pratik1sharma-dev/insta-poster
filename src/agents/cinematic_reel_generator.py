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
import random

from src.models import ContentStrategy, ChannelConfig, GeneratedContent
from src.agents.content_generator import ContentGenerator
from src.config import settings
from PIL import Image

logger = logging.getLogger(__name__)

class CinematicReelGenerator:
    """
    Virality Engine - Generates high-impact, relatable Indian stories.
    Upgraded for growth: Variation buckets, Hook engineering, and Pattern interrupts.
    """
    REEL_W = 1080
    REEL_H = 1920
    FPS    = 25

    # Style Variation Buckets to prevent visual fatigue
    VISUAL_STYLES = [
        "Raw iPhone footage - shaky, handheld, authentic Indian setting",
        "Documentary / CCTV style - gritty, grainy, low-angle, real-life feel",
        "Cinematic Noir - high contrast, moody, 35mm film grain, heavy shadows",
        "Minimalist / Text-Heavy - blurred realistic background, focus on bold typography",
        "Street Photography style - vibrant, high detail, candid Indian street moments"
    ]

    # Proven Viral Hook Patterns
    HOOK_PATTERNS = [
        "Nobody tells you this about {topic}...",
        "You're not {negative_state}, you're just {real_cause}...",
        "This is exactly why you're still {struggle}...",
        "The lie we all tell ourselves about {topic}...",
        "I was {age} when I realized {topic} was a trap..."
    ]

    # Tone Buckets for variation
    TONES = [
        "Brutally Honest / Spiky",
        "Empathetic / Smart Friend",
        "Controversial / Opinionated",
        "Action-Oriented / Direct"
    ]

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
        """Full Virality Pipeline."""
        logger.info("Starting Virality Engine: %s (voice=%s)", strategy.topic, with_voice)

        # 1. Randomly select Engine parameters for this specific run
        selected_style = random.choice(self.VISUAL_STYLES)
        selected_hook  = random.choice(self.HOOK_PATTERNS)
        selected_tone  = random.choice(self.TONES)
        
        logger.info("Engine Settings | Style: %s | Hook: %s | Tone: %s", 
                    selected_style.split(" - ")[0], selected_hook[:30], selected_tone)

        # 2. Generate Script and Prompts
        lines, prompts = self._generate_script_and_prompts(
            strategy, channel_config, num_images, 
            selected_style, selected_hook, selected_tone
        )

        # 3. Generate Cinematic Images (9:16)
        image_dir = self.temp_dir / "images"
        image_dir.mkdir(exist_ok=True)
        image_paths = self._generate_cinematic_images(prompts, image_dir)

        # 4. Generate Voice (if enabled)
        audio_paths = None
        if with_voice:
            audio_dir = self.temp_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_paths = self._generate_voice(lines, audio_dir, channel_config)

        # 5. Build Clips with Text Overlays (and optional voice)
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)

        slide_duration = getattr(settings, "cinematic_slide_duration", 4.0)
        transition_dur = getattr(settings, "cinematic_transition_duration", 0.6)

        clip_paths = self._build_cinematic_clips(
            image_paths, lines, video_dir, slide_duration, transition_dur, audio_paths
        )

        # 6. Blend Clips
        blended = self._blend_clips(clip_paths, video_dir, transition_dur)

        # 7. Add Music
        music_volume = getattr(settings, "cinematic_music_volume", 0.08 if with_voice else 0.15)
        self._mix_music(blended, output_path, music_volume)

        logger.info("Virality Reel complete: %s", output_path)
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
            logger.info("[Cinematic Image %d/%d] Prompt: %s", i, len(prompts), prompt)
            
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
        # Generate at lower resolution (768x1344) for speed on Mac hardware, then upscale
        gen_w, gen_h = 768, 1344
        target_w, target_h = 1080, 1920

        payload = {
            "prompt": prompt,
            "negative_prompt": settings.sd_negative_prompt,
            "steps": settings.sd_steps,
            "width": gen_w,
            "height": gen_h,
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

            # Manual text wrapping
            wrapped_lines = textwrap.wrap(text, width=28)
            wrapped_text = "\n".join(wrapped_lines)

            # Escape text for FFmpeg
            escaped_text = wrapped_text.replace('\\', '\\\\').replace("'", "'\\''").replace(':', '\\:')

            # Build FFmpeg command
            if audio_paths and i <= len(audio_paths):
                # WITH VOICE: Image + Text + Audio
                filter_complex = (
                    f"[0:v]scale={self.REEL_W}:{self.REEL_H},"
                    f"drawtext=text='{escaped_text}':fontcolor=white:fontsize=72:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.5:boxborderw=40:"
                    f"line_spacing=15:fix_bounds=1,format=yuv420p[v];"
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
                    f"drawtext=text='{escaped_text}':fontcolor=white:fontsize=72:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.5:boxborderw=40:"
                    f"line_spacing=15:fix_bounds=1"
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
    # Script Generation (The Engine)
    # ------------------------------------------------------------------

    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
        selected_style: str,
        selected_hook: str,
        selected_tone: str
    ) -> Tuple[List[str], List[str]]:
        """
        AI Creative Brief - Generates stories based on Engine parameters.
        """
        system_prompt = (
            f"You are the Lead Creative Director for '{channel_config.name}'.\n"
            f"Persona: Simple but sharp. You sound like a smart, brutally honest friend, not a teacher.\n"
            f"Visual Style: {selected_style}\n"
            f"Core Tone: {selected_tone}\n\n"
            "Your goal is to build an Indian Virality Engine. People don't share because it's 'beautiful'. "
            "They share when they feel 'attacked' by the truth. "
            "Use 'Pattern Interrupts': surprise the reader, contradict common beliefs, and spike the tension."
        )

        prompt = f"""### THE GROWTH BRIEF:
Topic: {strategy.topic}
The Hook Pattern: {selected_hook}
The Realization: {strategy.angle}
Target Audience: {channel_config.target_audience}

### YOUR TASK:
Create a {num_images}-image cinematic story that delivers RECOGNITION.

### SCRIPT RULES (CRITICAL):
1. **Hook Engineering:** You MUST start with the pattern: "{selected_hook}".
2. **Simple but Sharp:** Use words an Indian 10th-pass student understands, but with a 'smart' edge. 
   (e.g., Use "EMI trap" instead of "Financial liability").
3. **Pattern Interrupts:** In the middle of the story, spike the tension. Contradict what they believe.
4. **No Art/Poetry:** Forbid abstract metaphors. Use: "Swiggy prices," "2-hour traffic," "80k salary," "Bank balance."
5. **Human Realization:** The final line must be a "Punch to the gut" that they can't ignore.

### IMAGE PROMPT RULES:
- **Style Variation Bucket:** {selected_style}.
- **Real Indian Scenarios:** Show tired faces, dim rooms, traffic jams, checking phones, plastic chairs.
- **Single Character Continuity:** Use one consistent Indian character (e.g., 'A tired 30yo man in a worn formal shirt') across all prompts.
- **No AI Perfection:** Forbid model-like faces. Use 'realistic skin texture', 'sweat', 'tired eyes'.

### OUTPUT FORMAT (JSON):
{{
  "story_title": "The emotional core",
  "visual_anchor": "The character used for continuity",
  "lines": [
    "Punchy Line 1 (Hook)",
    "Punchy Line 2 (The Lie/Tension)",
    "Punchy Line 3 (The Pattern Interrupt)",
    "Punchy Line 4 (The Harsh Reality)",
    "Punchy Line 5 (The Realization)"
  ],
  "image_prompts": [
    "Realistic Indian prompt for Line 1",
    "Realistic Indian prompt for Line 2",
    ...
  ]
}}

Respond with ONLY valid JSON. Exactly {num_images} lines and prompts."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        
        # Log Engine Output
        logger.info("Engine Generation complete. Tone: %s, Hook: %s", selected_tone, selected_hook)

        try:
            data    = self.generator._parse_json_response(response)
            lines   = data.get("lines", [])
            prompts = data.get("image_prompts", [])
            visual_anchor = data.get("visual_anchor", "character")

            # Validate counts
            if len(lines) != num_images or len(prompts) != num_images:
                logger.warning("Count mismatch. Padding/Trimming to %d", num_images)
                lines = (lines + [strategy.topic]*num_images)[:num_images]
                prompts = (prompts + [f"Cinematic portrait of {visual_anchor}, 9:16"]*num_images)[:num_images]

            # Append style-specific instructions to every image prompt
            clean_prompts = []
            for p in prompts:
                p = str(p)
                if "9:16" not in p:
                    p += f", {selected_style.split(' - ')[0]}, 9:16 portrait, photorealistic, NO text"
                clean_prompts.append(p)
            
            # Log the final Storyline
            logger.info("=" * 60)
            logger.info("GENERATED VIRALITY STORY:")
            for i, (l, p) in enumerate(zip(lines, clean_prompts), 1):
                logger.info(f"{i}. [{selected_tone}] {l}")
            logger.info("=" * 60)

            return lines, clean_prompts

        except Exception as e:
            logger.error("Engine failed: %s", e)
            fallback_line   = [strategy.topic[:60]] * num_images
            fallback_prompt = [f"Realistic portrait of an Indian person, 9:16, {selected_style}"] * num_images
            return fallback_line, fallback_prompt
