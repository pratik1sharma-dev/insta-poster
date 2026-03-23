"""
Main orchestrator for the content generation pipeline.
"""
import argparse
import sys
from typing import Optional
from src.agents import ContentStrategist, ContentGenerator, ImageGenerator
from src.agents.reel_generator import ReelGenerator
from src.agents.cinematic_reel_generator import CinematicReelGenerator
from src.publishers import PostizClient
from src.utils import ContentLogger, load_channel_config, list_available_channels
from src.models import PostResult


class ContentPipeline:
    """Orchestrates the entire content generation and publishing pipeline."""

    def __init__(self):
        self.strategist              = ContentStrategist()
        self.generator               = ContentGenerator()
        self.image_generator         = ImageGenerator()
        self.reel_generator          = ReelGenerator()
        self.cinematic_reel_generator = CinematicReelGenerator()
        self.publisher               = PostizClient()

    def run(
        self,
        channel_name: str,
        dry_run: bool = False,
        topic_hint: Optional[str] = None,
        skip_ai_image: bool = False,
        reel_only: bool = False,
        no_reel: bool = False,
        cinematic: bool = False,
        cinematic_images: int = 4,
    ) -> PostResult:
        """
        Run the complete content pipeline.

        Args:
            channel_name:      Channel to post to
            dry_run:           Generate but don't post
            topic_hint:        Override AI topic selection
            skip_ai_image:     Use HTML for all slides (no AI image for slide 1)
            reel_only:         Generate and post Reel only, skip carousel
            no_reel:           Skip all Reel generation
            cinematic:         Generate a cinematic mood Reel (2-4 AI images +
                               burned captions, no voice) instead of narrated Reel
            cinematic_images:  Number of images for cinematic Reel (2-4)
        """
        logger = ContentLogger(channel_name)
        logger.logger.info("=" * 80)
        logger.logger.info("Starting content pipeline")
        logger.logger.info("=" * 80)

        try:
            # ── Load config ────────────────────────────────────────────
            logger.logger.info("Loading configuration: %s", channel_name)
            channel_config = load_channel_config(channel_name)
            logger.logger.info("Channel theme: %s", channel_config.theme)

            # ── Phase 1: Strategy ──────────────────────────────────────
            logger.logger.info("\n[Phase 1/4] Determining content strategy...")
            strategy = self.strategist.plan_content(
                channel_config, topic_hint, logger.raw_dir
            )

            if (
                strategy.topic == "DATA INSUFFICIENT"
                or "DATA INSUFFICIENT" in strategy.angle
            ):
                raise ValueError("Aborting: insufficient research data.")

            logger.log_strategy(strategy)

            # ── Phase 1.5: Validation ──────────────────────────────────
            logger.logger.info("\n[Phase 1.5] Validating strategy...")
            validation_prompt = f"""### GROUND RULES:
1. Appending a source label to an unverified number is a CRITICAL FAILURE.
2. The angle must be grounded in real data.

### STRATEGY:
Topic: {strategy.topic}
Angle: {strategy.angle}

### TASK:
1. List the top 2 factual claims this post will make.
2. Verify them.
3. Respond "VALID" or "INVALID".
"""
            validation_result = self.generator._generate_text(validation_prompt)

            try:
                with open(logger.raw_dir / "validation.txt", "w") as f:
                    f.write(validation_result)
            except Exception:
                pass

            if "INVALID" in validation_result.upper():
                raise ValueError(
                    f"Aborting: failed validation: {validation_result[:200]}"
                )
            logger.logger.info("Strategy validated.")

            # ── Phase 2: Content generation ────────────────────────────
            logger.logger.info("\n[Phase 2/4] Generating content...")
            content = self.generator.generate_content(
                strategy, channel_config, logger.raw_dir
            )
            logger.log_content(content)

            # ── Phase 3: Image generation ──────────────────────────────
            logger.logger.info("\n[Phase 3/4] Generating carousel images...")
            images_dir  = logger.get_images_dir()
            image_paths = self.image_generator.generate_carousel(
                content, strategy, channel_config, images_dir, skip_ai_image
            )

            for i, p in enumerate(image_paths, 1):
                logger.log_image_generation(i, p)

            if not image_paths:
                raise Exception("No images were generated")

            # ── Phase 3.5: Reel generation ─────────────────────────────
            reel_path = None

            if not no_reel:
                if cinematic:
                    # ── Cinematic mood Reel (AI images + burned captions) ──
                    logger.logger.info(
                        "\n[Phase 3.5] Generating cinematic Reel (%d images)...",
                        cinematic_images
                    )
                    try:
                        reel_output = images_dir / "reel_cinematic.mp4"
                        reel_path   = self.cinematic_reel_generator.generate(
                            content=content,
                            strategy=strategy,
                            channel_config=channel_config,
                            output_path=reel_output,
                            num_images=cinematic_images,
                        )
                        logger.logger.info("Cinematic Reel: %s", reel_path)
                    except Exception as e:
                        logger.logger.error(
                            "Cinematic Reel failed (continuing): %s", e
                        )
                        reel_path = None
                    finally:
                        try:
                            self.cinematic_reel_generator.cleanup()
                        except Exception:
                            pass

                else:
                    # ── Narrated portrait Reel ─────────────────────────
                    logger.logger.info("\n[Phase 3.5] Generating narrated Reel...")
                    try:
                        reel_output = images_dir / "reel.mp4"
                        reel_path   = self.reel_generator.generate_reel(
                            content=content,
                            strategy=strategy,
                            channel_config=channel_config,
                            image_paths=image_paths,
                            output_path=reel_output,
                        )
                        logger.logger.info("Narrated Reel: %s", reel_path)
                    except Exception as e:
                        logger.logger.error(
                            "Narrated Reel failed (continuing): %s", e
                        )
                        reel_path = None
                    finally:
                        try:
                            self.reel_generator.cleanup()
                        except Exception:
                            pass

            # ── Phase 4: Publishing ────────────────────────────────────
            logger.logger.info("\n[Phase 4/4] Publishing...")

            if dry_run:
                logger.logger.info("DRY RUN — skipping posting")

            publish_images = (
                [reel_path] if (reel_only and reel_path) else image_paths
            )

            result = self.publisher.publish_post(
                images=publish_images,
                content=content,
                strategy=strategy,
                channel=channel_name,
                dry_run=dry_run,
            )

            logger.log_post_result(result)

            # ── Summary ────────────────────────────────────────────────
            logger.logger.info("\n" + "=" * 80)
            logger.logger.info("Pipeline complete!")
            logger.logger.info("Topic:     %s", strategy.topic)
            logger.logger.info("Slides:    %d", len(content.slides))
            logger.logger.info(
                "Reel:      %s",
                str(reel_path) if reel_path else "not generated"
            )
            logger.logger.info("Status:    %s", result.status)
            if result.status == "success":
                logger.logger.info("Post ID:   %s", result.post_id)
            logger.logger.info("Output:    %s", logger.get_output_dir())
            logger.logger.info("=" * 80)

            return result

        except Exception as e:
            logger.log_error(e, "Pipeline execution")
            logger.logger.error("\nPipeline failed: %s", e)
            raise


