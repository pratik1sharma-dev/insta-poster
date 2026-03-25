import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import time
import requests
import base64
import io
import textwrap
import asyncio
import json

from src.models import ContentStrategy, ChannelConfig, GeneratedContent
from src.agents.content_generator import ContentGenerator
from src.config import settings
from PIL import Image

logger = logging.getLogger(__name__)

class CinematicReelGenerator:
    """
    Autonomous Virality Engine.
    The AI decides the best viral format for the topic, then executes the story.
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
        """Autonomous Pipeline: AI Plans Strategy -> AI Executes Story."""
        logger.info("Starting Autonomous Virality Engine for topic: %s", strategy.topic)

        # 1. PHASE 1: Viral Strategy Session
        # The AI decides the best way to make this specific topic go viral.
        viral_strategy = self._plan_viral_strategy(strategy, channel_config)
        
        logger.info("AI Decided Strategy | Format: %s | Aesthetic: %s | Trigger: %s", 
                    viral_strategy['format_description'][:30], viral_strategy['aesthetic_vibe'], viral_strategy['emotional_trigger'])

        # 2. PHASE 2: Execute Story based on Strategy
        lines, prompts = self._generate_script_and_prompts(
            strategy, channel_config, num_images, viral_strategy
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

        # 5. Build Clips with Text Overlays
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)

        slide_duration = getattr(settings, "cinematic_slide_duration", 4.0)
        transition_dur = getattr(settings, "cinematic_transition_duration", 0.6)

        clip_paths = self._build_cinematic_clips(
            image_paths, lines, video_dir, slide_duration, transition_dur, audio_paths
        )

        # 6. Blend and Mix
        blended = self._blend_clips(clip_paths, video_dir, transition_dur)
        music_volume = getattr(settings, "cinematic_music_volume", 0.08 if with_voice else 0.15)
        self._mix_music(blended, output_path, music_volume)

        logger.info("Autonomous Reel complete: %s", output_path)
        return output_path

    def _plan_viral_strategy(self, strategy: ContentStrategy, channel_config: ChannelConfig) -> Dict:
        """The AI chooses the best viral format and aesthetic for the topic."""
        
        prompt = f"""### THE TOPIC: {strategy.topic}
### AUDIENCE INSIGHT: {strategy.target_audience_insight}
### CORE LESSON: {strategy.angle}

### YOUR TASK:
As a Master Creative Director for Instagram, define the most viral 'Narrative Structure' for this specific topic in India.

