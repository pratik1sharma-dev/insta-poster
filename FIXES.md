# Critical Fixes Implementation

## Fix 1: Gray Bars (80% Coverage Issue) - CRITICAL

### Root Cause
html2image doesn't properly fill viewport, leaving gray bars. Your templates use `100vw/100vh` but Chrome interprets this incorrectly.

### Solution
Add missing browser flags + force proper rendering size

**File:** `src/agents/image_generator.py`

**Line 50-57, replace with:**
```python
self.hti.browser.flags = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-gpu',
    '--hide-scrollbars',
    '--window-size=1080,1080',
    '--force-device-scale-factor=1',
    '--default-background-color=0',  # Prevent gray background
    '--disable-dev-shm-usage',       # Prevent memory issues
]
```

**Line 246-256, replace screenshot call with:**
```python
# Force exact size rendering
temp_name = f"temp_slide_{slide.slide_number}.png"

# Render with explicit size parameter
self.hti.screenshot(
    html_str=html_content,
    save_as=temp_name,
    size=(1080, 1080)  # Explicit size
)

temp_path = Path(temp_name)
if temp_path.exists():
    # Crop to exact 1080x1080 (remove any gray bars)
    img = Image.open(temp_path)
    if img.size != (1080, 1080):
        img = img.crop((0, 0, 1080, 1080))
        img.save(temp_path)

    temp_path.replace(image_path)
    image_paths.append(image_path)
else:
    raise FileNotFoundError("html2image failed to create the file.")
```

---

## Fix 2: Color Extraction (Structured Format)

### Current Problem
Line 59-80 uses string matching which fails with "not blue", structured JSON, etc.

### Solution
Force LLM to return structured colors, parse as dict

**File:** `src/agents/content_strategist.py`

**Find the strategy prompt (around line 162-187), update JSON format:**

```python
def _build_strategy_prompt(self, channel_config: ChannelConfig, topic: str) -> str:
    return f"""You are an Instagram content expert.
Create a clear and engaging strategy for a post about: "{topic}"

**Channel:** {channel_config.theme}
**Audience:** {channel_config.target_audience}

**Your Task:**
1. Decide on a unique angle for this topic.
2. Choose a hook to grab attention.
3. Define a visual theme/metaphor for the slides.
4. Choose a professional color palette.

**Output Format (JSON):**
{{
  "angle": "The core idea or perspective of the post.",
  "hook_type": "curiosity | controversy | relatability | value_proposition | question",
  "carousel_length": 5-8,
  "visual_metaphor": "The visual theme for the images.",
  "color_palette": {{
    "background": "#0f172a",
    "text": "#ffffff",
    "accent": "#3b82f6"
  }},
  "typography_style": "Bold sans-serif with strong hierarchy",
  "target_audience_insight": "Why the audience will care.",
  "reasoning": "Brief explanation of this strategy."
}}

**CRITICAL: color_palette MUST be a JSON object with background, text, and accent keys. Use HEX colors only.**

Respond with ONLY JSON.
"""
```

**File:** `src/agents/image_generator.py`

**Line 59-80, replace entire `_extract_primary_color` method:**

```python
def _extract_primary_color(self, color_palette: Union[str, dict]) -> str:
    """Extract background color from strategy (expects dict format)."""

    # If it's already a dictionary (correct format)
    if isinstance(color_palette, dict):
        bg = color_palette.get('background')
        if bg and bg.startswith('#'):
            return bg
        # Fallback keys
        return color_palette.get('primary', color_palette.get('bg', "#111827"))

    # Legacy string parsing (fallback)
    import re
    hex_match = re.search(r'#(?:[0-9a-fA-F]{3}){1,2}', str(color_palette))
    if hex_match:
        return hex_match.group(0)

    # Default
    logger.warning(f"Could not parse color_palette: {color_palette}, using default")
    return "#111827"  # Dark gray default
```

**Add helper method for text color:**

```python
def _extract_text_color(self, color_palette: Union[str, dict]) -> str:
    """Extract text color or calculate contrast."""

    if isinstance(color_palette, dict):
        text = color_palette.get('text')
        if text and text.startswith('#'):
            return text

    # Calculate from background
    bg_color = self._extract_primary_color(color_palette)
    return self._get_contrast_color(bg_color)
```

**Line 111, update to use new method:**

```python
bg_color = self._extract_primary_color(strategy.color_palette)
text_color = self._extract_text_color(strategy.color_palette)
```

---

## Fix 3: Template Selection Guidelines

### Current Problem
LLM doesn't know when to use which template, picks randomly.

### Solution
Add clear guidelines in content generation prompt

**File:** `src/agents/content_generator.py`

**Find `_generate_slides` method (around line 212), update prompt section:**

```python
prompt = f"""{master_brief}

**Slide Breakdown:**
- Slide 1: HOOK - Selection: AI image generation.
- Slides 2-{strategy.carousel_length - 1}: CONTENT - Deliver the core data and narrative.
- Slide {strategy.carousel_length}: CTA - Final action.

**Template Selection Rules (CRITICAL):**

For each slide, choose template_name based on content type:

1. **standard** - Use for: regular sentences, explanations, multi-line content
   - Max 100 characters
   - Example: "This is why compound interest beats trading"

2. **big_fact** - Use for: single big number or stat ONLY
   - Max 60 characters
   - Example: "₹2.5 Crore" or "78% of startups fail"
   - DO NOT use for sentences

3. **cta** - Use for: ONLY the final call-to-action slide
   - Max 80 characters
   - Example: "Save this for later" or "Follow for more insights"

4. **split_comparison** - DO NOT USE (not implemented yet)

**Background Style Rules:**

- "solid" - Default, use for most slides
- "gradient" - Use for 1-2 slides for visual variety
- "blurred_hook" - Use ONLY for slides 2-3 to create visual continuity from hook

**Text Length ENFORCEMENT:**
- Count characters before assigning template
- If text > max for template, either shorten text or use standard template
- Unreadable text = failed post

**Output Format (JSON):**
{{
  "slides": [
    {{
      "slide_number": 1,
      "purpose": "hook",
      "text_overlay": "Short punchy hook (max 80 chars)",
      "image_prompt": "Literal scene description",
      "template_name": "standard",
      "background_style": "solid"
    }},
    {{
      "slide_number": 2,
      "purpose": "content",
      "text_overlay": "First insight (max 100 chars if standard, 60 if big_fact)",
      "image_prompt": "Not used for templates",
      "template_name": "standard",
      "background_style": "blurred_hook"
    }}
  ]
}}

Respond with ONLY JSON.
"""
```

---

## Implementation Order

1. **Fix Gray Bars First** (15 min) - Most visible issue
2. **Fix Color Extraction** (20 min) - Prevents wrong colors
3. **Fix Template Selection** (10 min) - Better layout choices

Total: ~45 minutes

---

## Testing

After implementing:

```bash
# Generate 3 test posts
python src/main.py --channel pagecapsules --dry-run
python src/main.py --channel wealthcapsules --dry-run
python src/main.py --channel mindcapsules --dry-run

# Check output images
open output/pagecapsules/*/images/*.png
# Verify: No gray bars, correct colors, appropriate templates
```

---

## Expected Results

**Before:**
- 20-30% of images have gray bars
- Wrong colors occasionally
- Long text in small templates

**After:**
- 0% gray bars (cropped if needed)
- Correct colors (structured parsing)
- Proper template selection (with guidelines)
