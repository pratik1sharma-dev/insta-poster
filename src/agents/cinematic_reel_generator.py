"""
Cinematic Reel Generator

Pipeline:
  1. AI plans viral format and emotional arc
  2. AI generates story lines (captions only)
  3. AI generates SD-optimized image prompts (separate call — knows SD constraints)
  4. Images generated — raises on any failure, no silent fallback
  5. Clips built with styled text overlay
  6. Cross-fade blend + background music

Key design decisions:
- Story generation and image prompt generation are SEPARATE AI calls.
  The story LLM focuses on narrative; the prompt LLM knows SD constraints.
- No fallback anywhere. Failures raise immediately with a clear message.
- SD prompts avoid "hands" and other subjects SD consistently destroys.
"""

import asyncio
import base64
import io
import logging
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image

from src.agents.content_generator import ContentGenerator
from src.config import settings
from src.models import ChannelConfig, ContentStrategy, GeneratedContent

logger = logging.getLogger(__name__)


# Subjects that SD models consistently fail to render correctly.
# A prompt dominated by these triggers bad anatomy and artifacts.
_SD_DANGER_SUBJECTS = frozenset({
    "hands", "hand", "fingers", "finger", "palms", "palm",
    "fist", "knuckles", "wrist",
})


class CinematicReelGenerator:
    """AI-driven cinematic reel generator for Instagram."""

    REEL_W = 1080
    REEL_H = 1920
    FPS    = 25

    def __init__(self):
        self.generator = ContentGenerator()
        self.temp_dir  = Path("temp_cinematic")
        self.temp_dir.mkdir(exist_ok=True)
        self.provider  = settings.image_provider.lower()

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
        with_voice: bool = False,
    ) -> Path:
        """Full pipeline. Raises on any failure — no silent fallback."""
        logger.info("Starting Cinematic Reel: %s (voice=%s)", strategy.topic, with_voice)

        # Phase 1: AI decides viral format and emotional arc
        viral_strategy = self._plan_viral_strategy(strategy, channel_config, num_images)
        logger.info(
            "Strategy | Format: %s | Aesthetic: %s | Trigger: %s",
            viral_strategy["format_description"][:50],
            viral_strategy["aesthetic_vibe"],
            viral_strategy["emotional_trigger"],
        )

        # Phase 2: Generate story captions
        lines = self._generate_story_lines(strategy, channel_config, num_images, viral_strategy)
        logger.info("=" * 60)
        logger.info("STORY LINES:")
        for i, line in enumerate(lines, 1):
            logger.info("%d. %s", i, line)
        logger.info("=" * 60)

        # Phase 3: Generate SD-optimized image prompts (separate AI call)
        prompts = self._generate_sd_prompts(lines, strategy, viral_strategy, num_images)
        logger.info("SD IMAGE PROMPTS:")
        for i, p in enumerate(prompts, 1):
            logger.info("%d. %s", i, p[:120])

        # Phase 4: Generate images — raises on failure
        image_dir = self.temp_dir / "images"
        image_dir.mkdir(exist_ok=True)
        image_paths = self._generate_cinematic_images(prompts, image_dir)

        if len(image_paths) != num_images:
            raise RuntimeError(
                f"Image generation incomplete: expected {num_images}, got {len(image_paths)}"
            )

        # Phase 5: Voice narration (optional)
        audio_paths = None
        if with_voice:
            audio_dir = self.temp_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_paths = self._generate_voice(lines, audio_dir, channel_config)

        # Phase 6: Build clips with text overlay
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)
        slide_duration = getattr(settings, "cinematic_slide_duration", 4.0)
        transition_dur = getattr(settings, "cinematic_transition_duration", 0.6)

        clip_paths = self._build_cinematic_clips(
            image_paths, lines, video_dir, slide_duration, transition_dur, audio_paths
        )

        # Phase 7: Blend + music
        blended = self._blend_clips(clip_paths, video_dir, transition_dur)
        music_volume = getattr(settings, "cinematic_music_volume", 0.08 if with_voice else 0.15)
        self._mix_music(blended, output_path, music_volume)

        logger.info("Cinematic Reel complete: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Phase 1: Viral strategy planning
    # ------------------------------------------------------------------

    def _plan_viral_strategy(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> Dict:
        """AI chooses the best viral format and aesthetic for the topic."""
        prompt = f"""### TOPIC: {strategy.topic}
### AUDIENCE INSIGHT: {strategy.target_audience_insight}
### CORE LESSON: {strategy.angle}
### NUMBER OF SLIDES: {num_images}

### YOUR TASK:
As a Master Creative Director for Indian Instagram, define the most viral narrative structure for this specific topic.

Autonomously identify:
1. **Format:** Best presentation style (e.g. Silent story, Confrontational POV, Vulnerable realization,
   Day-in-the-life, 'What they don't tell you' reveal, Before/After contrast)
2. **Aesthetic:** Visual vibe matching the story (e.g. Lo-fi, High-end Cinematic, Raw phone footage, Candid)
3. **Emotional Arc:** How the viewer's feeling should evolve from slide 1 to slide {num_images}

### REQUIREMENTS:
- Deeply relatable to Indian middle class/youth
- Focus on RECOGNITION ("bhai, this is me") or HIGH-VALUE INSIGHT ("I needed this today")
- The 'Aha!' moment must deliver the most valuable lesson from the topic
- No clickbait or fake drama — value must come from the truth of the topic

### OUTPUT (JSON only):
{{
  "format_description": "Detailed description of the chosen viral format",
  "aesthetic_vibe": "The visual style and mood",
  "emotional_trigger": "The core emotion (e.g. Relief, Guilt, Clarity, Surprise)",
  "language_style": "e.g. Conversational Hinglish, Direct English",
  "narrative_strategy": "Step-by-step logic of how the story unfolds across {num_images} slides"
}}"""

        response = self.generator._generate_text(prompt)
        result = self.generator._parse_json_response(response)

        if not result.get("format_description"):
            raise RuntimeError(
                f"Viral strategy planning failed — empty or invalid response.\n"
                f"LLM output: {response[:300]}"
            )
        return result

    # ------------------------------------------------------------------
    # Phase 2: Story caption generation
    # ------------------------------------------------------------------

    def _generate_story_lines(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
        viral_strategy: Dict,
    ) -> List[str]:
        """Generate the on-screen caption for each slide."""
        system_prompt = (
            f"You are the story writer for '{channel_config.name}'.\n"
            f"FORMAT: {viral_strategy['format_description']}\n"
            f"AESTHETIC: {viral_strategy['aesthetic_vibe']}\n"
            f"LANGUAGE: {viral_strategy['language_style']}\n\n"
            "Goal: Write captions that make an Indian viewer feel 'seen' or deliver a sharp insight.\n"
            "Each caption must be 8–14 words: concrete, conversational, no philosophical fluff."
        )

        prompt = f"""### TOPIC: {strategy.topic}
### LESSON: {strategy.angle}
### EMOTIONAL TRIGGER: {viral_strategy['emotional_trigger']}
### NARRATIVE ARC: {viral_strategy['narrative_strategy']}

Write exactly {num_images} caption lines for a cinematic Instagram Reel.

RULES:
1. 8–14 words per line — count before submitting
2. Each line must logically build on the previous one
3. Line 1: hook immediately — curiosity or instant recognition
4. Last line: deliver the core insight or a sharp call to action
5. Use {viral_strategy['language_style']}
6. NO abstract philosophy ("success hides behind failure", "journey is the destination")
7. NO unverified numbers — use only figures from the verified research data

GOOD EXAMPLES:
- "₹5,000 SIP at 25 becomes ₹2.3 crore. At 35? Only ₹67 lakh."
- "You've paid 1.2% annually to a fund that underperforms its index."
- "Your friend switched jobs 3 times. You stayed loyal. Check both salaries."

Return JSON:
{{"lines": ["line 1", "line 2", ...]}}

Exactly {num_images} lines. JSON only."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        data = self.generator._parse_json_response(response)
        lines = data.get("lines", [])

        if len(lines) != num_images:
            raise RuntimeError(
                f"Story generation failed: expected {num_images} lines, got {len(lines)}.\n"
                f"LLM response: {response[:400]}"
            )
        return [str(l) for l in lines]

    # ------------------------------------------------------------------
    # Phase 3: SD-optimized image prompt generation
    # ------------------------------------------------------------------

    def _generate_sd_prompts(
        self,
        lines: List[str],
        strategy: ContentStrategy,
        viral_strategy: Dict,
        num_images: int,
    ) -> List[str]:
        """
        Dedicated AI call to generate Stable Diffusion-optimized image prompts.

        This is intentionally separate from story generation. The story LLM
        focuses on narrative. This call specifically knows SD's constraints:
        what renders well, what triggers artifacts, and how to write prompts
        that produce cinematic 9:16 portrait images.
        """
        lines_text = "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))

        system_prompt = """You are an expert Stable Diffusion prompt engineer specializing in cinematic 9:16 portrait reels.
You know exactly what SD renders well versus what triggers artifacts.

═══ SD RENDERS WELL — ALWAYS USE ═══
Environments:
  - Modern Indian office, open-plan workspace, home study, coffee shop, bedroom desk
  - City street, metro station, park bench, apartment balcony at dusk
Objects in context:
  - Smartphone lying on wooden desk showing an app
  - Laptop with a glowing screen in a dim room
  - A document, notebook, or planner on a table
  - A wallet, coins, a piggy bank, a tea cup
Single person in environment:
  - Young Indian man/woman seen from mid-body up, clearly in a setting
  - Face and expression visible — not just isolated body parts
Abstract / atmospheric:
  - Light rays through a window, bokeh blur, soft shadows
  - Silhouette of a person against a bright window
  - Textured backgrounds: concrete, wood grain, fabric

═══ SD RENDERS POORLY — NEVER USE ═══
- HANDS as the main close-up subject → always fused fingers, extra limbs
- Multiple people interacting at close range → anatomy breaks down
- Text, numbers, graphs, or financial charts IN the scene → always garbled
- "Analyzing data" without a specific physical object anchor
- Complex multi-element scenes with many moving parts

═══ SHOT VARIETY (vary across images) ═══
- Extreme close-up: face detail, single object macro
- Close-up: face + shoulders, object on surface
- Medium shot: person from waist up in their environment
- Wide shot: full environment, person small in frame

═══ LIGHTING ═══
- Warm golden hour (sunrise/sunset light through window)
- Soft natural daylight (overcast, diffused, even)
- Warm desk/lamp light (evening, cozy interior)
- Dramatic side light (moody, high contrast, one-sided)
- Blue hour (cool evening tones, city background)"""

        prompt = f"""Create {num_images} Stable Diffusion image prompts for this Instagram Reel.

TOPIC: {strategy.topic}
AESTHETIC: {viral_strategy['aesthetic_vibe']}

STORY CAPTIONS (each image must visually support its caption):
{lines_text}

REQUIREMENTS FOR EACH PROMPT:
1. Choose a SPECIFIC concrete subject — not "person thinking about money" but
   "young Indian woman in navy kurta sitting at a wooden study desk, looking at laptop"
2. NEVER use hands as the main close-up subject
3. Include ALL of: [shot type] + [specific subject + what they're doing] + [specific environment] + [lighting] + [mood]
4. Vary shot types across the {num_images} images (don't use the same shot type twice if possible)
5. Visual continuity: use ONE recurring element across all images
   (same person, same location, OR same key object — pick one and stick to it)
6. End EVERY prompt with exactly:
   "35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

GOOD PROMPT EXAMPLES:
"Medium shot of young Indian man in grey t-shirt at wooden desk with open laptop, \
warm desk lamp casting soft shadows, contemplative expression, shallow depth of field, \
35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

"Extreme close-up of smartphone screen on wooden surface showing investment app with \
green upward chart, warm side light, shallow depth of field, 35mm film grain, \
9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

"Wide shot of young Indian woman walking through a modern glass office building lobby, \
blue hour light from large windows, slight motion blur, 35mm film grain, \
9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

BAD PROMPTS (DO NOT USE THESE PATTERNS):
❌ "Close-up of hands analyzing financial data"
❌ "Person thinking about money"
❌ "Financial documents with hands pointing at numbers"
❌ "Man holding papers with financial information"

Return JSON:
{{"prompts": ["full prompt 1", "full prompt 2", ...]}}

Exactly {num_images} prompts. JSON only."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        data = self.generator._parse_json_response(response)
        prompts = data.get("prompts", [])

        if len(prompts) != num_images:
            raise RuntimeError(
                f"SD prompt generation failed: expected {num_images}, got {len(prompts)}.\n"
                f"LLM response: {response[:400]}"
            )

        # Warn if any prompt contains SD-dangerous subjects
        for i, p in enumerate(prompts, 1):
            words = set(p.lower().split())
            dangers = _SD_DANGER_SUBJECTS & words
            if dangers:
                logger.warning(
                    "[SD Prompt %d] Contains difficult subjects for SD: %s", i, dangers
                )

        return prompts

    # ------------------------------------------------------------------
    # Phase 4: Image generation — no silent fallback
    # ------------------------------------------------------------------

    def _generate_cinematic_images(self, prompts: List[str], output_dir: Path) -> List[Path]:
        """Generate all images. Raises immediately on any failure."""
        image_paths = []
        for i, prompt in enumerate(prompts, 1):
            logger.info("[Image %d/%d] Provider: %s", i, len(prompts), self.provider)
            logger.info("[Image %d/%d] Prompt: %s", i, len(prompts), prompt[:130])

            if self.provider == "sd":
                path = self._generate_sd_image(prompt, i, output_dir)
            elif self.provider == "replicate":
                path = self._generate_replicate_image(prompt, i, output_dir)
            elif self.provider == "gemini":
                path = self._generate_gemini_image(prompt, i, output_dir)
            else:
                raise ValueError(f"Unknown image provider: {self.provider}")

            if not path or not path.exists():
                raise RuntimeError(
                    f"Image {i} generation returned no file. Provider: {self.provider}"
                )
            image_paths.append(path)

        return image_paths

    def _generate_sd_image(self, prompt: str, index: int, output_dir: Path) -> Path:
        gen_w, gen_h     = 768, 1344
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
        logger.info("[Image %d] SD: %dx%d → upscale to %dx%d", index, gen_w, gen_h, target_w, target_h)
        response = requests.post(settings.sd_api_url, json=payload, timeout=settings.sd_timeout)
        response.raise_for_status()
        image_data = base64.b64decode(response.json()["images"][0])
        img = Image.open(io.BytesIO(image_data))
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        p = output_dir / f"image_{index:02d}.png"
        img.save(p, "PNG")
        return p

    def _generate_replicate_image(self, prompt: str, index: int, output_dir: Path) -> Path:
        import replicate
        model = getattr(settings, "replicate_model", "ideogram-ai/ideogram-v2")
        output = replicate.run(model, input={"prompt": prompt, "aspect_ratio": "9:16", "style": "cinematic"})
        url = output[0] if isinstance(output, list) else str(output)
        res = requests.get(url, timeout=60)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to download Replicate image {index}: HTTP {res.status_code}")
        p = output_dir / f"image_{index:02d}.png"
        p.write_bytes(res.content)
        return p

    def _generate_gemini_image(self, prompt: str, index: int, output_dir: Path) -> Path:
        from google import genai as genai_client
        from google.genai import types
        client = genai_client.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_image_model,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        image_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                break
        if not image_bytes:
            raise RuntimeError(f"Gemini returned no image for prompt {index}")
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        target_ratio = 9 / 16
        if (w / h) > target_ratio:
            new_w = int(h * target_ratio)
            img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
        elif (w / h) < target_ratio:
            new_h = int(w / target_ratio)
            img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
        p = output_dir / f"image_{index:02d}.png"
        img.save(p, "PNG")
        return p

    # ------------------------------------------------------------------
    # Voice synthesis
    # ------------------------------------------------------------------

    def _generate_voice(
        self, lines: List[str], output_dir: Path, channel_config: ChannelConfig
    ) -> List[Path]:
        provider = getattr(settings, "tts_provider", "edge").lower()
        if provider == "edge":
            return self._tts_edge(lines, output_dir, channel_config)
        return self._tts_gtts(lines, output_dir)

    def _tts_edge(
        self, lines: List[str], output_dir: Path, channel_config: ChannelConfig
    ) -> List[Path]:
        import edge_tts
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

        asyncio.run(_gen())
        return paths

    def _tts_gtts(self, lines: List[str], output_dir: Path) -> List[Path]:
        from gtts import gTTS
        paths = []
        for i, text in enumerate(lines, 1):
            p = output_dir / f"audio_{i:02d}.mp3"
            gTTS(text=text, lang="en", tld="co.in").save(str(p))
            paths.append(p)
        return paths

    # ------------------------------------------------------------------
    # Clip building
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
        clip_paths = []
        n = len(image_paths)

        for i, (img, text) in enumerate(zip(image_paths, lines), 1):
            is_last   = (i == n)
            clip_path = output_dir / f"clip_{i:02d}.mp4"

            if audio_paths and i <= len(audio_paths):
                slide_dur = self._get_duration(audio_paths[i - 1]) + 0.3
            else:
                word_count = len(text.split())
                slide_dur  = max(3.5, (word_count / 3.0) + 1.5)

            clip_dur = slide_dur + (0 if is_last else transition_dur)

            drawtext_filter = self._build_drawtext(text)

            if audio_paths and i <= len(audio_paths):
                filter_complex = (
                    f"[0:v]scale={self.REEL_W}:{self.REEL_H},"
                    f"{drawtext_filter},format=yuv420p[v];"
                    f"[1:a]volume=1.0[a]"
                )
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(self.FPS),
                    "-t", str(clip_dur), "-i", str(img),
                    "-i", str(audio_paths[i - 1]),
                    "-filter_complex", filter_complex,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(clip_path),
                ]
            else:
                filter_complex = (
                    f"scale={self.REEL_W}:{self.REEL_H},{drawtext_filter}"
                )
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(self.FPS),
                    "-t", str(clip_dur), "-i", str(img),
                    "-vf", filter_complex,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p", str(clip_path),
                ]

            logger.info(
                "[Clip %d/%d] %.1fs | %d words | %s",
                i, n, clip_dur, len(text.split()), img.name,
            )
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"FFmpeg clip {i} failed:\n{r.stderr[-500:]}")
            clip_paths.append(clip_path)

        return clip_paths

    def _build_drawtext(self, text: str) -> str:
        """
        Build an FFmpeg drawtext filter string for a caption line.

        Improvements over original:
        - Dynamic font size: fewer words → bigger font
        - Text positioned in lower third (y=h*0.62) not dead center
        - Drop shadow for depth
        - Slightly reduced box opacity for cleaner look
        """
        wrapped = "\n".join(textwrap.wrap(text, width=30))
        escaped = (
            wrapped
            .replace("\\", "\\\\")
            .replace("'",  "\\'")
            .replace(":",  "\\:")
            .replace("%",  "\\%")
        )

        word_count = len(text.split())
        if word_count <= 7:
            font_size = 82
        elif word_count <= 11:
            font_size = 70
        else:
            font_size = 60

        return (
            f"drawtext=text='{escaped}'"
            f":fontcolor=white"
            f":fontsize={font_size}"
            f":x=(w-text_w)/2"
            f":y=h*0.62"
            f":line_spacing=18"
            f":fix_bounds=1"
            f":shadowcolor=black@0.85"
            f":shadowx=2:shadowy=2"
            f":box=1:boxcolor=black@0.40:boxborderw=28"
        )

    # ------------------------------------------------------------------
    # Blend + music
    # ------------------------------------------------------------------

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
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                str(blended),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"FFmpeg blend {i} failed:\n{r.stderr[-400:]}")
            current = blended
        return current

    def _mix_music(self, video_path: Path, output_path: Path, volume: float) -> None:
        music = Path("assets/music/background.mp3")
        if not music.exists():
            logger.info("No background music found, skipping mix")
            shutil.copy(video_path, output_path)
            return
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
            logger.error("Music mix failed, copying without music: %s", r.stderr[-200:])
            shutil.copy(video_path, output_path)

    def cleanup(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
