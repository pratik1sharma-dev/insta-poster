# Cinematic Reel Duration Logic

## Dynamic Duration Based on Text Length

### Formula
```python
calculated_duration = max(3.0, (word_count / 3.5) + 1.5)
final_duration = max(base_duration, calculated_duration)
```

### Breakdown
- **Reading time**: `word_count / 3.5` (average adult reading speed ~3.5 words/sec)
- **Processing time**: `+1.5s` (0.5s to see image + 1s for message to land)
- **Minimum**: `3.0s` (even short text needs time for visual impact)
- **Base duration override**: If base setting is higher, use that

### Examples

| Words | Calculation | Duration | Why |
|-------|-------------|----------|-----|
| 6 words | 6/3.5 + 1.5 = 3.2s | **4.0s** | Uses base duration (4s) |
| 8 words | 8/3.5 + 1.5 = 3.8s | **4.0s** | Uses base duration (4s) |
| 10 words | 10/3.5 + 1.5 = 4.4s | **4.4s** | Calculated > base |
| 12 words | 12/3.5 + 1.5 = 4.9s | **4.9s** | Needs more time |
| 14 words | 14/3.5 + 1.5 = 5.5s | **5.5s** | Maximum allowed |

### Total Reel Duration

**With 4 slides:**
```
Scenario A (all 8 words):
4 slides × 4.0s = 16s + transitions = ~17s

Scenario B (mixed lengths: 8, 10, 12, 14 words):
4.0s + 4.4s + 4.9s + 5.5s = 18.8s + transitions = ~20s

Scenario C (all 14 words):
4 slides × 5.5s = 22s + transitions = ~23s
```

**With 6 slides (for 30s target):**
```
Average 10 words per slide:
6 × 4.4s = 26.4s + transitions = ~28s ✅
```

### Configuration

In `.env` or `settings.py`:
```python
# Base duration (will be overridden if text needs more time)
CINEMATIC_SLIDE_DURATION = 4.0

# Transition overlap duration
CINEMATIC_TRANSITION_DURATION = 0.6
```

### Best Practices

1. **Keep captions 8-12 words** for optimal pacing
2. **14 words maximum** to avoid long pauses
3. **Use 4-6 slides** for 15-30 second reels
4. **Use 6-8 slides** for 30-45 second reels

### Reading Speed Science

- **Silent reading**: 200-250 words/minute (~3.5-4 wpm)
- **Reading to comprehend**: Slower, ~150-200 wpm (~3 wpm)
- **Reading on mobile**: 20-30% slower
- **Reading + processing image**: Need 1-1.5s extra

Our formula (`word_count / 3.5 + 1.5`) accounts for:
- ✅ Medium reading speed (not rushed)
- ✅ Visual processing time
- ✅ Emotional impact time
- ✅ Re-reading short phrases

### Validation

The system now logs duration calculation:
```
[Clip 1] 8 words → 4.0s duration (base=4.0s)
[Clip 2] 12 words → 4.9s duration (base=4.0s)
[Clip 3] 14 words → 5.5s duration (base=4.0s)
[Clip 4] 10 words → 4.4s duration (base=4.0s)

Total: ~18.8s + transitions = ~20s
```

### Edge Cases

**Very short captions (3-5 words)**:
```
Calculated: 3/3.5 + 1.5 = 2.4s
Enforced minimum: 3.0s
Final: 4.0s (base duration)
```
→ Even short text gets time for visual impact

**Maximum caption (14 words)**:
```
Calculated: 14/3.5 + 1.5 = 5.5s
Final: 5.5s
```
→ Enough time to read comfortably without feeling rushed
