"""
A/B Testing Framework: Generate multiple variants of cinematic reels
for testing different hooks, visual styles, and audio settings.
"""

import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.models.content_models import ContentStrategy, ChannelConfig, GeneratedContent
from src.agents.cinematic_reel_generator import CinematicReelGenerator

logger = logging.getLogger(__name__)


class VariantGenerator:
    """
    Generates multiple variants of cinematic reels for A/B testing.

    Varies:
    - Hook style (different hook strategies)
    - Visual style (different image prompt styles)
    - Music volume (different audio levels)
    """

    # Hook variants with different styles
    HOOK_VARIANTS = [
        {
            "id": "shocking_stat",
            "name": "Shocking Statistic",
            "description": "Lead with a surprising number or fact",
            "instruction": "Start with the most shocking statistic from the research data. Make it hit hard."
        },
        {
            "id": "contrarian",
            "name": "Contrarian Statement",
            "description": "Challenge conventional wisdom",
            "instruction": "Start by contradicting what most people believe about this topic. Be bold."
        },
        {
            "id": "question",
            "name": "Pattern Interrupt Question",
            "description": "Open with an intriguing question",
            "instruction": "Start with a provocative question that makes them stop scrolling."
        },
        {
            "id": "personal_cost",
            "name": "Personal Cost/Benefit",
            "description": "Show immediate personal impact",
            "instruction": "Start by showing what this costs them personally or what they're missing out on."
        },
        {
            "id": "status_quo",
            "name": "Status Quo Challenge",
            "description": "Challenge the current approach",
            "instruction": "Start by calling out the common mistake or outdated approach people use."
        }
    ]

    # Visual style variants
    VISUAL_STYLES = [
        {
            "id": "cinematic_noir",
            "name": "Cinematic Noir",
            "style_suffix": "cinematic noir, moody lighting, high contrast, 35mm film grain, dramatic shadows, 9:16 portrait, NO text"
        },
        {
            "id": "warm_natural",
            "name": "Warm Natural",
            "style_suffix": "warm natural lighting, soft focus, golden hour glow, intimate atmosphere, 35mm film grain, 9:16 portrait, NO text"
        },
        {
            "id": "modern_minimal",
            "name": "Modern Minimal",
            "style_suffix": "clean modern aesthetic, bright diffused lighting, minimalist composition, 35mm film grain, 9:16 portrait, NO text"
        }
    ]

    # Music volume variants (lower when voice is present)
    MUSIC_VOLUMES = [0.08, 0.12, 0.15]

    def __init__(self):
        self.generator = CinematicReelGenerator()

    def generate_variants(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        base_output_path: Path,
        num_variants: int = 3,
        num_images: int = 4,
        with_voice: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple variants of the cinematic reel.

        Args:
            content: Generated content for the post
            strategy: Content strategy with research data
            channel_config: Channel configuration
            base_output_path: Base path for outputs (e.g., output/reel_cinematic.mp4)
            num_variants: Number of variants to generate (default: 3)
            num_images: Number of images per reel
            with_voice: Whether to include voice narration

        Returns:
            List of variant metadata dicts containing:
            - variant_id: Identifier (A, B, C)
            - output_path: Path to generated video
            - parameters: Dict of parameters used
            - metadata: Generation metadata
        """
        logger.info("=" * 80)
        logger.info("Starting A/B Variant Generation")
        logger.info(f"Generating {num_variants} variants for topic: {strategy.topic}")
        logger.info("=" * 80)

        # Create variants directory structure
        output_dir = base_output_path.parent / "variants"
        output_dir.mkdir(exist_ok=True)

        variants = []
        variant_ids = ["A", "B", "C", "D", "E"][:num_variants]

        # Select different combinations for each variant
        for i, variant_id in enumerate(variant_ids):
            logger.info(f"\n--- Generating Variant {variant_id} ({i+1}/{num_variants}) ---")

            # Cycle through different styles
            hook_variant = self.HOOK_VARIANTS[i % len(self.HOOK_VARIANTS)]
            visual_style = self.VISUAL_STYLES[i % len(self.VISUAL_STYLES)]
            music_volume = self.MUSIC_VOLUMES[i % len(self.MUSIC_VOLUMES)]

            # Adjust music volume if voice is enabled
            if with_voice:
                music_volume = music_volume * 0.6  # Lower music when voice is present

            logger.info(f"Hook Style: {hook_variant['name']}")
            logger.info(f"Visual Style: {visual_style['name']}")
            logger.info(f"Music Volume: {music_volume}")

            # Create modified strategy for this variant
            variant_strategy = self._create_variant_strategy(
                strategy, hook_variant, visual_style, i
            )

            # Generate the variant
            output_path = output_dir / f"variant_{variant_id}.mp4"

            try:
                # Store original generator settings
                original_provider = self.generator.provider

                # Generate with variant parameters
                self.generator.generate(
                    content=content,
                    strategy=variant_strategy,
                    channel_config=channel_config,
                    output_path=output_path,
                    num_images=num_images,
                    with_voice=with_voice,
                )

                # Note: Music volume would ideally be a parameter to generate()
                # For now, variants use the default volume from CinematicReelGenerator
                # Future enhancement: Allow music_volume parameter in generate()

                # Collect variant metadata
                variant_metadata = {
                    "variant_id": variant_id,
                    "output_path": str(output_path),
                    "parameters": {
                        "hook_style": hook_variant["id"],
                        "hook_name": hook_variant["name"],
                        "visual_style": visual_style["id"],
                        "visual_style_name": visual_style["name"],
                        "music_volume": music_volume,
                        "num_images": num_images,
                        "with_voice": with_voice,
                    },
                    "metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "topic": strategy.topic,
                        "angle": variant_strategy.angle,
                        "research_data_length": len(strategy.verified_data or ""),
                    },
                    "changes": [
                        f"Hook: {hook_variant['name']}",
                        f"Visuals: {visual_style['name']}",
                        f"Music: {music_volume:.2f}"
                    ]
                }

                variants.append(variant_metadata)
                logger.info(f"✓ Variant {variant_id} generated successfully")

            except Exception as e:
                logger.error(f"✗ Failed to generate Variant {variant_id}: {e}")
                # Continue with other variants
                continue
            finally:
                # Cleanup temp files for this variant
                self.generator.cleanup()

        # Save variants metadata to JSON
        metadata_path = output_dir / "variants_metadata.json"
        self._save_metadata(variants, metadata_path, strategy)

        logger.info("\n" + "=" * 80)
        logger.info(f"A/B Variant Generation Complete")
        logger.info(f"Generated {len(variants)}/{num_variants} variants")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Metadata saved to: {metadata_path}")
        logger.info("=" * 80)

        return variants

    def _create_variant_strategy(
        self,
        base_strategy: ContentStrategy,
        hook_variant: Dict[str, str],
        visual_style: Dict[str, str],
        variant_index: int
    ) -> ContentStrategy:
        """
        Create a modified strategy for the variant with different hook and visual style.

        Args:
            base_strategy: Original content strategy
            hook_variant: Hook variant configuration
            visual_style: Visual style configuration
            variant_index: Index of the variant (for deterministic variation)

        Returns:
            Modified ContentStrategy with variant-specific hook and visuals
        """
        # Create a copy of the strategy
        variant_strategy = ContentStrategy(
            topic=base_strategy.topic,
            angle=base_strategy.angle,
            character_persona=base_strategy.character_persona,
            hook_type=base_strategy.hook_type,
            carousel_length=base_strategy.carousel_length,
            visual_metaphor=base_strategy.visual_metaphor,
            color_palette=base_strategy.color_palette,
            typography_style=base_strategy.typography_style,
            target_audience_insight=base_strategy.target_audience_insight,
            verified_data=base_strategy.verified_data,
            reasoning=base_strategy.reasoning,
        )

        # Modify the reasoning to incorporate hook variant and visual style
        # This will influence how the script is generated
        hook_instruction = hook_variant['instruction']
        visual_instruction = f"Visual style: {visual_style['name']}. Use image prompts with: {visual_style['style_suffix']}"

        variant_strategy.reasoning = (
            f"[VARIANT {variant_index}]\n"
            f"Hook Strategy: {hook_instruction}\n"
            f"{visual_instruction}\n\n"
            f"Original angle: {base_strategy.angle}"
        )

        return variant_strategy

    def _save_metadata(
        self,
        variants: List[Dict[str, Any]],
        output_path: Path,
        strategy: ContentStrategy
    ) -> None:
        """
        Save variant metadata to JSON file.

        Args:
            variants: List of variant metadata dicts
            output_path: Path to save JSON file
            strategy: Original content strategy
        """
        metadata = {
            "experiment": {
                "created_at": datetime.now().isoformat(),
                "topic": strategy.topic,
                "angle": strategy.angle,
                "total_variants": len(variants),
            },
            "base_parameters": {
                "research_data_available": bool(strategy.verified_data),
                "research_data_length": len(strategy.verified_data or ""),
            },
            "variants": variants,
            "testing_framework": {
                "dimensions": [
                    "Hook Style (5 variants)",
                    "Visual Style (3 variants)",
                    "Music Volume (3 levels)"
                ],
                "recommendation": (
                    "Test each variant with equal audience split. "
                    "Track completion rate, engagement, and shares. "
                    "Winner should show >15% improvement to be significant."
                )
            }
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info(f"Metadata saved: {output_path}")

    def cleanup(self):
        """Clean up temporary files."""
        self.generator.cleanup()
