"""
Comprehensive logging system for content generation pipeline.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from src.models import ContentStrategy, GeneratedContent, PostResult
from src.config import settings


class ContentLogger:
    """Logs all content generation decisions and outputs."""

    def __init__(self, channel_name: str):
        """
        Initialize logger for a channel.

        Args:
            channel_name: Name of the channel being processed
        """
        self.channel_name = channel_name
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create output directory structure
        self.base_dir = Path(settings.output_dir) / channel_name / self.timestamp
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        self.images_dir = self.base_dir / "images"
        self.images_dir.mkdir(exist_ok=True)

        # Setup Python logging
        self.logger = logging.getLogger(f"ContentLogger.{channel_name}")
        self.logger.setLevel(getattr(logging, settings.log_level.upper()))

        # File handler
        log_file = self.base_dir / "pipeline.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, settings.log_level.upper()))

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.logger.info(f"Initialized content pipeline for channel: {channel_name}")

    def log_strategy(self, strategy: ContentStrategy) -> None:
        """
        Log content strategy decisions.

        Args:
            strategy: ContentStrategy instance
        """
        strategy_path = self.base_dir / "strategy.json"
        strategy_data = strategy.model_dump(mode="json")

        with open(strategy_path, "w") as f:
            json.dump(strategy_data, f, indent=2)

        self.logger.info(f"Strategy: {strategy.topic}")
        self.logger.info(f"Hook Type: {strategy.hook_type}")
        self.logger.info(f"Carousel Length: {strategy.carousel_length}")
        self.logger.info(f"Visual Style: {strategy.visual_style}")
        self.logger.debug(f"Reasoning: {strategy.reasoning}")

    def log_content(self, content: GeneratedContent) -> None:
        """
        Log generated content.

        Args:
            content: GeneratedContent instance
        """
        content_path = self.base_dir / "content.json"
        content_data = content.model_dump(mode="json")

        with open(content_path, "w") as f:
            json.dump(content_data, f, indent=2)

        self.logger.info(f"Generated {len(content.slides)} slides")
        self.logger.info(f"Caption length: {len(content.caption)} characters")
        self.logger.info(f"Hashtags: {', '.join(content.hashtags[:5])}...")

        # Save caption separately for easy review
        caption_path = self.base_dir / "caption.txt"
        with open(caption_path, "w") as f:
            f.write(content.caption)
            f.write("\n\n")
            f.write(" ".join(content.hashtags))
            f.write("\n\n")
            f.write(content.call_to_action)

    def log_image_generation(self, slide_number: int, image_path: Path) -> None:
        """
        Log image generation for a slide.

        Args:
            slide_number: Slide number
            image_path: Path where image was saved
        """
        self.logger.info(f"Generated image for slide {slide_number}: {image_path.name}")

    def log_post_result(self, result: PostResult) -> None:
        """
        Log final posting result.

        Args:
            result: PostResult instance
        """
        result_path = self.base_dir / "post_result.json"
        result_data = result.model_dump(mode="json")

        # Convert datetime to string for JSON serialization
        if isinstance(result_data.get("timestamp"), datetime):
            result_data["timestamp"] = result_data["timestamp"].isoformat()

        with open(result_path, "w") as f:
            json.dump(result_data, f, indent=2)

        if result.status == "success":
            self.logger.info(f"Successfully posted! Post ID: {result.post_id}")
            if result.performance_tracking_url:
                self.logger.info(f"Track performance: {result.performance_tracking_url}")
        elif result.status == "dry_run":
            self.logger.info("Dry run completed - no actual posting")
        else:
            self.logger.error(f"Post failed: {result.error_message}")

    def log_error(self, error: Exception, context: str) -> None:
        """
        Log an error with context.

        Args:
            error: Exception that occurred
            context: Context where error occurred
        """
        error_path = self.base_dir / "errors.log"

        with open(error_path, "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Context: {context}\n")
            f.write(f"Error: {type(error).__name__}: {str(error)}\n")
            f.write(f"{'='*80}\n")

        self.logger.error(f"Error in {context}: {error}", exc_info=True)

    def get_output_dir(self) -> Path:
        """Get the output directory for this run."""
        return self.base_dir

    def get_images_dir(self) -> Path:
        """Get the images directory for this run."""
        return self.images_dir
