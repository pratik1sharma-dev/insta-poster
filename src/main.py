"""
Main orchestrator for the content generation pipeline.
"""
import argparse
import sys
from datetime import datetime
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
        post_carousel: bool = True,
        post_reel: bool = False,
        post_cinematic: bool = False,
        cinematic_images: int = 4,
        with_voice: bool = False,
    ) -> PostResult:
        """
        Run the complete content pipeline.

        Args:
            channel_name:      Channel to post to
            dry_run:           Generate but don't post
            topic_hint:        Override AI topic selection
            skip_ai_image:     Use HTML for all slides
            post_carousel:     Generate and post square carousel
            post_reel:         Generate and post narrated portrait Reel
            post_cinematic:    Generate and post cinematic mood Reel
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
            image_paths = []
            images_dir  = logger.get_images_dir()
            
            # Narrated Reel needs the carousel images as its base
            if post_carousel or post_reel:
                logger.logger.info("\n[Phase 3/4] Generating carousel images...")
                image_paths = self.image_generator.generate_carousel(
                    content, strategy, channel_config, images_dir, skip_ai_image
                )

                for i, p in enumerate(image_paths, 1):
                    logger.log_image_generation(i, p)

                if not image_paths:
                    raise Exception("No images were generated")

            # ── Phase 3.5: Reel generation ─────────────────────────────
            reel_path = None
            cinematic_path = None

            # 1. Narrated Reel
            if post_reel:
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
                    logger.logger.info("Narrated Reel generated successfully.")
                except Exception as e:
                    logger.logger.error("Narrated Reel failed: %s", e)
                finally:
                    self.reel_generator.cleanup()

            # 2. Cinematic Reel
            if post_cinematic:
                logger.logger.info("\n[Phase 3.6] Generating cinematic Reel (voice=%s)...", with_voice)
                try:
                    cin_output = images_dir / "reel_cinematic.mp4"
                    cinematic_path = self.cinematic_reel_generator.generate(
                        content=content,
                        strategy=strategy,
                        channel_config=channel_config,
                        output_path=cin_output,
                        num_images=cinematic_images,
                        with_voice=with_voice,
                    )
                    logger.logger.info("Cinematic Reel generated successfully.")
                except Exception as e:
                    logger.logger.error("Cinematic Reel failed: %s", e)
                finally:
                    self.cinematic_reel_generator.cleanup()

            # ── Phase 4: Publishing ────────────────────────────────────
            logger.logger.info("\n[Phase 4/4] Publishing...")

            if dry_run:
                logger.logger.info("DRY RUN MODE — skipping actual posting")

            # Track overall result
            final_result = PostResult(
                post_id=None,
                timestamp=datetime.now(),
                channel=channel_name,
                content=content,
                strategy=strategy,
                status="success",
            )

            # 1. Post Carousel
            if post_carousel:
                logger.logger.info("Publishing carousel post...")
                res = self.publisher.publish_post(
                    images=image_paths,
                    content=content,
                    strategy=strategy,
                    channel=channel_name,
                    dry_run=dry_run,
                )
                logger.log_post_result(res)
                if res.status == "success":
                    logger.logger.info(f"Carousel posted! ID: {res.post_id}")
                    final_result.post_id = res.post_id
                else:
                    final_result.status = "failed"
                    final_result.error_message = res.error_message

            # 2. Post Narrated Reel
            if post_reel and reel_path and reel_path.exists():
                logger.logger.info("Publishing narrated Reel...")
                res = self.publisher.publish_reel(
                    video_path=reel_path,
                    content=content,
                    strategy=strategy,
                    channel=channel_name,
                    dry_run=dry_run,
                )
                logger.log_post_result(res)
                if res.status == "success":
                    logger.logger.info(f"Narrated Reel posted! ID: {res.post_id}")
                    if not final_result.post_id: final_result.post_id = res.post_id

            # 3. Post Cinematic Reel
            if post_cinematic and cinematic_path and cinematic_path.exists():
                logger.logger.info("Publishing cinematic Reel...")
                res = self.publisher.publish_reel(
                    video_path=cinematic_path,
                    content=content,
                    strategy=strategy,
                    channel=channel_name,
                    dry_run=dry_run,
                )
                logger.log_post_result(res)
                if res.status == "success":
                    logger.logger.info(f"Cinematic Reel posted! ID: {res.post_id}")
                    if not final_result.post_id: final_result.post_id = res.post_id

            # ── Summary ────────────────────────────────────────────────
            logger.logger.info("\n" + "=" * 80)
            logger.logger.info("Pipeline complete!")
            logger.logger.info("Status:    %s", final_result.status)
            logger.logger.info("Output:    %s", logger.get_output_dir())
            logger.logger.info("=" * 80)

            return final_result

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
    
    # Content type toggles
    parser.add_argument("--carousel",      action="store_true", help="Opt-in: Generate/Post Carousel")
    parser.add_argument("--reel",          action="store_true", help="Opt-in: Generate/Post Narrated Reel")
    parser.add_argument("--cinematic",     action="store_true", help="Opt-in: Generate/Post Cinematic Reel")
    
    parser.add_argument("--cinematic-images", type=int, default=4,
                        choices=[2, 3, 4, 5, 6],
                        help="Number of images for cinematic Reel (default: 4)")

    parser.add_argument("--voice", action="store_true",
                        help="Add voiceover narration to cinematic/reel (requires TTS)")

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

    # Default logic: if no content type is specified, default to Carousel
    do_carousel  = args.carousel
    do_reel      = args.reel
    do_cinematic = args.cinematic
    
    if not (do_carousel or do_reel or do_cinematic):
        do_carousel = True

    try:
        pipeline = ContentPipeline()
        result   = pipeline.run(
            channel_name=args.channel,
            dry_run=args.dry_run,
            topic_hint=args.topic,
            skip_ai_image=args.skip_ai_image,
            post_carousel=do_carousel,
            post_reel=do_reel,
            post_cinematic=do_cinematic,
            cinematic_images=args.cinematic_images,
            with_voice=args.voice,
        )
        sys.exit(0 if result.status == "success" else 1)

    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
