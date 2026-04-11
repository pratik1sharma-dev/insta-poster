#!/bin/bash
#
# Example: Generate A/B Test Variants for Cinematic Reels
#
# This script demonstrates how to use the variant generator to create
# multiple versions of a reel for A/B testing.
#

echo "=========================================="
echo "A/B Testing Variant Generator - Example"
echo "=========================================="
echo ""

# Configuration
CHANNEL="money_mindset"
TOPIC="compound interest power"
NUM_VARIANTS=3
CINEMATIC_IMAGES=4

# Example 1: Basic variant generation (no voice)
echo "Example 1: Basic Variant Generation"
echo "------------------------------------"
echo "Generating $NUM_VARIANTS variants for channel: $CHANNEL"
echo ""

python -m src.main \
  --channel "$CHANNEL" \
  --topic "$TOPIC" \
  --cinematic \
  --cinematic-images $CINEMATIC_IMAGES \
  --generate-variants \
  --num-variants $NUM_VARIANTS \
  --dry-run

echo ""
echo "✓ Variants generated!"
echo ""
echo "Check output in: output/YYYY-MM-DD_${CHANNEL}/images/variants/"
echo "  - variant_A.mp4 (Hook: Shocking Stat, Visual: Noir, Music: 0.08)"
echo "  - variant_B.mp4 (Hook: Contrarian, Visual: Warm, Music: 0.12)"
echo "  - variant_C.mp4 (Hook: Question, Visual: Minimal, Music: 0.15)"
echo "  - variants_metadata.json (detailed info)"
echo ""

# Example 2: Variants with voice narration
echo "=========================================="
echo "Example 2: Variants with Voice Narration"
echo "=========================================="
echo ""

python -m src.main \
  --channel "$CHANNEL" \
  --topic "why index funds beat active funds" \
  --cinematic \
  --voice \
  --generate-variants \
  --num-variants 3 \
  --dry-run

echo ""
echo "✓ Voice-enabled variants generated!"
echo ""

# Example 3: Maximum variants (5)
echo "=========================================="
echo "Example 3: Maximum Variants (5 total)"
echo "=========================================="
echo ""

python -m src.main \
  --channel "$CHANNEL" \
  --topic "retirement planning mistakes" \
  --cinematic \
  --cinematic-images 5 \
  --generate-variants \
  --num-variants 5 \
  --dry-run

echo ""
echo "✓ 5 variants generated for comprehensive testing!"
echo ""
echo "Variants will use these hook styles:"
echo "  A: Shocking Statistic"
echo "  B: Contrarian Statement"
echo "  C: Pattern Interrupt Question"
echo "  D: Personal Cost/Benefit"
echo "  E: Status Quo Challenge"
echo ""

# Example 4: Production run (actually post to Instagram)
echo "=========================================="
echo "Example 4: Production Run (Dry-run removed)"
echo "=========================================="
echo ""
echo "WARNING: This will actually post to Instagram!"
echo "Remove --dry-run only when ready to publish."
echo ""
echo "# python -m src.main \\"
echo "#   --channel \"$CHANNEL\" \\"
echo "#   --cinematic \\"
echo "#   --generate-variants \\"
echo "#   --num-variants 3"
echo ""

# Summary
echo "=========================================="
echo "Summary: Testing Your Variants"
echo "=========================================="
echo ""
echo "1. Review variants_metadata.json to see what changed"
echo "2. Post each variant on different days (e.g., Mon/Wed/Fri)"
echo "3. Track metrics for each:"
echo "   - Completion rate (%)"
echo "   - Engagement rate (likes + comments + shares per 1000 views)"
echo "   - Share rate"
echo "   - Save rate"
echo "4. Winner = >15% improvement over others"
echo "5. Use winning hook/visual/music in future content"
echo ""
echo "For detailed documentation, see:"
echo "  - docs/AB_TESTING_VARIANTS.md (full guide)"
echo "  - VARIANT_GENERATOR_QUICKSTART.md (quick reference)"
echo ""
