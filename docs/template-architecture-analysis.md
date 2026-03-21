# Template Architecture Analysis (dev-content-refactoring branch)

## Current Hybrid Approach ✅

**Slide 1:** AI-generated (Ideogram/Gemini) with text-in-image
**Slides 2+:** HTML/CSS templates rendered via html2image + Jinja2

---

## Template System Components

### Templates Available:
1. **standard.html** - Glassmorphism card, centered text, handles `---` separator for headline/body
2. **big_fact.html** - Larger headline (120px), bold numbers, radial dot pattern overlay
3. **cta.html** - Call-to-action box with border, "Save this post" button
4. **split_comparison.html** - (exists but not reviewed yet)
5. **slide.html** - Generic fallback

### Background Styles:
- `solid` - Pure color background
- `gradient` - CSS gradients
- `blurred_hook` - Slide 1 image blurred + darkened (lines 220-234)

### Dynamic Features:
- **Auto-sizing text** (JavaScript fitText function)
- **Color extraction** from strategy.color_palette (lines 59-80)
- **Contrast calculation** for text color (lines 82-95)
- **Emoji support** (fallback fonts included)
- **Brand watermarks** (channel name + handle)

---

## Strengths of Current Implementation

✅ **Perfect typography** - No AI text rendering issues on slides 2+
✅ **Visual consistency** - Same glassmorphism style across templates
✅ **Fast rendering** - html2image faster than image generation
✅ **Cost efficient** - Only 1 AI image per post vs 5-8
✅ **Flexible** - Easy to add new templates
✅ **Responsive text** - JavaScript auto-scales if content too long
✅ **Blurred hook background** - Creates visual continuity from slide 1

---

## Weaknesses & Risks

### 1. html2image Dependency 🔴
**Lines 46-57:** Browser flags for headless Chrome
- `--no-sandbox` (security risk if user input in templates)
- `--disable-setuid-sandbox` (Linux root requirement)
- Requires Chrome/Chromium installed on system
- Can fail silently on some environments

**Risk:** Brittle in production, especially containerized deployments

---

### 2. Template Selection Logic ⚠️
**Lines 198-199:**
```python
template_name = slide.template_name if slide.template_name else "standard"
```

**Problem:** Who decides template_name?

Checking content_generator.py to see if LLM selects templates...

---

### 3. Text Overflow Handling ⚠️
**JavaScript lines 98-115 (standard.html):**
```javascript
while ((container.scrollHeight > container.offsetHeight) && iterations < 100) {
    if (hSize > 30) hSize -= 2;
    if (bodyText && bSize > 20) bSize -= 1;
    ...
}
```

**Issue:** After 100 iterations or hitting minimum size (30px/20px), text may still overflow

**Missing:** Truncation or word wrapping fallback

---

### 4. Color Extraction Fragility ⚠️
**Lines 59-80:** Parsing color_palette string/dict

```python
if "blue" in palette_str:
    return "#0f172a"
```

**Problem:** LLM might say "navy blue" (matches "blue"), "blue-ish" (matches), "not blue" (matches!)

**Better approach:** Ask LLM for structured color output in strategy phase

---

### 5. No Template Preview/Validation ❌

Currently no way to:
- Preview templates before posting
- Validate rendered output quality
- Check if text fits before rendering
- A/B test template variants

---

### 6. Hardcoded Brand Elements 🔴
**Lines 69-77 (all templates):**
```html
<div class="brand">{{ channel_name }}</div>
<div class="handle">@{{ channel_name|lower|replace(' ', '') }}</div>
```

**Issues:**
- Handle generation is naive (removes spaces only)
- No option to disable branding
- Position hardcoded (top-right, bottom-left)
- Can overlap with long text

---

## Recommendations for Template Robustness

### HIGH PRIORITY

**1. Template Selection Intelligence**
Ask LLM to choose template per slide in content_generator.py:

```python
# In slide generation prompt:
"For each slide, specify:
- template_name: standard | big_fact | cta | split_comparison
- background_style: solid | gradient | blurred_hook"
```

Currently: `template_name = "standard"` (line 198 - always default?)

---

