# Cinematic Reel Generator - Improvement Plan

## Executive Summary

The cinematic reel generator has solid research infrastructure (Tavily integration, synthesis) but lacks enforcement and verification. Research data is gathered but not guaranteed to be used or validated in final output.

## Critical Issues

### 1. Research Data Usage Not Enforced
**File:** `src/agents/cinematic_reel_generator.py:559`

**Problem:** Research data is conditionally included - LLM can ignore it
```python
{f'### VERIFIED DATA (USE THESE FACTS): {strategy.verified_data}' if strategy.verified_data else ''}
```

**Impact:** Stories may contain fabricated statistics instead of researched facts

**Solution:** Make research mandatory, fail if unavailable

### 2. No Post-Generation Verification
**Files:** `src/agents/cinematic_reel_generator.py:676-738`

**Problem:** After generating story, no validation that:
- Numbers match verified_data
- Sources are preserved
- No made-up stats introduced

**Impact:** Generated line "Solar grew 50%" when research says "23%" - undetected

**Solution:** Add `_validate_data_usage()` method to cross-check all numbers

### 3. Weak Story Validation
**File:** `src/agents/cinematic_reel_generator.py:495-527`

**Current checks:**
- Abstract keywords (good)
- Presence of numbers (good)
- Word count (good)

**Missing checks:**
- Numbers match research data
- Sources preserved
- Data not misrepresented

**Solution:** Enhance validation to verify factual accuracy

### 4. Generic Fallback Without Research
**File:** `src/agents/cinematic_reel_generator.py:741-763`

**Problem:** When generation fails, uses generic phrases even when research exists
```python
fallback_lines = ["Let's talk about...", "Here's what most people don't know"]
```

**Solution:** Extract data points from research for intelligent fallback

## Implementation Tasks

### Priority 1: Enforce Research Requirement

**File:** `src/agents/cinematic_reel_generator.py`
**Method:** `_generate_script_and_prompts()`

Add at method start:
```python
# Enforce research requirement
if not strategy.verified_data or len(strategy.verified_data) < 100:
    raise ValueError(
        f"Cannot generate cinematic reel without research data. "
        f"Topic: {strategy.topic} - Enable Tavily API or provide manual data."
    )

# Extract numbers for later validation
import re
research_numbers = re.findall(
    r'[\d,\.]+(?:\s*(?:crore|lakh|million|billion|%|₹|\$))?',
    strategy.verified_data
)
```

After generation, validate:
```python
self._validate_data_usage(trimmed_lines, research_numbers, strategy.verified_data)
```

### Priority 2: Add Data Validation Method

**File:** `src/agents/cinematic_reel_generator.py`
**New Method:** `_validate_data_usage()`

```python
def _validate_data_usage(
    self,
    generated_lines: List[str],
    research_numbers: List[str],
    verified_data: str
) -> None:
    """
    Verify generated story uses ONLY researched facts.

    Raises ValueError if story contains unverified numbers.
    """
    import re

    # Extract all numbers from generated lines
    story_numbers = []
    for line in generated_lines:
        story_numbers.extend(
            re.findall(r'[\d,\.]+(?:\s*(?:crore|lakh|million|billion|%|₹|\$))?', line)
        )

    # Check each story number against research
    unverified = []
    for num in story_numbers:
        normalized = num.replace(',', '').strip()

        if not any(normalized in research.replace(',', '')
                   for research in research_numbers):
            unverified.append(num)

    if unverified:
        logger.error("=" * 60)
        logger.error("DATA INTEGRITY VIOLATION")
        logger.error("Unverified numbers: %s", unverified)
        logger.error("Research data:\n%s", verified_data)
        logger.error("=" * 60)

        raise ValueError(f"Story contains unverified data: {unverified}")
```

### Priority 3: Enhance Research Synthesis

**File:** `src/agents/content_strategist.py`
**Method:** `_synthesize_research()`

