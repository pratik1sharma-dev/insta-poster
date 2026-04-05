import re
from enum import Enum
from datetime import datetime
from typing import Optional, Iterable, Set

from src.agents import ContentStrategist, ContentGenerator, ImageGenerator
from src.agents.reel_generator import ReelGenerator
from src.agents.cinematic_reel_generator import CinematicReelGenerator
from src.agents.variant_generator import VariantGenerator
from src.publishers import PostizClient
from src.utils import ContentLogger, load_channel_config
from src.models import PostResult


class PostType(Enum):
    CAROUSEL = "carousel"
    REEL = "reel"
    CINEMATIC = "cinematic"


class ContentPipeline:
    """Orchestrates the entire content generation and publishing pipeline."""

    def __init__(self):
        self.strategist = ContentStrategist()
        self.generator = ContentGenerator()
        self.image_generator = ImageGenerator()
        self.reel_generator = ReelGenerator()
        self.cinematic_reel_generator = CinematicReelGenerator()
        self.variant_generator = VariantGenerator()
        self.publisher = PostizClient()

    def run(
        self,
        channel_name: str,
        dry_run: bool = False,
        topic_hint: Optional[str] = None,
        skip_ai_image: bool = False,
        post_types: Optional[Iterable[PostType]] = None,
        cinematic_images: int = 4,
        with_voice: bool = False,
        generate_variants: bool = False,
        num_variants: int = 3,
    ) -> PostResult:
        
        """
        Run the complete content pipeline.

        Args:
            channel_name:      Channel to post to
            dry_run:           Generate but don't post
            topic_hint:        Override AI topic selection
            skip_ai_image:     Use HTML for all slides
            post_types:        Iterable of PostType values to generate/post
            cinematic_images:  Number of images for cinematic Reel (2-4)
            generate_variants: Generate A/B test variants after main cinematic reel
            num_variants:      Number of A/B test variants to generate (2-5)
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
            # Resolve Instagram account — allows multiple configs to share one account
            instagram_account = channel_config.instagram_account or channel_name
            if instagram_account != channel_name:
                logger.logger.info("Publishing to Instagram account: %s", instagram_account)

            # ── Phase 1: Strategy + Validation (up to 2 retries) ─────────
            MAX_STRATEGY_ATTEMPTS = 3
            strategy = None
            for attempt in range(1, MAX_STRATEGY_ATTEMPTS + 1):
                logger.logger.info("\n[Phase 1/4] Determining content strategy (attempt %d/%d)...", attempt, MAX_STRATEGY_ATTEMPTS)
                strategy = self.strategist.plan_content(
                    channel_config, topic_hint, logger.raw_dir
                )

                if (
                    strategy.topic == "DATA INSUFFICIENT"
                    or "DATA INSUFFICIENT" in strategy.angle
                ):
                    raise ValueError("Aborting: insufficient research data.")

                logger.log_strategy(strategy)

                # ── Phase 1.5: Validation ──────────────────────────────
                logger.logger.info("\n[Phase 1.5] Validating strategy (attempt %d/%d)...", attempt, MAX_STRATEGY_ATTEMPTS)
                validation_prompt = f"""### STRATEGY:
Topic: {strategy.topic}
Angle: {strategy.angle}

### TASK:
Review this strategy angle. Mark it INVALID only if it contains a claim that is:
- Factually impossible or obviously fabricated (e.g. "100% of Indians invest in stocks")
- Directly contradicts well-known reality

Plausible statistics, reasonable estimates, and common knowledge are VALID even if not sourced.

End your response with EXACTLY one of these two lines:
   VERDICT: VALID
   VERDICT: INVALID
