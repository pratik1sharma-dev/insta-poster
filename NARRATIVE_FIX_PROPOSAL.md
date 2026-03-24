# Narrative Quality Fix - Two-Phase Story Generation

## Current Problem

Slides are generated in one shot without narrative planning, resulting in:
- Incoherent progression
- Random fact listing instead of storytelling
- Lost thread by slide 4-5
- No clear resolution or payoff

## Solution Architecture

### Phase 1: Story Outline (NEW)
**Goal**: Plan the narrative arc BEFORE writing slides

**Input**:
- Strategy (topic, angle, verified data)
- Channel config (audience, tone)

**Output**:
```json
{
  "story_spine": "The one-sentence story this carousel tells",
  "narrative_beats": [
    {
      "beat_number": 1,
      "purpose": "hook",
      "emotional_goal": "Shock the reader with unexpected truth",
      "key_message": "Everyone believes X, but the data shows Y",
      "data_to_use": ["Verified data point #2", "Verified data point #5"],
      "transition_to_next": "This raises the question: why?"
    },
    {
      "beat_number": 2,
      "purpose": "context",
      "emotional_goal": "Build understanding",
      "key_message": "Here's the hidden mechanism causing this",
      "data_to_use": ["Verified data point #1"],
      "transition_to_next": "But here's where it gets interesting..."
    },
    // ... more beats
  ],
  "throughline": "Each slide answers the question raised by the previous one"
}
```

### Phase 2: Slide Execution (IMPROVED)
**Goal**: Write ONE slide at a time, following the outline

**Process**:
```python
for beat in story_outline.narrative_beats:
    slide = generate_slide_for_beat(
        beat=beat,
        previous_slides=slides_generated_so_far,  # Context
        remaining_beats=beats_after_this_one,      # Foreshadowing
        verified_data=strategy.verified_data
    )
    slides.append(slide)
```

## Implementation Changes

### 1. Add Story Outliner Method

```python
# content_generator.py

def _generate_story_outline(
    self,
    strategy: ContentStrategy,
    channel_config: ChannelConfig,
    system_prompt: str,
    master_brief: str,
    raw_output_dir: Optional[Path],
) -> StoryOutline:
    """
    Generate narrative structure BEFORE writing slides.

    This ensures:
    - Each slide builds on previous one
    - Clear emotional progression
    - Verified data is used strategically (not randomly)
    - Story has a clear resolution
    """

    prompt = f"""{master_brief}

### YOUR TASK:
You are the Story Architect. Plan the narrative structure for this carousel.

**Story Requirements:**
1. One clear throughline - what's the ONE realization this carousel delivers?
2. Each beat must logically lead to the next
3. Build tension → Provide insight → Resolve with action
4. Use verified data strategically (not as random facts)

**Narrative Beats to Plan:**
- Beat 1 (Hook): What unexpected truth grabs attention?
- Beats 2-3 (Context): Why does this matter? What's the mechanism?
- Beats 4-{strategy.carousel_length - 2} (Development): What are the implications?
- Beat {strategy.carousel_length - 1} (Resolution): What can the reader do?
- Beat {strategy.carousel_length} (CTA): What question makes them engage?

**Output Format (JSON):**
{{
  "story_spine": "One sentence explaining the story arc",
  "throughline": "How each slide connects to the next",
  "narrative_beats": [
    {{
      "beat_number": 1,
      "purpose": "hook",
      "emotional_goal": "Surprise with counter-intuitive fact",
      "key_message": "The specific insight this beat delivers",
      "data_to_use": ["Exactly which verified data points support this beat"],
      "transition_to_next": "The question or tension that leads to the next beat"
    }},
    // ... more beats
  ]
}}

**Critical Rules:**
- Every beat must advance the story (no random tangents)
- Data points must be distributed strategically (not all dumped in one slide)
- The progression must feel inevitable, not arbitrary
- The resolution must feel earned, not tacked on

Generate the story outline now.
"""

    response_text = self._generate_text(prompt, system_prompt=system_prompt)
    self._save_debug_file(raw_output_dir, "story_outline.json", response_text)

    return self._parse_story_outline(response_text, strategy)
```

### 2. Modify generate_content Method

```python
def generate_content(
    self,
    strategy: ContentStrategy,
    channel_config: ChannelConfig,
    raw_output_dir: Optional[Path] = None,
) -> GeneratedContent:
    """Generate all text content for a post with story-first approach."""

    system_prompt = self._build_generator_system_prompt(channel_config)
    master_brief = self._build_master_brief(strategy, channel_config)

    # PHASE 1: Generate story outline (NEW)
    story_outline = self._generate_story_outline(
        strategy, channel_config, system_prompt, master_brief, raw_output_dir
    )

    # Log the story spine for debugging
    logger.info("Story spine: %s", story_outline.story_spine)

    # PHASE 2: Generate slides following the outline
    slides = self._generate_slides_from_outline(
        story_outline, strategy, channel_config,
        system_prompt, master_brief, raw_output_dir
    )

    # Rest remains same
    caption = self._generate_caption(...)
    hashtags = self._generate_hashtags(...)
    cta = self._generate_smart_cta(...)

    return GeneratedContent(
        caption=caption,
        hashtags=hashtags,
        call_to_action=cta,
        slides=slides,
    )
```

