"""
Reel Generator Agent - Transforms carousel slides into high-impact Instagram Reels.
"""
import os
import subprocess
import logging
import json
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from gtts import gTTS
from src.models import CarouselSlide, ContentStrategy, ChannelConfig, GeneratedContent
from src.config import settings
from src.agents.content_generator import ContentGenerator

logger = logging.getLogger(__name__)

class ReelGenerator:
    """AI agent that converts carousel images and text into a narrated video Reel."""

    def __init__(self):
        """Initialize the Reel Generator."""
        self.generator = ContentGenerator()
        # Ensure we have a temporary directory for audio/video fragments
        self.temp_dir = Path("temp_reel")
        self.temp_dir.mkdir(exist_ok=True)

    def _generate_narration_script(self, slides: List[CarouselSlide], strategy: ContentStrategy, channel_config: ChannelConfig) -> List[str]:
        """Use LLM to convert punchy slide text into a natural, flowing narration script."""
        
        slides_text = "\n".join([f"Slide {s.slide_number}: {s.text_overlay}" for s in slides])
        
        system_prompt = f"""You are a Professional Voiceover Scriptwriter for '{channel_config.name}'.
Your goal is to transform static slide text into a natural, flowing, and engaging narrative script for an Instagram Reel.

### GUIDELINES:
- **Natural Speech:** Write how a person actually talks. Use transitions like "But here's the thing...", "Now look at this...", or "Think about it."
- **Pacing:** Each slide's narration should be concise (10-15 seconds max).
- **Engagement:** Keep the energy high and the tone educational yet conversational.
- **Strict Matching:** You MUST provide exactly {len(slides)} script segments, one for each slide.
"""

        prompt = f"""### CAROUSEL CONTENT:
{slides_text}

### TOPIC & ANGLE:
Topic: {strategy.topic}
Angle: {strategy.angle}

### TASK:
Write a narration script for a Reel. 
Return exactly {len(slides)} segments in a JSON array. Each segment should be the spoken text for that specific slide.

**Output Format (JSON):**
{{
  "segments": [
    "Spoken text for slide 1...",
    "Spoken text for slide 2...",
    ...
  ]
}}
"""
        response_text = self.generator._generate_text(prompt, system_prompt=system_prompt)
        try:
            data = self.generator._parse_json_response(response_text)
            segments = data.get("segments", [])
            if len(segments) != len(slides):
                logger.warning(f"Script segment count mismatch ({len(segments)} vs {len(slides)}). Falling back to slide text.")
                return [s.text_overlay for s in slides]
            return segments
        except Exception as e:
            logger.error(f"Failed to parse script: {e}")
            return [s.text_overlay for s in slides]

    def _create_audio_segments(self, script_segments: List[str], output_dir: Path) -> List[Path]:
        """Convert script segments into individual audio files using gTTS."""
        audio_paths = []
        for i, text in enumerate(script_segments, 1):
            audio_path = output_dir / f"audio_{i:02d}.mp3"
            tts = gTTS(text=text, lang='en', tld='co.in') # Using Indian English TLD for local flavor
            tts.save(str(audio_path))
            audio_paths.append(audio_path)
        return audio_paths

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get duration of audio file using ffprobe."""
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())

    def generate_reel(self, content: GeneratedContent, strategy: ContentStrategy, channel_config: ChannelConfig, image_paths: List[Path], output_path: Path) -> Path:
        """Complete pipeline to generate a Reel .mp4 file."""
        logger.info(f"Starting Reel generation for: {strategy.topic}")
        
        # 1. Generate Script
        script_segments = self._generate_narration_script(content.slides, strategy, channel_config)
        
        # 2. Create Audio
        audio_fragments_dir = self.temp_dir / "audio"
        audio_fragments_dir.mkdir(exist_ok=True)
        audio_paths = self._create_audio_segments(script_segments, audio_fragments_dir)
        
        # 3. Assemble Video Fragments using FFmpeg
        # We'll create individual clips for each slide synced to its audio
        video_fragments_dir = self.temp_dir / "video"
        video_fragments_dir.mkdir(exist_ok=True)
        clip_paths = []

        for i, (img_path, audio_path) in enumerate(zip(image_paths, audio_paths), 1):
            duration = self._get_audio_duration(audio_path)
            clip_path = video_fragments_dir / f"clip_{i:02d}.mp4"
            
            # FFmpeg command:
            # - Create vertical 1080x1920 canvas
            # - Background: Scaled/blurred version of the square image
            # - Foreground: The sharp square image centered
            # - Apply slight Ken Burns (zoom)
            
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-loop', '1', '-i', str(img_path), '-i', str(audio_path),
                '-filter_complex', 
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];" +
                f"[0:v]scale=1080:1080[fg];" +
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,zoompan=z='min(zoom+0.001,1.1)':d={int(duration * 25)}:s=1080x1920[v]",
                '-map', '[v]', '-map', '1:a', '-c:v', 'libx264', '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '192k', 
                '-pix_fmt', 'yuv420p', '-t', str(duration), str(clip_path)
            ]
            
            subprocess.run(ffmpeg_cmd, check=True)
            clip_paths.append(clip_path)

        # 4. Concatenate Clips
        concat_list_path = self.temp_dir / "clips.txt"
        with open(concat_list_path, "w") as f:
            for cp in clip_paths:
                f.write(f"file '{cp.absolute()}'\n")
        
        final_cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_list_path),
            '-c', 'copy', str(output_path)
        ]
        subprocess.run(final_cmd, check=True)
        
        logger.info(f"Reel successfully generated at: {output_path}")
        return output_path

    def cleanup(self):
        """Clean up temporary files."""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
