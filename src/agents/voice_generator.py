"""
Voice Generator — TTS providers for cinematic reel narration.
"""
import asyncio
import logging
from pathlib import Path
from typing import List

from src.models import ChannelConfig
from src.config import settings

logger = logging.getLogger(__name__)


class VoiceGenerator:
    """Generates voiceover audio using configurable TTS providers."""

    def generate(self, lines: List[str], output_dir: Path, channel_config: ChannelConfig) -> List[Path]:
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
