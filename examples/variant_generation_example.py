"""
Example: Programmatic A/B Variant Generation

This script shows how to use the VariantGenerator class directly
from Python code for more control over the generation process.
"""

from pathlib import Path
from src.agents import ContentStrategist, ContentGenerator
from src.agents.variant_generator import VariantGenerator
from src.utils import load_channel_config
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_basic_variant_generation():
    """
    Example 1: Basic variant generation with default settings
    """
    print("\n" + "=" * 80)
    print("Example 1: Basic Variant Generation")
    print("=" * 80 + "\n")

    # Load channel configuration
    channel_config = load_channel_config("money_mindset")

    # Create content strategy
    strategist = ContentStrategist()
    strategy = strategist.plan_content(
        channel_config,
        topic_hint="compound interest power",
        output_dir=Path("output/test")
    )

    # Generate content
    generator = ContentGenerator()
    content = generator.generate_content(
        strategy,
        channel_config,
        output_dir=Path("output/test")
    )

    # Generate variants
    variant_gen = VariantGenerator()
    variants = variant_gen.generate_variants(
        content=content,
        strategy=strategy,
        channel_config=channel_config,
        base_output_path=Path("output/test/reel_cinematic.mp4"),
        num_variants=3,
        num_images=4,
        with_voice=False
    )

    # Print results
    print(f"\n✓ Generated {len(variants)} variants:")
    for v in variants:
        print(f"\nVariant {v['variant_id']}:")
        print(f"  Path: {v['output_path']}")
        print(f"  Changes: {', '.join(v['changes'])}")

    variant_gen.cleanup()


def example_custom_variants():
    """
    Example 2: Custom variant generation with specific parameters
    """
    print("\n" + "=" * 80)
    print("Example 2: Custom Variant Generation")
    print("=" * 80 + "\n")

    # Load configuration
    channel_config = load_channel_config("money_mindset")

    # Create strategy with specific topic
    strategist = ContentStrategist()
    strategy = strategist.plan_content(
        channel_config,
        topic_hint="why index funds beat active funds",
        output_dir=Path("output/test")
    )

    # Generate content
    generator = ContentGenerator()
    content = generator.generate_content(
        strategy,
        channel_config,
        output_dir=Path("output/test")
    )

    # Generate more variants with voice
    variant_gen = VariantGenerator()
    variants = variant_gen.generate_variants(
        content=content,
        strategy=strategy,
        channel_config=channel_config,
        base_output_path=Path("output/test/reel_cinematic_custom.mp4"),
        num_variants=5,  # Maximum variants
        num_images=5,    # More images per variant
        with_voice=True  # Add voice narration
    )

    # Analyze variants
    print(f"\n✓ Generated {len(variants)} variants with voice:")
    for v in variants:
        params = v['parameters']
        print(f"\nVariant {v['variant_id']}:")
        print(f"  Hook: {params['hook_name']}")
        print(f"  Visual: {params['visual_style_name']}")
        print(f"  Music: {params['music_volume']:.2f}")
        print(f"  Images: {params['num_images']}")
        print(f"  Voice: {params['with_voice']}")

    variant_gen.cleanup()


def example_variant_comparison():
    """
    Example 3: Generate variants and prepare for comparison
    """
    print("\n" + "=" * 80)
    print("Example 3: Variant Comparison Preparation")
    print("=" * 80 + "\n")

    # Setup
    channel_config = load_channel_config("money_mindset")
    strategist = ContentStrategist()
    generator = ContentGenerator()
    variant_gen = VariantGenerator()

    # Generate base content
    strategy = strategist.plan_content(
        channel_config,
        topic_hint="retirement planning mistakes",
        output_dir=Path("output/comparison_test")
    )

    content = generator.generate_content(
        strategy,
        channel_config,
        output_dir=Path("output/comparison_test")
    )

    # Generate variants
    variants = variant_gen.generate_variants(
        content=content,
        strategy=strategy,
        channel_config=channel_config,
        base_output_path=Path("output/comparison_test/reel_cinematic.mp4"),
        num_variants=3,
        num_images=4,
        with_voice=False
    )

    # Create testing plan
    print("\n" + "=" * 80)
    print("A/B TESTING PLAN")
    print("=" * 80)

    print(f"\nTopic: {strategy.topic}")
    print(f"Angle: {strategy.angle}")
    print(f"\nGenerated {len(variants)} variants for testing:\n")

    for i, v in enumerate(variants, 1):
        params = v['parameters']
        print(f"{i}. Variant {v['variant_id']}:")
        print(f"   File: {Path(v['output_path']).name}")
        print(f"   Hook Style: {params['hook_name']}")
        print(f"   Visual Style: {params['visual_style_name']}")
        print(f"   Music Volume: {params['music_volume']:.2f}")
        print("")

    print("Recommended Testing Schedule:")
    print("  Monday 10am:    Post Variant A")
    print("  Wednesday 10am: Post Variant B")
    print("  Friday 10am:    Post Variant C")
    print("")
    print("Metrics to Track (48 hours each):")
    print("  - Completion Rate (%)")
    print("  - Engagement Rate (likes + comments + shares per 1000 views)")
    print("  - Share Rate")
    print("  - Save/Bookmark Rate")
    print("")
    print("Decision Criteria:")
    print("  Winner must show >15% improvement to be significant")
    print("")

    variant_gen.cleanup()


def example_inspect_metadata():
    """
    Example 4: Inspect variant metadata after generation
    """
    print("\n" + "=" * 80)
    print("Example 4: Inspect Variant Metadata")
    print("=" * 80 + "\n")

    import json

    # Assume variants have been generated
    metadata_path = Path("output/test/variants/variants_metadata.json")

    if metadata_path.exists():
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

        print("Experiment Overview:")
        exp = metadata['experiment']
        print(f"  Created: {exp['created_at']}")
        print(f"  Topic: {exp['topic']}")
        print(f"  Angle: {exp['angle']}")
        print(f"  Total Variants: {exp['total_variants']}")
        print("")

        print("Variants:")
        for v in metadata['variants']:
            print(f"\n  Variant {v['variant_id']}:")
            print(f"    Changes: {', '.join(v['changes'])}")
            print(f"    Path: {v['output_path']}")

        print("\nTesting Framework:")
        framework = metadata['testing_framework']
        print(f"  Dimensions: {', '.join(framework['dimensions'])}")
        print(f"  Recommendation: {framework['recommendation']}")
    else:
        print(f"Metadata file not found: {metadata_path}")
        print("Generate variants first using one of the above examples.")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("A/B Variant Generation Examples")
    print("=" * 80)

    # Run examples
    try:
        # Uncomment the examples you want to run:

        # example_basic_variant_generation()
        # example_custom_variants()
        # example_variant_comparison()
        example_inspect_metadata()

        print("\n" + "=" * 80)
        print("Examples completed successfully!")
        print("=" * 80 + "\n")

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        print(f"\nError: {e}")
        print("\nMake sure you have:")
        print("  1. Configured your channel in configs/channels/")
        print("  2. Set up API keys in .env")
        print("  3. Generated base content first (if inspecting metadata)")