def main():
    parser = argparse.ArgumentParser(
        description="AI-Powered Instagram Content Generation and Posting"
    )

    parser.add_argument("--channel",       type=str,  help="Channel name")
    parser.add_argument("--list-channels", action="store_true")
    parser.add_argument("--dry-run",       action="store_true",
                        help="Generate without posting")
    parser.add_argument("--topic",         type=str,
                        help="Specific topic (overrides AI selection)")
    parser.add_argument("--skip-ai-image", action="store_true",
                        help="Use HTML for all slides")
    parser.add_argument("--reel-only",     action="store_true",
                        help="Post Reel only, skip carousel")
    parser.add_argument("--no-reel",       action="store_true",
                        help="Skip all Reel generation")
    parser.add_argument("--cinematic",     action="store_true",
                        help="Generate cinematic mood Reel (AI images + captions)")
    parser.add_argument("--cinematic-images", type=int, default=4,
                        choices=[2, 3, 4],
                        help="Number of images for cinematic Reel (default: 4)")

    args = parser.parse_args()

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

    if not args.channel:
        parser.print_help()
        print("\nError: --channel is required")
        sys.exit(1)

    try:
        pipeline = ContentPipeline()
        result   = pipeline.run(
            channel_name=args.channel,
            dry_run=args.dry_run,
            topic_hint=args.topic,
            skip_ai_image=args.skip_ai_image,
            reel_only=args.reel_only,
            no_reel=args.no_reel,
            cinematic=args.cinematic,
            cinematic_images=args.cinematic_images,
        )
        sys.exit(0 if result.status == "success" else 1)

    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()