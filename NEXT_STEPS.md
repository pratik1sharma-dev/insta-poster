# Next Steps: Testing the A/B Variant Generator

The A/B Testing Framework (Priority 10) has been successfully implemented. Here's how to test and use it.

---

## Quick Test (Recommended First Step)

Run a dry-run to verify everything works:

```bash
python -m src.main \
  --channel your_channel_name \
  --cinematic \
  --generate-variants \
  --num-variants 3 \
  --dry-run
```

**Expected Output:**
```
output/YYYY-MM-DD_CHANNEL/images/
├── reel_cinematic.mp4
└── variants/
    ├── variant_A.mp4
    ├── variant_B.mp4
    ├── variant_C.mp4
    └── variants_metadata.json
```

---

## Verification Checklist

After running the test, verify:

### 1. Files Created
- [ ] Main reel exists: `reel_cinematic.mp4`
- [ ] Variants directory created: `variants/`
- [ ] 3 variant videos exist: `variant_A.mp4`, `variant_B.mp4`, `variant_C.mp4`
- [ ] Metadata file exists: `variants_metadata.json`

### 2. Metadata Content
Open `variants_metadata.json` and check:
- [ ] `experiment` section has topic, angle, timestamp
- [ ] `variants` array has 3 entries
- [ ] Each variant has: `variant_id`, `output_path`, `parameters`, `changes`
- [ ] Parameters show different: `hook_style`, `visual_style`, `music_volume`

### 3. Video Quality
Play each variant and verify:
- [ ] Videos play without errors
- [ ] Each variant looks visually different
- [ ] Text overlays are readable
- [ ] Videos are 9:16 portrait format
- [ ] Duration is appropriate (4-6 seconds per image)

### 4. Logs
Check the logs for:
- [ ] "Starting A/B Variant Generation" message
- [ ] Each variant shows: Hook Style, Visual Style, Music Volume
- [ ] "✓ Variant X generated successfully" for each variant
- [ ] "A/B Variant Generation Complete" message
- [ ] No errors or warnings (except expected validation warnings)

---

## Common Issues & Solutions

### Issue: "Cannot generate cinematic reel without research data"
**Solution**: Ensure Tavily API is configured or provide manual research data

### Issue: Variants look identical
**Solution**: Check `variants_metadata.json` to see what actually changed. Visual differences may be subtle.

### Issue: Only 1 or 2 variants generated
**Solution**: Check logs for errors. One variant failing shouldn't stop others. Review error messages.

### Issue: "VariantGenerator" not found
**Solution**: Ensure you're in the correct directory and imports are working:
```bash
python -c "from src.agents.variant_generator import VariantGenerator; print('OK')"
```

---

## Usage Patterns

### Pattern 1: Test Different Hooks
Focus on varying hook styles to see what resonates:
```bash
python -m src.main \
  --channel money_mindset \
  --topic "compound interest power" \
  --cinematic \
  --generate-variants \
  --num-variants 5
```
Review which hook (shocking stat, contrarian, question, etc.) performs best.

### Pattern 2: Test Visual Styles
Generate fewer variants to focus on visual differences:
```bash
python -m src.main \
  --channel money_mindset \
  --cinematic \
  --generate-variants \
  --num-variants 3
```
Compare Cinematic Noir vs Warm Natural vs Modern Minimal.

### Pattern 3: With Voice Narration
Test how voice affects engagement:
```bash
python -m src.main \
  --channel money_mindset \
  --cinematic \
  --voice \
  --generate-variants \
  --num-variants 3
```
Note: Music volume automatically adjusts lower when voice is present.

### Pattern 4: Maximum Testing
Generate all possible combinations:
```bash
python -m src.main \
  --channel money_mindset \
  --cinematic \
  --cinematic-images 5 \
  --generate-variants \
  --num-variants 5 \
  --dry-run
```
5 variants = all hook styles tested.

---

## Production Workflow

Once testing is successful, use this workflow:

### Week 1: Generate Variants
```bash
python -m src.main \
  --channel your_channel \
  --cinematic \
  --generate-variants \
  --num-variants 3
```

### Week 1-2: Test in Market
- **Monday**: Post Variant A to Instagram
- **Wednesday**: Post Variant B to Instagram
- **Friday**: Post Variant C to Instagram

*Use identical captions and hashtags for all three*

### Week 2: Collect Metrics
Track for each variant (48 hours minimum):
- Completion rate (%)
- Engagement rate (likes + comments + shares per 1000 views)
- Share rate
- Save rate

### Week 2: Analyze Results
- Which variant had highest completion rate?
- Which got most engagement?
- Was the difference >15%? (= statistically significant)

### Week 3+: Apply Learnings
- Use winning hook style in future content
- Apply winning visual aesthetic
- Adjust music volume based on results

### Repeat Monthly
- Generate 2-3 new variants each month
- Keep testing and iterating
- Document patterns that work

---

## Advanced Usage

### Programmatic Generation
Use Python code for more control:

```python
from src.agents.variant_generator import VariantGenerator
from pathlib import Path

# Assuming you have content, strategy, and channel_config

generator = VariantGenerator()
variants = generator.generate_variants(
    content=content,
    strategy=strategy,
    channel_config=channel_config,
    base_output_path=Path("output/reel.mp4"),
    num_variants=3,
    num_images=4,
    with_voice=False
)

# Process results
for v in variants:
    print(f"Generated: {v['output_path']}")
    print(f"Changes: {v['changes']}")
```

### Batch Processing
Generate variants for multiple topics:

```bash
for topic in "compound interest" "index funds" "emergency fund"; do
  python -m src.main \
    --channel money_mindset \
    --topic "$topic" \
    --cinematic \
    --generate-variants \
    --dry-run
done
```

---

## Resources

### Documentation
- **Full Guide**: `docs/AB_TESTING_VARIANTS.md`
- **Quick Start**: `VARIANT_GENERATOR_QUICKSTART.md`
- **Implementation Details**: `IMPLEMENTATION_SUMMARY.md`

### Examples
- **Shell Script**: `examples/variant_generation_example.sh`
- **Python Code**: `examples/variant_generation_example.py`

### Code
- **Implementation**: `src/agents/variant_generator.py`
- **Integration**: `src/main.py` (Phase 3.7)
- **Exports**: `src/agents/__init__.py`

---

## Support

### Getting Help

1. **Check Logs**: Most issues show up in logs with clear error messages
2. **Review Documentation**: Start with `VARIANT_GENERATOR_QUICKSTART.md`
3. **Check Examples**: Run `examples/variant_generation_example.sh`
4. **Inspect Metadata**: Check `variants_metadata.json` for what actually changed

### Reporting Issues

When reporting problems, include:
- Command you ran
- Error message from logs
- Content of `variants_metadata.json` (if generated)
- Expected vs actual behavior

---

## Success Metrics

You'll know it's working when:

✅ 3 video files generated in `variants/` directory
✅ Each video plays correctly and looks different
✅ `variants_metadata.json` shows different parameters for each
✅ Logs show successful generation of all variants
✅ No errors or critical warnings in output

---

## What's Next?

After successful testing:

1. ✅ **Test with Real Channel**: Run with actual channel configuration
2. ✅ **Review Quality**: Ensure variants meet your quality standards
3. ✅ **Post First Set**: Upload to Instagram and start tracking metrics
4. ✅ **Document Winners**: Keep records of what works
5. ✅ **Iterate**: Use learnings to improve future content

---

**Ready to test?** Start with the Quick Test command at the top of this document!
