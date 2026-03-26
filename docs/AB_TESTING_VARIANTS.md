# A/B Testing Framework - Variant Generator

## Overview

The Variant Generator creates multiple versions of cinematic reels with controlled variations for A/B testing. This allows you to test different approaches and measure which performs best with your audience.

## What Gets Varied

Each variant differs in three key dimensions:

### 1. Hook Style (5 variants)
- **Shocking Statistic**: Lead with a surprising number or fact
- **Contrarian Statement**: Challenge conventional wisdom
- **Pattern Interrupt Question**: Open with an intriguing question
- **Personal Cost/Benefit**: Show immediate personal impact
- **Status Quo Challenge**: Call out the common mistake

### 2. Visual Style (3 variants)
- **Cinematic Noir**: Moody lighting, high contrast, dramatic shadows
- **Warm Natural**: Soft focus, golden hour glow, intimate atmosphere
- **Modern Minimal**: Clean aesthetic, bright diffused lighting, minimalist

### 3. Music Volume (3 levels)
- **0.08**: Subtle background music
- **0.12**: Balanced music presence
- **0.15**: More prominent music (auto-adjusted if voice enabled)

## Usage

### Command Line

Generate 3 variants after creating the main cinematic reel:

```bash
python -m src.main \
  --channel your_channel \
  --cinematic \
  --generate-variants \
  --num-variants 3 \
  --dry-run
```

### Full Example with Voice

```bash
python -m src.main \
  --channel money_mindset \
  --cinematic \
  --voice \
  --cinematic-images 4 \
  --generate-variants \
  --num-variants 3 \
  --dry-run
```

### Arguments

- `--generate-variants`: Enable variant generation (must be used with `--cinematic`)
- `--num-variants N`: Number of variants to generate (2-5, default: 3)
- `--voice`: Include voiceover narration in all variants
- `--cinematic-images N`: Number of images per variant (2-6, default: 4)

## Output Structure

After generation, you'll find:

```
output/YYYY-MM-DD_CHANNEL_NAME/images/
├── reel_cinematic.mp4          # Main reel (unchanged)
└── variants/
    ├── variant_A.mp4           # Hook: Shocking Stat, Visual: Noir, Music: 0.08
    ├── variant_B.mp4           # Hook: Contrarian, Visual: Warm, Music: 0.12
    ├── variant_C.mp4           # Hook: Question, Visual: Minimal, Music: 0.15
    └── variants_metadata.json  # Detailed metadata
```

## Metadata File

`variants_metadata.json` contains:

```json
{
  "experiment": {
    "created_at": "2026-03-25T10:30:00",
    "topic": "Compound Interest Power",
    "total_variants": 3
  },
  "variants": [
    {
      "variant_id": "A",
      "output_path": "variants/variant_A.mp4",
      "parameters": {
        "hook_style": "shocking_stat",
        "hook_name": "Shocking Statistic",
        "visual_style": "cinematic_noir",
        "visual_style_name": "Cinematic Noir",
        "music_volume": 0.08
      },
      "metadata": {
        "generated_at": "2026-03-25T10:30:15",
        "topic": "Compound Interest Power",
        "angle": "₹5,000 monthly for 35 years..."
      },
      "changes": [
        "Hook: Shocking Statistic",
        "Visuals: Cinematic Noir",
        "Music: 0.08"
      ]
    }
  ]
}
```

## Testing Recommendations

### 1. Equal Audience Split
- Upload all variants to Instagram as separate posts/reels
- Schedule them at similar times across different days
- Use identical captions and hashtags for consistency

### 2. Metrics to Track
- **Completion Rate**: % who watch until the end
- **Engagement Rate**: Likes, comments, shares per 1000 impressions
- **Share Rate**: How often viewers share the content
- **Save Rate**: How often viewers bookmark it

### 3. Determining a Winner
- Run each variant for at least 24-48 hours
- Winner should show **>15% improvement** to be statistically significant
- Sample size: Minimum 1,000 views per variant for reliable data

### 4. Learning & Iteration
- Document which hook/visual/music combination won
- Use winning patterns in future content
- Test 2-3 new variants monthly to keep improving

## Example Workflow

1. **Generate Base Content + Variants**
   ```bash
   python -m src.main --channel money_mindset --cinematic --generate-variants
   ```

2. **Review Output**
   - Check `variants_metadata.json` for what changed in each variant
   - Preview each video to ensure quality

3. **Test in Market**
   - Post Variant A on Monday 10am
   - Post Variant B on Wednesday 10am
   - Post Variant C on Friday 10am

4. **Analyze Results** (after 48 hours each)
   - Compare completion rate, engagement, shares
   - Identify the winner

5. **Apply Learnings**
   - Update your content strategy based on results
   - Use winning hook style, visual style, or music volume

## Advanced: Programmatic Access

Use the VariantGenerator directly in Python:

```python
from src.agents.variant_generator import VariantGenerator
from pathlib import Path

generator = VariantGenerator()

variants = generator.generate_variants(
    content=generated_content,
    strategy=content_strategy,
    channel_config=channel_config,
    base_output_path=Path("output/reel_cinematic.mp4"),
    num_variants=3,
    num_images=4,
    with_voice=False
)

# Process variants
for variant in variants:
    print(f"Variant {variant['variant_id']}: {variant['output_path']}")
    print(f"Changes: {variant['changes']}")
```

## Technical Details

### How It Works

1. **Hook Variation**: Each variant modifies the strategy's reasoning field to influence script generation with different hook instructions

2. **Visual Variation**: Image prompts receive different style suffixes that change lighting, mood, and aesthetic

3. **Music Variation**: Final audio mix uses different volume levels (automatically reduced if voice narration is enabled)

### Limitations

- Variants are generated sequentially (not in parallel)
- Each variant regenerates images from scratch (no caching)
- Music volume variation requires re-mixing the final output

### Performance

- **Time**: ~2-4 minutes per variant (depending on image provider)
- **Storage**: ~50-100 MB per variant (depending on length/quality)
- **API Costs**: Multiplies image generation costs by number of variants

## Best Practices

1. **Start Small**: Begin with 2-3 variants, not 5
2. **Test One Variable**: If possible, vary only hook OR visuals, not both
3. **Document Everything**: Keep the metadata.json file for future reference
4. **Be Patient**: Wait for sufficient sample size before declaring a winner
5. **Iterate**: Use learnings to inform your base content strategy

## Troubleshooting

### Variant Generation Fails
- Check that `--cinematic` flag is enabled
- Ensure research data is available (variant generation requires it)
- Verify image provider API keys are configured

### Output Missing
- Check the `variants/` subdirectory
- Review logs for generation errors
- Ensure sufficient disk space

### Inconsistent Results
- Variants use the same research data but different hook instructions
- Some variation in script generation is expected and desired
- Visual anchor should remain consistent across variants

## Future Enhancements

Planned improvements:
- Parallel variant generation for faster processing
- Image caching to reduce redundant API calls
- More granular control over what gets varied
- Automated performance tracking integration
- Statistical significance calculator