Do NOT just pick from a list. AUTONOMOUSLY identify:
1. **The Format:** What is the best way to present this? (e.g., A simple silent story, a confrontational POV, a vulnerable realization, a day-in-the-life, a 'What they don't tell you' reveal, etc.)
2. **The Aesthetic:** What visual vibe will match the story? (e.g., Lo-fi, High-end Cinematic, Raw Phone, Noir, Candid, etc.)
3. **The Emotional Arc:** How should the viewer's feeling change from slide 1 to {num_images}?

### REQUIREMENTS:
- Must be deeply relatable to the Indian middle class/youth.
- Must focus on RECOGNITION (Bhai, this is me) or a HIGH-VALUE INSIGHT (I needed to hear this today).
- **CRITICAL:** The 'Aha!' moment must be the most valuable lesson from the topic. 
- Avoid 'clickbait' or 'fake drama'. The value should come from the actual truth of the topic, whether it is a surprising revelation or a deeply relatable simple fact.
- Must be simple enough for a 10th pass student but sharp enough for a smart professional.

### OUTPUT FORMAT (JSON ONLY):
{{
  "format_description": "Detailed description of the chosen viral format",
  "aesthetic_vibe": "The visual style and mood",
  "emotional_trigger": "The core emotion (e.g. Relief, Guilt, Clarity, Surprise)",
  "language_style": "e.g. Conversational Hinglish, Direct English, etc.",
  "narrative_strategy": "The step-by-step logic of how you will reveal the story"
}}
"""
        response = self.generator._generate_text(prompt)
        try:
            return self.generator._parse_json_response(response)
        except:
            return {
                "format": "The 3 AM Realization",
                "aesthetic": "Raw iPhone Footage",
                "trigger": "Recognition",
                "language_style": "Sharp Hinglish",
                "reasoning": "Fallback strategy"
            }

    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
        viral_strategy: Dict
    ) -> Tuple[List[str], List[str]]:
        """Executes the story based on the AI-planned strategy."""
        
        system_prompt = (
            f"You are executing a viral strategy for '{channel_config.name}'.\n"
            f"STRATEGY: {viral_strategy['format_description']}\n"
            f"AESTHETIC: {viral_strategy['aesthetic_vibe']}\n"
            f"LANGUAGE: {viral_strategy['language_style']}\n\n"
            "Goal: Create high-retention 'Recognition' for an Indian audience. "
            "Use 'Pattern Interrupts' to keep them watching. Make them feel 'seen' or 'attacked'."
        )

        prompt = f"""### THE BRIEF:
Topic: {strategy.topic}
Lesson: {strategy.angle}
Emotional Trigger: {viral_strategy['emotional_trigger']}
Narrative Arc: {viral_strategy['narrative_strategy']}

### TASK:
Create a {num_images}-image story based on the strategy above.

### RULES:
1. **Language:** Use {viral_strategy['language_style']}. Keep it 'smart-simple' (no teaching, just sharing).
2. **The Story:** Follow the '{viral_strategy['narrative_strategy']}' logic strictly.
3. **The Visuals:** All prompts must follow the '{viral_strategy['aesthetic_vibe']}' style. 
   Use ONE consistent Indian character across all images. Forbid AI perfection.

### OUTPUT FORMAT (JSON):
{{
  "lines": ["Line 1", "Line 2", ...],
  "image_prompts": ["Prompt 1", "Prompt 2", ...]
}}
"""
        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        data = self.generator._parse_json_response(response)
        
        # Log the Storyline
        logger.info("=" * 60)
        logger.info("GENERATED AUTONOMOUS STORY:")
        for i, l in enumerate(data.get("lines", []), 1):
            logger.info(f"{i}. {l}")
        logger.info("=" * 60)

        return data.get("lines", []), data.get("image_prompts", [])

    # ... [REST OF THE METHODS REMAIN THE SAME: _generate_cinematic_images, _build_cinematic_clips, etc.]
    # (Keeping existing optimized SD generation and FFmpeg logic)

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
                if path: image_paths.append(path)
            except Exception as e:
                logger.error("Failed to generate image %d: %s", i, e)
                if image_paths: image_paths.append(image_paths[-1])
        return image_paths

    def _generate_replicate_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        import replicate
        model = getattr(settings, "replicate_model", "ideogram-ai/ideogram-v2")
        output = replicate.run(model, input={"prompt": prompt, "aspect_ratio": "9:16", "style": "cinematic"})
        url = output[0] if isinstance(output, list) else str(output)
        res = requests.get(url, timeout=60)
        if res.status_code == 200:
            p = output_dir / f"image_{index:02d}.png"
            with open(p, "wb") as f: f.write(res.content)
            return p
        return None

    def _generate_sd_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        gen_w, gen_h = 768, 1344
        target_w, target_h = 1080, 1920
        payload = {"prompt": prompt, "negative_prompt": settings.sd_negative_prompt, "steps": settings.sd_steps, "width": gen_w, "height": gen_h}
        response = requests.post(settings.sd_api_url, json=payload, timeout=settings.sd_timeout)
        response.raise_for_status()
        image_data = base64.b64decode(response.json()['images'][0])
        p = output_dir / f"image_{index:02d}.png"
        img = Image.open(io.BytesIO(image_data))
        if img.size != (target_w, target_h): img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        img.save(p, "PNG")
        return p

    def _generate_gemini_image(self, prompt: str, index: int, output_dir: Path) -> Optional[Path]:
        from google import genai as genai_client
        from google.genai import types
        client = genai_client.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(model=settings.gemini_image_model, contents=prompt, config=types.GenerateContentConfig(response_modalities=["IMAGE"]))
        image_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data: image_bytes = part.inline_data.data; break
        if not image_bytes: return None
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size; target_ratio = 9/16; current_ratio = w/h
        if current_ratio > target_ratio:
            new_w = h * target_ratio; left = (w - new_w) / 2; img = img.crop((left, 0, left + new_w, h))
        elif current_ratio < target_ratio:
            new_h = w / target_ratio; top = (h - new_h) / 2; img = img.crop((0, top, w, top + new_h))
        p = output_dir / f"image_{index:02d}.png"; img.save(p, "PNG"); return p

    def _generate_voice(self, lines: List[str], output_dir: Path, channel_config: ChannelConfig) -> List[Path]:
        provider = getattr(settings, "tts_provider", "edge").lower()
        if provider == "edge": return self._tts_edge(lines, output_dir, channel_config)
        return self._tts_gtts(lines, output_dir)

    def _tts_edge(self, lines: List[str], output_dir: Path, channel_config: ChannelConfig) -> List[Path]:
        import edge_tts
        voice = getattr(channel_config, "voice_id", None) or getattr(settings, "edge_tts_voice", "en-IN-PrabhatNeural")
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
            p = output_dir / f"audio_{i:02d}.mp3"; gTTS(text=text, lang="en", tld="co.in").save(str(p)); paths.append(p)
        return paths

    def _build_cinematic_clips(self, image_paths: List[Path], lines: List[str], output_dir: Path, duration: float, transition_dur: float, audio_paths: Optional[List[Path]] = None) -> List[Path]:
        clip_paths = []
        for i, (img, text) in enumerate(zip(image_paths, lines), 1):
            is_last = (i == len(image_paths)); clip_path = output_dir / f"clip_{i:02d}.mp4"
            if audio_paths and i <= len(audio_paths):
                audio_dur = self._get_duration(audio_paths[i-1]); slide_dur = audio_dur + 0.3
            else:
                word_count = len(text.split()); slide_dur = max(3.0, (word_count / 3.5) + 1.5)
            clip_dur = slide_dur + (0 if is_last else transition_dur)
            wrapped_text = "\n".join(textwrap.wrap(text, width=28))
            escaped_text = wrapped_text.replace('\\', '\\\\').replace("'", "'\\''").replace(':', '\\:')
            if audio_paths and i <= len(audio_paths):
                filter_complex = f"[0:v]scale={self.REEL_W}:{self.REEL_H},drawtext=text='{escaped_text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.5:boxborderw=40:line_spacing=15:fix_bounds=1,format=yuv420p[v];[1:a]volume=1.0[a]"
                cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(self.FPS), "-t", str(clip_dur), "-i", str(img), "-i", str(audio_paths[i-1]), "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-shortest", str(clip_path)]
            else:
                filter_complex = f"scale={self.REEL_W}:{self.REEL_H},drawtext=text='{escaped_text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.5:boxborderw=40:line_spacing=15:fix_bounds=1"
                cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(self.FPS), "-t", str(clip_dur), "-i", str(img), "-vf", filter_complex, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p", str(clip_path)]
            subprocess.run(cmd, capture_output=True, check=True); clip_paths.append(clip_path)
        return clip_paths

    def _get_duration(self, path: Path) -> float:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try: return float(r.stdout.strip())
        except: return 5.0

    def _blend_clips(self, clip_paths: List[Path], output_dir: Path, transition_dur: float) -> Path:
        if len(clip_paths) == 1: return clip_paths[0]
        current = clip_paths[0]
        for i in range(1, len(clip_paths)):
            blended = output_dir / f"blend_{i:02d}.mp4"; dur = self._get_duration(current); offset = max(0.0, dur - transition_dur)
            cmd = ["ffmpeg", "-y", "-i", str(current), "-i", str(clip_paths[i]), "-filter_complex", f"[0:v][1:v]xfade=transition=fade:duration={transition_dur}:offset={offset:.3f},format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", str(blended)]
            subprocess.run(cmd, capture_output=True, check=True); current = blended
        return current

    def _mix_music(self, video_path: Path, output_path: Path, volume: float) -> None:
        music = Path("assets/music/background.mp3")
        if not music.exists(): shutil.copy(video_path, output_path); return
        cmd_no_v_audio = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(music), "-filter_complex", f"[1:a]volume={volume}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output_path)]
        subprocess.run(cmd_no_v_audio, capture_output=True, text=True)

    def cleanup(self):
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
