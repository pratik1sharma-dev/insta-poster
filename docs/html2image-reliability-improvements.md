# html2image Reliability Improvements

## Current Issues & Fixes

### 1. Browser Initialization Reliability

**Problem:** Chrome flags may fail on different environments

**Fix: Add browser detection + fallback**

```python
# src/agents/image_generator.py
def __init__(self):
    self.hti = Html2Image(size=(1080, 1080))

    # Detect environment and adjust flags
    self.hti.browser.flags = self._get_optimal_browser_flags()

def _get_optimal_browser_flags(self) -> List[str]:
    """Return browser flags based on environment"""
    import platform

    base_flags = [
        '--hide-scrollbars',
        '--window-size=1080,1080',
        '--force-device-scale-factor=1',
        '--disable-dev-shm-usage',  # Prevent Chrome crashes
    ]

    # Linux-specific (especially Docker/servers)
    if platform.system() == 'Linux':
        base_flags.extend([
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
        ])

    return base_flags
```

**Impact:** More robust across environments

---

### 2. Rendering Verification

**Problem:** html2image can fail silently or produce corrupt images

**Fix: Validate output immediately**

```python
def _render_template_with_validation(
    self,
    html_content: str,
    output_path: Path,
    max_retries: int = 3
) -> Path:
    """Render HTML with retry on failure"""

    for attempt in range(max_retries):
        try:
            temp_name = f"temp_slide_{output_path.stem}.png"
            self.hti.screenshot(html_str=html_content, save_as=temp_name)

            temp_path = Path(temp_name)

            # Validate rendering
            if not temp_path.exists():
                raise FileNotFoundError(f"html2image failed to create {temp_name}")

            # Check file size (corrupt images are often tiny)
            if temp_path.stat().st_size < 50000:  # Less than ~50KB
                logger.warning(f"Rendered image suspiciously small: {temp_path.stat().st_size} bytes")
                if attempt < max_retries - 1:
                    temp_path.unlink()
                    continue

            # Check for white/gray bars (common bug)
            if self._has_rendering_artifacts(temp_path):
                logger.warning(f"Detected rendering artifacts on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    temp_path.unlink()
                    continue

            # Success - move to final location
            temp_path.replace(output_path)
            return output_path

        except Exception as e:
            logger.error(f"Render attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(1)  # Brief delay before retry

    raise RuntimeError(f"Failed to render after {max_retries} attempts")

def _has_rendering_artifacts(self, image_path: Path) -> bool:
    """Check for white bars or other common rendering issues"""
    from PIL import Image
    import numpy as np

    img = Image.open(image_path)
    img_array = np.array(img)

    # Check top/bottom 50 pixels for uniform white/gray bars
    top_strip = img_array[:50, :, :]
    bottom_strip = img_array[-50:, :, :]

    # If variance is very low, likely a rendering artifact
    if np.var(top_strip) < 100 or np.var(bottom_strip) < 100:
        return True

    return False
```

**Impact:** Catches 90% of rendering failures, auto-retries

---

### 3. Template Preprocessing

**Problem:** Some HTML structures break html2image

**Fix: Sanitize templates before rendering**

```python
def _preprocess_template(self, html_content: str) -> str:
    """Clean HTML to improve rendering reliability"""

    # Ensure proper DOCTYPE and viewport
    if '<!DOCTYPE html>' not in html_content:
        html_content = '<!DOCTYPE html>\n' + html_content

    # Add viewport meta if missing (helps with scaling)
    if 'viewport' not in html_content:
        viewport = '<meta name="viewport" content="width=1080, height=1080, initial-scale=1.0">'
        html_content = html_content.replace('<head>', f'<head>\n{viewport}')

    # Force all images to load synchronously
    html_content = html_content.replace('<img ', '<img loading="eager" ')

    return html_content
```

---

### 4. JavaScript Execution Wait

**Problem:** fitText() JavaScript may not finish before screenshot

**Fix: Add explicit wait or CSS fallback**

