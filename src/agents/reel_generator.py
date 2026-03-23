"""
Reel Generator Agent - Transforms carousel slides into high-impact Instagram Reels.
"""
import os
import subprocess
import logging
import json
import re
import shutil
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
        """Convert script segments into individual audio files using the configured provider."""
        provider = settings.tts_provider.lower()
        audio_paths = []

        if provider == "edge":
            logger.info(f"Using Edge-TTS with voice: {settings.edge_tts_voice}")
            import asyncio
            import edge_tts

            async def gen_edge():
                for i, text in enumerate(script_segments, 1):
                    audio_path = output_dir / f"audio_{i:02d}.mp3"
                    communicate = edge_tts.Communicate(text, settings.edge_tts_voice)
                    await communicate.save(str(audio_path))
                    audio_paths.append(audio_path)

            asyncio.run(gen_edge())

        elif provider == "bark":
            # Keeping stub for compatibility, but recommending Edge for this server
            logger.warning("Bark is not recommended for 4GB RAM. Falling back to gTTS.")
            for i, text in enumerate(script_segments, 1):
                audio_path = output_dir / f"audio_{i:02d}.mp3"
                tts = gTTS(text=text, lang='en', tld='co.in')
                tts.save(str(audio_path))
                audio_paths.append(audio_path)
                
        else: # Default to gTTS
            for i, text in enumerate(script_segments, 1):
                audio_path = output_dir / f"audio_{i:02d}.mp3"
                tts = gTTS(text=text, lang='en', tld='co.in')
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
        """Complete pipeline to generate a Reel .mp4 file using sequential assembly for low RAM stability."""
        logger.info(f"Starting Reel generation for: {strategy.topic}")
        
        # 1. Generate Script
        script_segments = self._generate_narration_script(content.slides, strategy, channel_config)
        
        # 2. Create Audio
        audio_fragments_dir = self.temp_dir / "audio"
        audio_fragments_dir.mkdir(exist_ok=True)
        audio_paths = self._create_audio_segments(script_segments, audio_fragments_dir)
        
        # 3. Assemble Individual Video Clips
        video_fragments_dir = self.temp_dir / "video"
        video_fragments_dir.mkdir(exist_ok=True)
        clip_paths = []
        transition_duration = 0.5

        for i, (img_path, audio_path) in enumerate(zip(image_paths, audio_paths), 1):
            audio_dur = self._get_audio_duration(audio_path)
            # Add tail for transition (except last slide)
            is_last = (i == len(image_paths))
            clip_duration = audio_dur + (0 if is_last else transition_duration)
            
            clip_path = video_fragments_dir / f"clip_{i:02d}.mp4"
            
            # Clip generation: Standardize to 1080x1920, 25fps, stereo 44.1k audio
            ffmpeg_cmd = [
                'ffmpeg', '-y', 
                '-loop', '1', '-framerate', '25', '-t', str(clip_duration), '-i', str(img_path),
                '-i', str(audio_path),
                '-filter_complex', 
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];" +
                f"[0:v]scale=1080:1080[fg];" +
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v];" +
                f"[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a]",
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', str(clip_path)
            ]
            subprocess.run(ffmpeg_cmd, check=True)
            clip_paths.append(clip_path)

        # 4. Sequential Blending (Safe for 4GB RAM)
        current_out = clip_paths[0]
        
        for i in range(1, len(clip_paths)):
            next_clip = clip_paths[i]
            temp_out = video_fragments_dir / f"blend_{i}.mp4"
            
            # Get current duration to set xfade offset
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(current_out)]
            curr_dur = float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
            
            offset = curr_dur - transition_duration
            
            # Blend current result with next clip
            blend_cmd = [
                'ffmpeg', '-y',
                '-i', str(current_out), '-i', str(next_clip),
                '-filter_complex',
                f"[0:v][1:v]xfade=transition=fade:duration={transition_duration}:offset={offset},format=yuv420p[v];" +
                f"[0:a][1:a]acrossfade=d={transition_duration}[a]",
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k', str(temp_out)
            ]
            subprocess.run(blend_cmd, check=True)
            current_out = temp_out

        # 5. Final Music Mix
        music_path = Path("assets/music/background.mp3")
        if music_path.exists():
            logger.info("Adding background music...")
            final_mix_cmd = [
                'ffmpeg', '-y', '-i', str(current_out), '-i', str(music_path),
                '-filter_complex',
                "[1:a]aloop=loop=-1:size=100M,volume=0.12[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
                '-map', '0:v', '-map', '[a]',
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', str(output_path)
            ]
            subprocess.run(final_mix_cmd, check=True)
        else:
            shutil.copy(current_out, output_path)
        
        logger.info(f"Reel successfully generated: {output_path}")
        return output_path

    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