Improve prompt to enforce strict format:
```python
prompt = f"""You are a Research Analyst with focus on DATA INTEGRITY.

Topic: "{topic}"

RAW SEARCH DATA:
{raw_research}

### TASK:
Extract 5-8 VERIFIED DATA POINTS in STRICT FORMAT:

**Format per point:**
[SOURCE NAME]: [SPECIFIC FACT with NUMBER] (Year: YYYY)

### REQUIREMENTS:
1. Every data point MUST include:
   - Named source (McKinsey, World Bank, specific study)
   - Specific number (not "increased significantly")
   - Time reference (year, quarter)

2. Flag LOW CONFIDENCE data:
   - If source is "blog" or unnamed → prefix with ⚠️
   - If date is >2 years old → add "(DATED)"
   - If conflicting data → note both values

3. For COMPARISONS, ensure same timeframe

### GOOD EXAMPLE:
- [McKinsey 2024]: India's solar capacity reached 70.1 GW (Year: 2024)
- [NIFTY50 Index]: ₹1 lakh invested in 2010 → ₹8.7 crore by 2024

### BAD EXAMPLE:
- "Solar is growing fast" ❌ No number
- "One report said..." ❌ No source
- "In recent years" ❌ No year

Respond with ONLY formatted list starting with "VERIFIED DATA POINTS:"
"""
```

### Priority 4: Add Research Quality Scoring

**File:** `src/agents/content_strategist.py`
**New Method:** `_assess_research_quality()`

```python
def _assess_research_quality(self, research_data: str) -> dict:
    """
    Score research quality before using it.

    Returns:
        {
            'score': 0-100,
            'has_sources': bool,
            'has_numbers': bool,
            'has_dates': bool,
            'confidence': 'high|medium|low',
            'issues': [list]
        }
    """
    import re

    score = 0
    issues = []

    # Check named sources
    sources = re.findall(r'\[([A-Z][^\]]+)\]:', research_data)
    has_sources = len(sources) >= 3
    score += 30 if has_sources else 0
    if not has_sources:
        issues.append("Fewer than 3 named sources")

    # Check specific numbers
    numbers = re.findall(
        r'\d+(?:\.\d+)?(?:\s*(?:crore|lakh|million|billion|%|₹|\$))',
        research_data
    )
    has_numbers = len(numbers) >= 4
    score += 30 if has_numbers else 0
    if not has_numbers:
        issues.append("Fewer than 4 specific numbers")

    # Check dates
    dates = re.findall(r'(?:20\d{2}|Year:\s*\d{4})', research_data)
    has_dates = len(dates) >= 3
    score += 20 if has_dates else 0
    if not has_dates:
        issues.append("Missing time references")

    # Check quality warnings
    has_warnings = '⚠️' in research_data or '(DATED)' in research_data
    score += 20 if not has_warnings else 10
    if has_warnings:
        issues.append("Contains low-confidence data")

    confidence = 'high' if score >= 80 else ('medium' if score >= 50 else 'low')

    return {
        'score': score,
        'has_sources': has_sources,
        'has_numbers': has_numbers,
        'has_dates': has_dates,
        'confidence': confidence,
        'issues': issues
    }
```

Use in `plan_content()`:
```python
research_data = self._synthesize_research(raw_research, topic)
quality = self._assess_research_quality(research_data)

if quality['confidence'] == 'low':
    logger.warning("Research quality low (score: %d). Issues: %s",
                   quality['score'], quality['issues'])

    if quality['score'] < 30:
        raise ValueError(f"Research quality too low: {quality['issues']}")
```

### Priority 5: Smart Fallback with Research

**File:** `src/agents/cinematic_reel_generator.py`
**Method:** `_generate_script_and_prompts()` exception handler

