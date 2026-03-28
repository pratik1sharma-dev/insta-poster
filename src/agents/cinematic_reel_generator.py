import logging
import shutil
from pathlib import Path
from typing import Optional

from src.models import ContentStrategy, ChannelConfig, GeneratedContent
from src.agents.content_generator import ContentGenerator
from src.agents.cinematic_script_generator import CinematicScriptGenerator
from src.agents.cinematic_image_generator import CinematicImageGenerator
from src.agents.voice_generator import VoiceGenerator
from src.agents.video_composer import VideoComposer
from src.config import settings

logger = logging.getLogger(__name__)


class CinematicReelGenerator:
    """
    Generates a cinematic mood Reel:
    - AI-generated background images (9:16, no text)
    - High-impact 'spiky' captions overlaid
    - Moody background music
    - No narration (mood film style)
    """

    def __init__(self):
        self.temp_dir = Path("temp_cinematic")
        self.temp_dir.mkdir(exist_ok=True)

        generator = ContentGenerator()
        self.script_gen = CinematicScriptGenerator(generator)
        self.image_gen = CinematicImageGenerator()
        self.voice_gen = VoiceGenerator()
        self.video_composer = VideoComposer()

    def generate(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        output_path: Path,
        num_images: int = 4,
        with_voice: bool = False,
        music_volume: Optional[float] = None,
    ) -> Path:
        """
        Full pipeline: generate scenes → generate 9:16 images →
        overlay text with motion → (optional voice) → blend → music.

        num_images is used as a max_scenes hint (3-5 recommended).
        """
        logger.info("Starting Cinematic Reel: %s (voice=%s)", strategy.topic, with_voice)

        # 1. Generate scenes (story lines + image prompts + motion effects)
        scenes = self.script_gen.generate_script_and_prompts(strategy, channel_config, num_images)

        # 1b. Refine image prompts via dedicated SD-optimized AI call
        scenes = self.image_gen.refine_sd_prompts(scenes, strategy, channel_config)

        # 2. Generate cinematic images (9:16), one per scene
        image_dir = self.temp_dir / "images"
        image_dir.mkdir(exist_ok=True)
        scenes = self.image_gen.generate_images(scenes, image_dir)

        # 3. Generate voice (if enabled)
        audio_paths = None
        if with_voice:
            all_lines = [line for scene in scenes for line in scene["lines"]]
            audio_dir = self.temp_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_paths = self.voice_gen.generate(all_lines, audio_dir, channel_config)

        # 4. Build clips with text overlays + motion effects
        video_dir = self.temp_dir / "video"
        video_dir.mkdir(exist_ok=True)
        transition_dur = getattr(settings, "cinematic_transition_duration", 0.6)
        clip_paths = self.video_composer.build_clips(scenes, video_dir, transition_dur, audio_paths)

        # 5. Blend clips
        blended = self.video_composer.blend_clips(clip_paths, video_dir, transition_dur)

        # 6. Add music
        if music_volume is None:
            music_volume = getattr(settings, "cinematic_music_volume", 0.08 if with_voice else 0.15)
        self.video_composer.mix_music(blended, output_path, music_volume)

        logger.info("Cinematic Reel complete: %s", output_path)
        return output_path

    def cleanup(self):
        """Remove all temporary files."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
