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

        # 1. Generate Script and Prompts
        lines, prompts = self._generate_script_and_prompts(
            strategy, channel_config, num_images
        )

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
    # Story Validation
    # ------------------------------------------------------------------

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

        Caption lines: 8-14 words, clear narrative progression.
        Image prompts: cinematic, story-driven, 9:16, no text.
        """
        system_prompt = (
            f"You are a Story Architect for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Brand Mission: {channel_config.brand_mission}\n"
            f"Target Audience: {channel_config.target_audience}\n"
            f"Cultural Context: {channel_config.cultural_context}\n\n"
            "Your goal: Tell a clear, coherent story in {num_images} lines that the audience can follow and learn from.\n"
            "Priority: STORY COHERENCE over shock value. Each line must logically connect to the next.\n"
            "Use concrete examples and specific situations the audience recognizes."
        )

        prompt = f"""### TOPIC: {strategy.topic}
### CORE ANGLE: {strategy.angle}
### TARGET AUDIENCE: {channel_config.target_audience}
### AUDIENCE INSIGHT: {strategy.target_audience_insight}
{f'### VERIFIED DATA (USE THESE FACTS): {strategy.verified_data}' if strategy.verified_data else ''}

### YOUR TASK:
Create a {num_images}-line story that teaches the audience something valuable about {strategy.topic}.

The story must be:
1. **Easy to Follow** - Each line builds logically on the previous one
2. **Relevant** - Addresses a real situation the audience faces
3. **Concrete** - Uses specific examples, not abstract concepts
4. **Coherent** - The {num_images} lines together deliver ONE clear insight

### STORY STRUCTURE:

**Line 1 - THE SETUP:**
Introduce the situation in concrete terms. Use a specific example or number.
Example: "Your parents saved ₹50 lakh in FDs over 30 years"
NOT: "Safety is an illusion we cling to"

**Line 2 - THE CONTEXT:**
Build understanding. Show why this matters or what people believe.
Example: "It grew to ₹1.2 crore. They felt safe."
NOT: "The mirror shows what others want to see"

**Line 3 - THE INSIGHT:**
Reveal the key learning or comparison. This is the "aha" moment.
Example: "The same amount in Nifty 50? ₹8.7 crore."
NOT: "Behind every mask is another mask"

**Line 4 - THE TAKEAWAY:**
Complete the thought. What does this mean for them?
Example: "Playing it safe cost them ₹7.5 crore."
NOT: "Authenticity is the final illusion"

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

        try:
            data    = self.generator._parse_json_response(response)
            lines   = data.get("lines", [])
            prompts = data.get("image_prompts", [])
            visual_anchor = data.get("visual_anchor", "hands")
            story_spine = data.get("story_spine", strategy.topic)

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
            
            # Log the final Storyline
            logger.info("=" * 60)
            logger.info("GENERATED CINEMATIC STORY:")
            logger.info(f"STORY SPINE: {story_spine}")
            logger.info(f"VISUAL ANCHOR: {visual_anchor}")
            logger.info("-" * 60)
            for i, (l, p) in enumerate(zip(trimmed_lines, clean_prompts), 1):
                logger.info(f"{i}. CAPTION: {l}")
                logger.info(f"   IMAGE: {p[:120]}...")
                logger.info("")
            logger.info("=" * 60)

            # Validate story coherence
            self._validate_story_coherence(trimmed_lines, story_spine)

            return trimmed_lines, clean_prompts

        except Exception as e:
            logger.error("Script generation failed: %s", e)
            logger.error("Using fallback story structure")

            # Fallback: Create a simple coherent story
            topic_short = strategy.topic[:50]
            fallback_lines = [
                f"Let's talk about {topic_short}",
                "Here's what most people don't know",
                "This changes everything",
                "Think about that"
            ][:num_images]

            # Ensure we have exactly num_images lines
            while len(fallback_lines) < num_images:
                fallback_lines.append(topic_short)

            fallback_prompts = [
                f"Close-up of hands holding {topic_short.split()[0] if topic_short.split() else 'book'}, "
                "warm natural lighting, contemplative mood, 35mm film grain, 9:16 portrait, NO text"
            ] * num_images

            return fallback_lines, fallback_prompts