```python
except Exception as e:
    logger.error("Script generation failed: %s", e)

    # Try research-based fallback
    if strategy.verified_data and len(strategy.verified_data) > 100:
        logger.warning("Using research-based fallback")

        import re
        data_points = re.findall(r'\[.+?\]:.+', strategy.verified_data)

        if len(data_points) >= num_images:
            fallback_lines = []
            for dp in data_points[:num_images]:
                # Convert "[Source]: Fact (Year: 2024)" → "Fact"
                clean = re.sub(r'\[.+?\]:\s*', '', dp)
                clean = re.sub(r'\(Year:.+?\)', '', clean).strip()
                words = clean.split()[:12]
                fallback_lines.append(' '.join(words))

            fallback_prompts = [
                f"Close-up of hands analyzing data, warm lighting, "
                f"contemplative mood, 35mm film grain, 9:16 portrait, NO text"
            ] * num_images

            logger.warning("Fallback from research data")
            return fallback_lines, fallback_prompts

    # Last resort: generic fallback
    logger.error("No research for fallback")
    # ... existing generic fallback
```

## Additional Enhancements

### 6. Visual Quality Control

**File:** `src/agents/cinematic_reel_generator.py`
**New Method:** `_validate_image_quality()`

Use vision model to verify:
- Visual anchor present
- Quality score (blur, composition)
- Style consistency
- Text/watermark detection

If quality < 70 or no visual anchor: regenerate

### 7. Hook Optimization

**New Method:** `_generate_hook_variants()`

Generate 5 hook variants:
1. Shocking statistic
2. Contrarian statement
3. Pattern interrupt question
4. Personal cost/benefit
5. Status quo challenge

Score on curiosity, relevance, emotional trigger

### 8. Dynamic Story Structures

Add multiple story formats:
- `contrast` (current default)
- `timeline` (historical progression)
- `myth_buster` (debunking)
- `case_study` (real example)

### 9. Advanced Text Animation

Replace basic drawtext with:
- Typewriter effect for hooks
- Fade+slide for content
- Scale+emphasis for numbers
- Word-by-word reveal

### 10. A/B Testing Framework

Generate 3 variants per reel:
- Different hooks
- Different visual styles
- Different music

Track performance for learning

## Implementation Order

### Week 1: Research Enforcement (Critical)
- [ ] Priority 1: Enforce research requirement
- [ ] Priority 2: Add data validation method
- [ ] Test with existing channels

### Week 2: Research Quality (High Impact)
- [ ] Priority 3: Enhance research synthesis
- [ ] Priority 4: Add quality scoring
- [ ] Priority 5: Smart fallback

### Week 3: Content Quality (Medium Impact)
- [ ] Visual quality control
- [ ] Hook optimization
- [ ] Dynamic story structures

### Week 4: Production Polish (Nice to Have)
- [ ] Advanced text animation
- [ ] A/B testing framework
- [ ] Performance analytics

## Success Metrics

### Before Implementation
- Research gathered but usage not verified
- Unknown if facts match sources
- Generic fallbacks on failure
- No quality scoring

### After Implementation
- Research mandatory, generation fails without it
- All numbers cross-checked against sources
- Intelligent fallbacks using research
- Quality scored 0-100 with issue detection
- Data integrity violations logged and prevented

## Testing Checklist

- [ ] Generate reel with good research data (should succeed)
- [ ] Generate reel without research data (should fail gracefully)
- [ ] Generate reel with weak research (should warn/fail)
- [ ] Verify numbers in output match research
- [ ] Test fallback with research data
- [ ] Test fallback without research data
- [ ] Check logs for data integrity violations

## Files to Modify

1. `src/agents/cinematic_reel_generator.py`
   - Add research enforcement
   - Add validation method
   - Improve fallback logic

2. `src/agents/content_strategist.py`
   - Enhance synthesis prompt
   - Add quality scoring
   - Add quality checks in plan_content()

3. Tests (create if missing)
   - Test research validation
   - Test fallback logic
   - Test quality scoring
