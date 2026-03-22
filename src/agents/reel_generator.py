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
        """Complete pipeline to generate a Reel .mp4 file with smooth transitions."""
        logger.info(f"Starting Reel generation for: {strategy.topic}")
        
        # 1. Generate Script
        script_segments = self._generate_narration_script(content.slides, strategy, channel_config)
        
        # 2. Create Audio
        audio_fragments_dir = self.temp_dir / "audio"
        audio_fragments_dir.mkdir(exist_ok=True)
        audio_paths = self._create_audio_segments(script_segments, audio_fragments_dir)
        
        # 3. Assemble Video Fragments
        video_fragments_dir = self.temp_dir / "video"
        video_fragments_dir.mkdir(exist_ok=True)
        clip_paths = []
        durations = []

        transition_duration = 0.5 # seconds

        for i, (img_path, audio_path) in enumerate(zip(image_paths, audio_paths), 1):
            audio_dur = self._get_audio_duration(audio_path)
            # Add a small buffer for the transition overlap
            clip_duration = audio_dur + transition_duration
            durations.append(clip_duration)
            
            clip_path = video_fragments_dir / f"clip_{i:02d}.mp4"
            
            ffmpeg_cmd = [
                'ffmpeg', '-y', 
                '-loop', '1', '-framerate', '25', '-t', str(clip_duration), '-i', str(img_path),
                '-i', str(audio_path),
                '-filter_complex', 
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];" +
                f"[0:v]scale=1080:1080[fg];" +
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]",
                '-map', '[v]', '-map', '1:a',
                '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage',
                '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-ac', '2',
                '-pix_fmt', 'yuv420p', str(clip_path)
            ]
            
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
            clip_paths.append(clip_path)

        # 4. Concatenate with XFADE
        # If only one clip, just copy it
        if len(clip_paths) == 1:
            subprocess.run(['ffmpeg', '-y', '-i', str(clip_paths[0]), '-c', 'copy', str(output_path)], check=True)
            return output_path

        # Build complex filter for transitions
        # We process clips in pairs using xfade
        filter_str = ""
        inputs = []
        for i, cp in enumerate(clip_paths):
            inputs.extend(['-i', str(cp)])
        
        # Initial crossfade between clip 0 and 1
        offset = durations[0] - transition_duration
        filter_str += f"[0:v][1:v]xfade=transition=fade:duration={transition_duration}:offset={offset}[v1]; "
        
        # Audio needs to be concatenated too
        audio_filter_str = "[0:a][1:a]concat=n=2:v=0:a=1[a1]; "

        # Chain subsequent clips
        last_v = "v1"
        last_a = "a1"
        current_offset = offset + (durations[1] - transition_duration)

        for i in range(2, len(clip_paths)):
            next_v = f"v{i}"
            next_a = f"a{i}"
            filter_str += f"[{last_v}][{i}:v]xfade=transition=fade:duration={transition_duration}:offset={current_offset}[{next_v}]; "
            audio_filter_str += f"[{last_a}][{i}:a]concat=n=2:v=0:a=1[{next_a}]; "
            
            current_offset += (durations[i] - transition_duration)
            last_v = next_v
            last_a = next_a

        final_v = last_v
        final_a = last_a

        # 5. Optional Background Music Mixing
        music_path = Path("assets/music/background.mp3")
        if music_path.exists():
            logger.info("Mixing background music...")
            # We add the music as an additional input
            # [final_a] is the narration
            # [bg_music] is the looped, lowered volume music with fade out
            total_duration = sum(durations) - (len(durations)-1)*transition_duration
            
            final_cmd = [
                'ffmpeg', '-y'
            ] + inputs + ['-i', str(music_path),
                '-filter_complex', 
                filter_str + audio_filter_str + 
                f"[{len(clip_paths)}:a]aloop=loop=-1:size=2e+09,volume=0.15,afade=t=out:st={total_duration-2}:d=2[bg_m]; " +
                f"[{final_a}][bg_m]amix=inputs=2:duration=first:dropout_transition=2[a_mixed]",
                '-map', f"[{final_v}]", '-map', "[a_mixed]",
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                str(output_path)
            ]
        else:
            logger.warning("No background music found at assets/music/background.mp3. Skipping mix.")
            final_cmd = [
                'ffmpeg', '-y'
            ] + inputs + [
                '-filter_complex', filter_str + audio_filter_str,
                '-map', f"[{final_v}]", '-map', f"[{final_a}]",
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                str(output_path)
            ]
        
        logger.info("Assembling final video with transitions and music...")
        subprocess.run(final_cmd, check=True, capture_output=True)
        
        logger.info(f"Reel with transitions successfully generated at: {output_path}")
        return output_path
        
        logger.info(f"Reel successfully generated at: {output_path}")
        return output_path

    def cleanup(self):
        """Clean up temporary files."""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
