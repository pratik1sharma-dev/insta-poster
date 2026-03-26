# A/B Testing Variant Generator - Quick Start

## What It Does

Automatically generates 2-5 variants of your cinematic reel, each with different:
- **Hook style** (e.g., shocking stat vs. question vs. contrarian)
- **Visual style** (e.g., noir vs. warm vs. minimal)
- **Music volume** (e.g., 0.08 vs. 0.12 vs. 0.15)

Perfect for A/B testing to discover what resonates best with your audience.

## Quick Start

### 1. Generate Variants

```bash
python -m src.main \
  --channel your_channel \
  --cinematic \
  --generate-variants \
  --num-variants 3 \
  --dry-run
```

### 2. Find Your Variants

```
output/YYYY-MM-DD_CHANNEL/images/variants/
├── variant_A.mp4
├── variant_B.mp4
├── variant_C.mp4
└── variants_metadata.json
```

### 3. Review What Changed

Check `variants_metadata.json` to see exactly what's different in each variant:

```json
{
  "variant_id": "A",
  "changes": [
    "Hook: Shocking Statistic",
    "Visuals: Cinematic Noir",
    "Music: 0.08"
  ]
}
```

### 4. Test in Market

Post each variant as a separate reel on different days and track:
- Completion rate
- Engagement (likes, comments, shares)
- Which variant performs best

### 5. Learn & Iterate

Use the winning variant's approach (hook style, visual style, music) in future content.

## Examples

### Basic: 3 Variants (Default)
```bash
python -m src.main --channel money_mindset --cinematic --generate-variants
```

### With Voice Narration
```bash
python -m src.main --channel money_mindset --cinematic --voice --generate-variants
```

### More Variants (5 total)
```bash
python -m src.main --channel money_mindset --cinematic --generate-variants --num-variants 5
```

### Custom Image Count
```bash
python -m src.main --channel money_mindset --cinematic --cinematic-images 6 --generate-variants
```

## Arguments

| Flag | Description | Default |
|------|-------------|---------|
| `--generate-variants` | Enable variant generation | Off |
| `--num-variants N` | How many variants (2-5) | 3 |
| `--cinematic-images N` | Images per variant (2-6) | 4 |
| `--voice` | Add voiceover to all variants | Off |

## Requirements

- Must use `--cinematic` flag (variants only work with cinematic reels)
- Research data must be available (Tavily API enabled or manual data)
- Sufficient API credits for image generation (costs multiply by variant count)

## Pro Tips

1. **Start with 3 variants** - Enough variety without overwhelming
2. **Test one dimension** - If results are unclear, reduce variables
3. **Wait 48 hours** - Give each variant time to gather data
4. **Document winners** - Keep `variants_metadata.json` for reference
5. **Iterate monthly** - Test 2-3 new variants each month to keep improving

## Full Documentation

See [docs/AB_TESTING_VARIANTS.md](docs/AB_TESTING_VARIANTS.md) for:
- Detailed metrics to track
- Statistical significance guidelines
- Advanced programmatic usage
- Troubleshooting guide

---

**Implementation Status**: ✅ Complete (Priority 10 from CINEMATIC_REEL_IMPROVEMENTS.md)
