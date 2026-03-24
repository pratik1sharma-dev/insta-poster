# Cinematic Visual Storytelling Fix

## Current State: Static Visuals

**Problem**: Only slide 1 gets AI image, rest are HTML text on colored backgrounds.
**Result**: No visual story, just text slides.

## Root Cause: LLM Doesn't Know Cinematography

When the LLM writes `image_prompt`, it outputs:
```json
"image_prompt": "A smartphone showing a graph"
```

This lacks:
- Camera language (angle, framing, depth)
- Lighting mood (dramatic, soft, natural)
- Emotional tone (tense, hopeful, energetic)
- Composition principles (negative space, focal point)

## Solution: Cinematic Prompt Engineering

### 1. Add Cinematography Context to Image Prompts

Instead of:
```
"Create an image for: {slide.text_overlay}"
```

Use:
```
You are a cinematographer planning a shot for a visual story.

EMOTIONAL BEAT: {beat.emotional_goal}
NARRATIVE MOMENT: {beat.key_message}

SHOT SPECIFICATIONS:
- Camera: [Close-up | Medium | Wide | Extreme close-up]
- Angle: [Eye-level | Low angle | High angle | Dutch tilt]
- Lighting: [Dramatic contrast | Soft natural | Harsh | Backlit | Golden hour]
- Color Temperature: [Warm | Cool | Neutral]
- Mood: [Tense | Hopeful | Shocking | Calm | Urgent]

COMPOSITION RULES:
- Focal point placement: Rule of thirds
- Negative space: 40% of frame (center-left for text overlay)
- Depth: {Shallow | Deep} focus
- Leading lines: Guide eye to focal point

SCENE DESCRIPTION:
{visual_metaphor} - {specific_scene_detail}

Example Output:
"Extreme close-up of weathered hands holding a single seedling, shallow focus,
soft natural lighting from camera right, warm golden hour tones, rule of thirds
placement with seedling in right third, generous negative space in left two-thirds
for text overlay, blurred forest bokeh background, hopeful mood"
```

### 2. Visual Arc Planning

Add to StoryArchitect:

```python
class NarrativeBeat(BaseModel):
    # Existing fields...

    # NEW: Visual storytelling
    shot_type: str  # "close-up", "medium", "wide"
    lighting_mood: str  # "dramatic", "soft", "harsh"
    color_temperature: str  # "warm", "cool", "neutral"
    emotional_tone: str  # "tense", "hopeful", "shocking"
```

Plan visual progression:
```
Beat 1 (Hook): Extreme close-up, dramatic lighting, cool tones (SHOCK)
Beat 2 (Context): Medium shot, soft lighting, neutral tones (UNDERSTANDING)
Beat 3 (Development): Wide shot, natural lighting, warm tones (REALIZATION)
Beat 4 (Resolution): Close-up, golden hour, warm tones (AGENCY)
```

### 3. Enforce Visual Metaphor Consistency

Your strategy has `visual_metaphor` but it's ignored in execution.

Fix:
```python
def _build_cinematic_prompt(
    self,
    slide: CarouselSlide,
    beat: NarrativeBeat,
    strategy: ContentStrategy,
) -> str:
    """Build cinematically-aware image prompt."""

    return f"""VISUAL METAPHOR: {strategy.visual_metaphor}
This is the unifying object/scene across all slides.

CURRENT BEAT: #{beat.beat_number} - {beat.purpose}
EMOTIONAL GOAL: {beat.emotional_goal}

SHOT DESIGN:
- Type: {beat.shot_type}
- Lighting: {beat.lighting_mood}
- Temperature: {beat.color_temperature}
- Mood: {beat.emotional_tone}

COMPOSITION:
- Frame: 1080x1080 square
- Focal point: {self._get_focal_point_position(beat.beat_number)}
- Text space: Reserve {self._get_text_space(beat.purpose)}
- Negative space: Minimum 35% of frame

SCENE:
{slide.image_prompt}

FINAL CHECK:
- Does this shot support "{beat.key_message}"?
- Does it feel {beat.emotional_tone}?
- Is the visual metaphor present and clear?
- Is there space for text overlay?

Generate the shot now."""
```

## Implementation Priority

### CRITICAL (Do First):
1. **Add visual fields to NarrativeBeat model**
   ```python
   shot_type: str
   lighting_mood: str
   color_temperature: str
   ```

2. **Modify StoryArchitect to plan visual arc**
   Include cinematography in the outline generation

3. **Update image prompt builder with cinematic context**
   Feed beat visual specs into the prompt

### MEDIUM (Do Second):
4. **Generate AI images for more slides**
   Not just slide 1 - generate for beats 1, 3, 5, 7
   Use blurred/tinted versions for intermediate slides

5. **Visual consistency check**
   Validate that visual metaphor appears in all image prompts

### OPTIONAL (Polish):
6. **Lighting progression system**
   Auto-map emotional arc to lighting:
   - Shock → Harsh/Dramatic
   - Understanding → Soft/Natural
   - Resolution → Warm/Golden

7. **Composition templates**
   Pre-defined framing for each beat type:
   - Hook → Extreme close-up, off-center
   - Content → Medium shot, centered
   - CTA → Close-up portrait orientation

## Example: Before vs After

### BEFORE (Current):
```json
{
  "slide_number": 1,
  "image_prompt": "A smartphone with investment apps"
}
```

**LLM generates**: Generic stock photo vibes

### AFTER (Cinematic):
```json
{
  "slide_number": 1,
  "purpose": "hook",
  "emotional_goal": "Shock reader with unexpected truth",
  "shot_type": "extreme_close_up",
  "lighting_mood": "dramatic_contrast",
  "color_temperature": "cool",
  "emotional_tone": "tense",
  "image_prompt": "Extreme close-up of cracked smartphone screen showing a red
    declining graph, dramatic side lighting creating harsh shadows, cool blue tones,
    shallow focus with background fully blurred, rule of thirds placement with crack
    lines leading to graph in right third, generous negative space in left two-thirds,
    tense and urgent mood"
}
```

**LLM generates**: Cinematic, emotionally-directed image

## Testing the Fix

### Test 1: Visual Metaphor Consistency
Run a carousel. Check: Does the visual metaphor appear in slide 1's image?

### Test 2: Emotional Alignment
Does slide 1 (shock) LOOK shocking? Does resolution slide LOOK resolved?

### Test 3: Text Overlay Space
Are all images leaving proper negative space for text?

## ROI of This Fix

**Narrative Quality**: ⭐⭐⭐⭐⭐
Visuals now SUPPORT the story instead of being decoration

**Scroll-Stopping Power**: ⭐⭐⭐⭐⭐
Cinematic images perform 3-5x better than stock-looking ones

**Brand Consistency**: ⭐⭐⭐⭐⭐
Visual metaphor creates memorable aesthetic

**Generation Cost**: ⭐⭐⭐☆☆
More detailed prompts = better first-try success = fewer regenerations
