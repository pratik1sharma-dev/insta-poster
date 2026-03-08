"""
Main orchestrator for the content generation pipeline.
"""
import argparse
import sys
from typing import Optional
from src.agents import ContentStrategist, ContentGenerator, ImageGenerator
from src.publishers import PostizClient
from src.utils import ContentLogger, load_channel_config, list_available_channels
from src.models import PostResult


class ContentPipeline:
    """Orchestrates the entire content generation and publishing pipeline."""

    def __init__(self):
        """Initialize the pipeline with all agents."""
        self.strategist = ContentStrategist()
        self.generator = ContentGenerator()
        self.image_generator = ImageGenerator()
        self.publisher = PostizClient()

    def run(
        self, channel_name: str, dry_run: bool = False, topic_hint: Optional[str] = None
    ) -> PostResult:
        """
        Run the complete content pipeline.

        Args:
            channel_name: Name of the channel to post to
            dry_run: If True, generate content but don't post
            topic_hint: Optional specific topic to use

        Returns:
            PostResult with all pipeline information
        """
        # Initialize logger
        logger = ContentLogger(channel_name)
        logger.logger.info("="*80)
        logger.logger.info("Starting content pipeline")
        logger.logger.info("="*80)

        try:
            # Load channel configuration
            logger.logger.info(f"Loading configuration for channel: {channel_name}")
            channel_config = load_channel_config(channel_name)
            logger.logger.info(f"Channel theme: {channel_config.theme}")

            # Phase 1: Content Strategy
            logger.logger.info("\n[Phase 1/4] Determining content strategy...")
            strategy = self.strategist.plan_content(channel_config, topic_hint)
            logger.log_strategy(strategy)

            # Phase 2: Content Generation
            logger.logger.info("\n[Phase 2/4] Generating content...")
            content = self.generator.generate_content(strategy, channel_config)
            logger.log_content(content)

            # Phase 3: Image Generation
            logger.logger.info("\n[Phase 3/4] Generating images...")
            images_dir = logger.get_images_dir()
            image_paths = self.image_generator.generate_carousel(
                content, strategy, images_dir
            )

            for i, image_path in enumerate(image_paths, 1):
                logger.log_image_generation(i, image_path)

            if not image_paths:
                raise Exception("No images were generated")

            # Phase 4: Publishing
            logger.logger.info("\n[Phase 4/4] Publishing to Instagram...")
            if dry_run:
                logger.logger.info("DRY RUN MODE - Skipping actual posting")

            result = self.publisher.publish_post(
                images=image_paths,
                content=content,
                strategy=strategy,
                channel=channel_name,
                dry_run=dry_run,
            )

            logger.log_post_result(result)

            # Summary
            logger.logger.info("\n" + "="*80)
            logger.logger.info("Pipeline completed successfully!")
            logger.logger.info("="*80)
            logger.logger.info(f"Topic: {strategy.topic}")
            logger.logger.info(f"Slides: {len(content.slides)}")
            logger.logger.info(f"Status: {result.status}")
            if result.status == "success":
                logger.logger.info(f"Post ID: {result.post_id}")
            logger.logger.info(f"Output directory: {logger.get_output_dir()}")
            logger.logger.info("="*80)

            return result

        except Exception as e:
            logger.log_error(e, "Pipeline execution")
            logger.logger.error(f"\nPipeline failed: {e}")
            raise


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="AI-Powered Instagram Content Generation and Posting"
    )

    parser.add_argument(
        "--channel",
        type=str,
        help="Channel name to post to (e.g., book_summaries)",
    )

    parser.add_argument(
        "--list-channels",
        action="store_true",
        help="List all available channels",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate content without posting",
    )

    parser.add_argument(
        "--topic",
        type=str,
        help="Specific topic to use (overrides AI selection)",
    )

    args = parser.parse_args()

    # List channels if requested
    if args.list_channels:
        channels = list_available_channels()
        if not channels:
            print("No channels configured.")
            return

        print("\nAvailable channels:")
        print("-" * 80)
        for name, theme in channels.items():
            print(f"  {name:20s} - {theme}")
        print("-" * 80)
        return

    # Validate channel argument
    if not args.channel:
        parser.print_help()
        print("\nError: --channel is required (or use --list-channels)")
        sys.exit(1)

    # Run pipeline
    try:
        pipeline = ContentPipeline()
        result = pipeline.run(
            channel_name=args.channel,
            dry_run=args.dry_run,
            topic_hint=args.topic,
        )

        if result.status == "success":
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