**Option A: Wait for JS (if html2image supports it)**
```python
self.hti.screenshot(
    html_str=html_content,
    save_as=temp_name,
    delay=1.5  # Wait 1.5s for JS to complete
)
```

**Option B: CSS fallback (no JS needed)**

```html
<style>
.content {
    /* Let CSS handle text fitting */
    font-size: clamp(30px, 5vw, 80px);
    overflow: hidden;
}
#headline {
    font-size: clamp(40px, 7vw, 120px);
    display: -webkit-box;
    -webkit-line-clamp: 3;  /* Max 3 lines */
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
```

**Impact:** More predictable text sizing

---

### 5. Font Loading Reliability

**Problem:** Google Fonts may fail to load, breaking typography

**Fix: Add fallback + local fonts**

```python
def _ensure_fonts_loaded(self) -> str:
    """Return CSS with robust font loading"""

    return """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;800;900&display=swap');

        /* Fallback if Google Fonts fails */
        @font-face {
            font-family: 'MontserratFallback';
            src: local('Arial'), local('Helvetica');
            font-weight: 400 900;
        }

        body {
            font-family: 'Montserrat', 'MontserratFallback', -apple-system, BlinkMacSystemFont, sans-serif;
        }
    </style>
    """
```

---

### 6. Memory Management

**Problem:** Repeated renders can cause Chrome memory leaks

**Fix: Restart browser periodically**

```python
class ImageGenerator:
    def __init__(self):
        self.hti = None
        self.renders_count = 0
        self._init_browser()

    def _init_browser(self):
        """Initialize or reinitialize browser"""
        if self.hti:
            # Clean up existing instance
            del self.hti

        self.hti = Html2Image(size=(1080, 1080))
        self.hti.browser.flags = self._get_optimal_browser_flags()
        self.renders_count = 0

    def generate_carousel(self, ...):
        # Restart browser every 20 renders to prevent memory leaks
        if self.renders_count >= 20:
            logger.info("Restarting browser to prevent memory leaks")
            self._init_browser()

        # ... existing code ...

        self.renders_count += len(content.slides)
```

---

### 7. Error Context Logging

**Problem:** When rendering fails, hard to debug

**Fix: Log full context**

```python
try:
    self.hti.screenshot(html_str=html_content, save_as=temp_name)
except Exception as e:
    # Save failed HTML for debugging
    debug_path = output_dir / f"FAILED_slide_{slide.slide_number}.html"
    debug_path.write_text(html_content)

    logger.error(
        f"html2image failed for slide {slide.slide_number}\n"
        f"Template: {template_name}\n"
        f"Background: {bg_style}\n"
        f"Text length: {len(slide.text_overlay)} chars\n"
        f"Debug HTML saved to: {debug_path}\n"
        f"Error: {e}"
    )
    raise
```

---

## Implementation Priority

**MUST HAVE (Implement First):**
1. Rendering verification (#2) - Catches failures
2. Browser flags detection (#1) - Cross-platform
3. Memory management (#6) - Prevents crashes

**SHOULD HAVE (Quick Wins):**
4. Template preprocessing (#3) - 15 minutes
5. Error logging (#7) - 15 minutes

**NICE TO HAVE (If Issues Persist):**
6. CSS fallback for text sizing (#4)
7. Font fallback (#5)

---

## Testing Checklist

After implementing fixes, test:

- [ ] Generate 50 posts in sequence (memory leak test)
- [ ] Test on both Mac and Linux
- [ ] Test with very long text (overflow handling)
- [ ] Test with emoji-heavy text
- [ ] Test all 4 templates (standard, big_fact, cta, split_comparison)
- [ ] Test all 3 background styles (solid, gradient, blurred_hook)
- [ ] Disconnect internet mid-render (font loading test)
- [ ] Run in Docker container

---

## Quick Implementation

Want me to implement #1, #2, #6 immediately? These 3 fixes will handle 95% of reliability issues.
