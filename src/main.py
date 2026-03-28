"""
Main orchestrator for the content generation pipeline.
"""
import argparse
import re
import sys
from datetime import datetime
from typing import Optional
from src.agents import ContentStrategist, ContentGenerator, ImageGenerator
from src.agents.reel_generator import ReelGenerator
from src.agents.cinematic_reel_generator import CinematicReelGenerator
from src.agents.variant_generator import VariantGenerator
from src.pipelines.ContentPipeline import ContentPipeline, PostType
from src.publishers import PostizClient
from src.utils import ContentLogger, load_channel_config, list_available_channels
from src.models import PostResult


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

    parser.add_argument("--generate-variants", action="store_true",
                        help="Generate A/B test variants after main cinematic reel")

    parser.add_argument("--num-variants", type=int, default=3,
                        choices=[2, 3, 4, 5],
                        help="Number of A/B test variants to generate (default: 3)")

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

        # Build set of post types from CLI flags (default to CAROUSEL)
        post_types = set()
        if do_carousel:
            post_types.add(PostType.CAROUSEL)
        if do_reel:
            post_types.add(PostType.REEL)
        if do_cinematic:
            post_types.add(PostType.CINEMATIC)
        if not post_types:
            post_types.add(PostType.CAROUSEL)

        result = pipeline.run(
            channel_name=args.channel,
            dry_run=args.dry_run,
            topic_hint=args.topic,
            skip_ai_image=args.skip_ai_image,
            post_types=post_types,
            cinematic_images=args.cinematic_images,
            with_voice=args.voice,
            generate_variants=args.generate_variants,
            num_variants=args.num_variants,
        )
        sys.exit(0 if result.status == "success" else 1)

    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