### 3. New Slide Generation (Iterative)

```python
def _generate_slides_from_outline(
    self,
    story_outline: StoryOutline,
    strategy: ContentStrategy,
    channel_config: ChannelConfig,
    system_prompt: str,
    master_brief: str,
    raw_output_dir: Optional[Path],
) -> List[CarouselSlide]:
    """Generate slides ONE AT A TIME following story outline."""

    slides = []

    for beat in story_outline.narrative_beats:
        # Build context from previous slides
        previous_context = ""
        if slides:
            previous_context = "\n".join([
                f"Slide {s.slide_number}: {s.headline} - {s.subtext}"
                for s in slides[-2:]  # Last 2 slides for context
            ])

        # Generate this specific slide
        prompt = f"""{master_brief}

### STORY CONTEXT:
Story Spine: {story_outline.story_spine}
Throughline: {story_outline.throughline}

### PREVIOUS SLIDES:
{previous_context if previous_context else "This is the first slide"}

### THIS BEAT:
Beat #{beat.beat_number} - {beat.purpose}
Emotional Goal: {beat.emotional_goal}
Key Message: {beat.key_message}
Data to Use: {', '.join(beat.data_to_use)}
Transition to Next: {beat.transition_to_next}

### YOUR TASK:
Write ONLY slide {beat.beat_number} following this beat's requirements.

{_SLIDE_FORMAT_GUIDE}

**Requirements:**
1. Deliver the key message: "{beat.key_message}"
2. Achieve the emotional goal: {beat.emotional_goal}
3. Use these data points naturally: {beat.data_to_use}
4. End with this transition: "{beat.transition_to_next}"
5. Build on the previous slides (don't repeat information)

**Output Format (JSON):**
{{
  "slide_number": {beat.beat_number},
  "purpose": "{beat.purpose}",
  "template_name": "standard | big_fact | split_comparison | cta",
  "background_style": "solid | gradient | blurred_hook",
  "headline": "...",
  "subtext": "...",
  "text_overlay": "...",
  "image_prompt": "...",
  // ... other fields based on template
}}

Write ONLY the JSON for slide {beat.beat_number}.
"""

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        self._save_debug_file(
            raw_output_dir,
            f"slide_{beat.beat_number}_raw.txt",
            response_text
        )

        slide_data = self._parse_json_response(response_text)
        slide = self._parse_single_slide(slide_data, beat.beat_number)
        slides.append(slide)

        logger.info("Generated slide %d: %s", beat.beat_number, slide.headline)

    return slides
```

## Benefits of This Approach

### ✅ Coherent Story
- Outline forces the LLM to plan the entire arc upfront
- Each slide knows its role in the larger story

### ✅ Better Data Usage
- Data points assigned strategically to specific beats
- No random fact dumping

### ✅ Iterative Refinement
- Each slide builds on previous ones
- LLM has context of where story is going

### ✅ Validation Opportunity
```python
# You can validate the outline before generating slides
def validate_story_outline(outline: StoryOutline) -> bool:
    # Check for narrative progression
    # Verify data distribution
    # Ensure clear resolution
    # Return True if story makes sense
```

### ✅ Easier Debugging
When a carousel fails, you can see exactly where:
- Is the outline bad? (Poor story planning)
- Is a specific slide bad? (Execution issue)

## Testing the Fix

### Before (Current):
```
Strategy → All 6 slides in one shot → Often incoherent
```

### After (Proposed):
```
Strategy → Story Outline → Validate Outline → Generate Slide 1 → Slide 2 → ... → Slide 6
              ↓                                    ↓           ↓          ↓
           Check story             Context from   Context     Context
           makes sense             previous       from 1      from 1-2
```

## Migration Path

1. Add `StoryOutline` model to `content_models.py`
2. Implement `_generate_story_outline()` method
3. Implement `_generate_slides_from_outline()` method
4. Add `--use-story-mode` flag to test alongside old approach
5. Compare outputs and migrate when satisfied

## Expected Improvements

**Narrative Coherence**: ⭐⭐⭐⭐⭐
- Clear throughline
- Each slide builds on previous
- Satisfying resolution

**Data Usage**: ⭐⭐⭐⭐⭐
- Strategic distribution
- Facts support story (not interrupt it)

**Emotional Impact**: ⭐⭐⭐⭐⭐
- Planned emotional journey
- Proper tension and release

**Generation Time**: ⭐⭐⭐☆☆
- Slower (multiple LLM calls)
- But output quality justifies it

## Quick Win Alternative

If full two-phase is too much, try this simpler fix:

**Chain-of-Slides Prompting**:
```python
# Generate slides 1-2 together (hook + context)
# Then generate 3-5 with context of 1-2
# Then generate 6+ with context of 1-5
```

This gives some narrative awareness without full outlining.