**2. Better Text Overflow**
```python
# Before rendering, estimate character limits per template
MAX_CHARS = {
    "standard": 120,
    "big_fact": 80,
    "cta": 100
}

# In content generation prompt:
f"Slide {N} text must be under {MAX_CHARS[template_name]} characters"
```

---

**3. Replace html2image**
**Why:** Fragile Chrome dependency

**Option A:** Pillow + ImageDraw (pure Python)
```python
from PIL import Image, ImageDraw, ImageFont

def render_template_with_pillow(bg_color, text, font_size):
    img = Image.new('RGB', (1080, 1080), color=bg_color)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("Montserrat-Bold.ttf", font_size)
    draw.text((540, 540), text, font=font, anchor="mm")
    return img
```

**Pros:** No browser needed, faster, more reliable
**Cons:** No CSS, manual layout, no glassmorphism effects

**Option B:** Playwright (better than html2image)
- More reliable screenshots
- Better error handling
- Active maintenance

---

**4. Structured Color Output**
Modify strategy prompt (content_strategist.py):

```python
"color_palette": {
    "background": "#0f172a",
    "text": "#ffffff",
    "accent": "#3b82f6"
}
```

Remove heuristic parsing entirely.

---

### MEDIUM PRIORITY

**5. Template Validation Layer**
```python
class TemplateValidator:
    def validate_render(self, image_path: Path) -> bool:
        """Check if rendered image has issues"""
        img = Image.open(image_path)

        # Check for white bars (common html2image bug)
        if self._has_whitespace_borders(img):
            return False

        # Check if mostly blank
        if self._is_mostly_uniform_color(img):
            return False

        return True
```

---

**6. Template Preview System**
```python
# In dry-run mode, generate HTML preview files
if dry_run:
    for slide in slides:
        html_path = output_dir / f"preview_slide_{slide.slide_number}.html"
        html_path.write_text(rendered_html)

    print(f"Preview slides in browser: file://{output_dir}/preview_slide_01.html")
```

---

**7. Dynamic Brand Configuration**
Move to channel config:

```yaml
pagecapsules:
  branding:
    show_brand: true
    brand_position: "top-right"
    show_handle: true
    handle_position: "bottom-left"
    handle_format: "@{name}"  # or custom
```

---

### LOW PRIORITY (Nice-to-Have)

**8. Template Analytics**
Track which templates perform best:

```python
class TemplatePerformance:
    def log_template_usage(post_id, slides):
        for slide in slides:
            db.insert({
                'post_id': post_id,
                'slide_num': slide.slide_number,
                'template': slide.template_name,
                'bg_style': slide.background_style
            })

    def get_best_template_for_purpose(purpose: SlidePurpose):
        # Query posts with high engagement
        # Return most-used template for that purpose
```

---

**9. Template Variants (A/B Testing)**
```python
templates = {
    "standard_v1": "standard.html",
    "standard_v2": "standard_bold.html",
    "standard_v3": "standard_minimal.html"
}

# Randomly select variant
variant = random.choice(["v1", "v2", "v3"])
template_name = f"standard_{variant}"
```

---

## Critical Questions for You

**Q1: Template Selection**
Currently defaults to "standard" for all slides 2+. Should:
- A) LLM choose template per slide based on content?
- B) Predefined mapping (hook→standard, fact→big_fact, cta→cta)?
- C) Keep as-is (all standard)?

**Q2: html2image Reliability**
Have you encountered rendering issues? Should we:
- A) Keep html2image (works well enough)?
- B) Switch to Pillow (more reliable, less fancy)?
- C) Switch to Playwright (most robust)?

**Q3: Color Palette**
LLM currently returns freeform text like "Deep blue with gold accents". Should we:
- A) Force structured JSON color output?
- B) Keep heuristic parsing with improvements?

**Q4: Text Overflow**
What should happen if text doesn't fit?
- A) Truncate with "..." ?
- B) Reject slide and regenerate?
- C) Accept small/unreadable text?

---

## Next Steps

1. You answer Q1-Q4 above
2. I'll update discussion plan with template-specific improvements
3. We prioritize template robustness fixes
4. Generate implementation plan

**Your turn:** Which questions should we address first?