"""
                validation_result = self.generator._generate_text(validation_prompt)

                try:
                    with open(logger.raw_dir / f"validation_attempt{attempt}.txt", "w") as f:
                        f.write(validation_result)
                except Exception:
                    pass

                if not re.search(r'^VERDICT:\s*INVALID\s*$', validation_result, re.MULTILINE | re.IGNORECASE):
                    logger.logger.info("Strategy validated.")
                    break

                logger.logger.warning(
                    "Strategy failed validation (attempt %d/%d): %s",
                    attempt, MAX_STRATEGY_ATTEMPTS, validation_result[:200],
                )
                if attempt == MAX_STRATEGY_ATTEMPTS:
                    raise ValueError(
                        f"Aborting: strategy failed validation after {MAX_STRATEGY_ATTEMPTS} attempts. "
                        f"Last result: {validation_result[:200]}"
                    )

            # ── Phase 2: Content generation ────────────────────────────
            logger.logger.info("\n[Phase 2/4] Generating content...")
            content = self.generator.generate_content(
                strategy, channel_config, logger.raw_dir
            )
            logger.log_content(content)

            # ── Phase 3: Image generation ──────────────────────────────
            image_paths = []
            images_dir  = logger.get_images_dir()
            
            # Normalize post types: default to CAROUSEL if unspecified
            post_types_set: Set[PostType] = set(post_types) if post_types else {PostType.CAROUSEL}

            # Narrated Reel needs the carousel images as its base
            if PostType.CAROUSEL in post_types_set or PostType.REEL in post_types_set:
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
            if PostType.REEL in post_types_set:
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
            if PostType.CINEMATIC in post_types_set:
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

            # 3. A/B Test Variants (optional, after main cinematic reel)
            variants_metadata = []
            if generate_variants and (PostType.CINEMATIC in post_types_set) and cinematic_path:
                logger.logger.info("\n[Phase 3.7] Generating A/B test variants...")
                logger.logger.info("Creating %d variants for testing...", num_variants)
                try:
                    variants_metadata = self.variant_generator.generate_variants(
                        content=content,
                        strategy=strategy,
                        channel_config=channel_config,
                        base_output_path=cinematic_path,
                        num_variants=num_variants,
                        num_images=cinematic_images,
                        with_voice=with_voice,
                    )
                    logger.logger.info("Generated %d variants successfully.", len(variants_metadata))

                    # Log variant details
                    for variant in variants_metadata:
                        logger.logger.info(
                            "Variant %s: %s",
                            variant['variant_id'],
                            ", ".join(variant['changes'])
                        )
                except Exception as e:
                    logger.logger.error("Variant generation failed: %s", e)
                finally:
                    self.variant_generator.cleanup()

            # ── Phase 4: Publishing ────────────────────────────────────
            logger.logger.info("\n[Phase 4/4] Publishing...")

            if dry_run:
                logger.logger.info("DRY RUN MODE — skipping actual posting")

            # Track overall result
            final_result = PostResult(
                post_id=None,
                timestamp=datetime.now(),
                channel=instagram_account,
                content=content,
                strategy=strategy,
                status="success",
            )

            # 1. Post Carousel
            if PostType.CAROUSEL in post_types_set:
                logger.logger.info("Publishing carousel post...")
                res = self.publisher.publish_post(
                    images=image_paths,
                    content=content,
                    strategy=strategy,
                    channel=instagram_account,
                    dry_run=dry_run,
                )
                logger.log_post_result(res)
                if res.status == "success":
                    logger.logger.info("Carousel posted! ID: %s", res.post_id)
                    final_result.post_id = res.post_id
                else:
                    final_result.status = "failed"
                    final_result.error_message = res.error_message

            # 2. Post Narrated Reel
            if (PostType.REEL in post_types_set) and reel_path and reel_path.exists():
                logger.logger.info("Publishing narrated Reel...")
                res = self.publisher.publish_reel(
                    video_path=reel_path,
                    content=content,
                    strategy=strategy,
                    channel=instagram_account,
                    dry_run=dry_run,
                )
                logger.log_post_result(res)
                if res.status == "success":
                    logger.logger.info("Narrated Reel posted! ID: %s", res.post_id)
                    if not final_result.post_id: final_result.post_id = res.post_id

            # 3. Post Cinematic Reel
            if (PostType.CINEMATIC in post_types_set) and cinematic_path and cinematic_path.exists():
                logger.logger.info("Publishing cinematic Reel...")
                res = self.publisher.publish_reel(
                    video_path=cinematic_path,
                    content=content,
                    strategy=strategy,
                    channel=instagram_account,
                    dry_run=dry_run,
                )
                logger.log_post_result(res)
                if res.status == "success":
                    logger.logger.info("Cinematic Reel posted! ID: %s", res.post_id)
                    if not final_result.post_id: final_result.post_id = res.post_id

            # ── Feedback recording (non-fatal) ────────────────────────
            if not dry_run and final_result.status == "success" and final_result.post_id:
                try:
                    from src.utils.feedback_store import init_db, record_post, get_active_config_version
                    init_db()
                    _meta = self.cinematic_reel_generator.last_script_meta if cinematic_path else {}
                    _post_type = "cinematic" if cinematic_path else ("reel" if reel_path else "carousel")
                    _config_version = get_active_config_version(instagram_account) or "initial"
                    record_post(
                        post_result=final_result,
                        post_type=_post_type,
                        config_version=_config_version,
                        hook_text=_meta.get("hook_text") or (content.slides[0].headline if content.slides else ""),
                        story_spine=_meta.get("story_spine") or strategy.angle,
                        visual_anchor=_meta.get("visual_anchor"),
                        cinematic_path=str(cinematic_path) if cinematic_path else None,
                    )
                except Exception as _fb_err:
                    logger.logger.warning("Feedback recording failed (non-fatal): %s", _fb_err)

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

