"""
Comprehensive tests for VideoComposer text escaping and drawtext filter generation.

Tests three layers:
  1. _escape()                   — string transformation correctness
  2. _create_kinetic_text_overlay() — full filter string structure and style behaviour
  3. FFmpeg drawtext rendering   — actual video frame rendered on server (needs libfreetype)

Run:
    source venv/bin/activate
    python tests/test_video_composer_escape.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Import VideoComposer
# ─────────────────────────────────────────────────────────────────────────────

from src.agents.video_composer import VideoComposer

vc = VideoComposer()

# Convenience wrappers
def escape(s: str) -> str:
    return vc._escape(s)

def is_punchline(s: str) -> bool:
    return vc._is_punchline_number(s)

def overlay(text: str, style: str, duration: float = 5.0) -> str:
    return vc._create_kinetic_text_overlay(text, style, duration)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PASSED = []
FAILED = []

def run(fn):
    label = fn.__name__
    print(f"\n[{label}]")
    try:
        fn()
        PASSED.append(label)
    except AssertionError as e:
        print(f"  FAIL: {e}")
        FAILED.append(label)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        FAILED.append(label)

def check(condition, msg):
    assert condition, msg


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: _escape()
# ─────────────────────────────────────────────────────────────────────────────

def test_escape_apostrophe_replaced_with_unicode():
    """ASCII apostrophe must become U+2019, never appear raw in output."""
    inputs = ["don't", "it's", "you're", "others'"]
    for s in inputs:
        out = escape(s)
        check("'" not in out, f"ASCII apostrophe still present in {out!r} (from {s!r})")
        check('\u2019' in out, f"U+2019 not found in {out!r} (from {s!r})")
        print(f"  PASS: {s!r} → {out!r}")


def test_escape_left_single_quote_replaced():
    """Unicode left single quote U+2018 must also become U+2019."""
    out = escape('\u2018hello\u2019')
    check('\u2018' not in out, f"U+2018 still present: {out!r}")
    check("'" not in out, f"ASCII apostrophe in output: {out!r}")
    print(f"  PASS: U+2018/U+2019 → {out!r}")


def test_escape_percent_doubled():
    """Percent must be doubled for drawtext text expansion."""
    inputs = ["75%", "60% done", "100% sure", "0%"]
    for s in inputs:
        out = escape(s)
        check('%%' in out, f"Expected %% in {out!r} (from {s!r})")
        check('\\x25' not in out, f"\\x25 must not appear: {out!r}")
        print(f"  PASS: {s!r} → {out!r}")


def test_escape_no_xhh_sequences():
    """\\xHH hex escapes are NOT supported by FFmpeg — must never appear."""
    inputs = ["don't", "75%", "it's 100%", "you're losing 40%"]
    for s in inputs:
        out = escape(s)
        check('\\x' not in out, f"\\xHH found in {out!r} (from {s!r})")
        print(f"  PASS: {s!r} → {out!r} (no \\xHH)")


def test_escape_colon_escaped():
    out = escape("10:30 AM")
    check('\\:' in out, f"Colon not escaped: {out!r}")
    check(out.count(':') == out.count('\\:'), f"Unescaped colon in {out!r}")
    print(f"  PASS: {out!r}")


def test_escape_backslash_doubled():
    out = escape("C:\\path\\file")
    check('\\\\' in out, f"Backslash not doubled: {out!r}")
    print(f"  PASS: {out!r}")


def test_escape_em_dash_converted():
    out = escape("work\u2014life")
    check('\u2014' not in out, f"Em dash still present: {out!r}")
    check(' - ' in out, f"Em dash not converted: {out!r}")
    print(f"  PASS: {out!r}")


def test_escape_en_dash_converted():
    out = escape("10\u201320")
    check('\u2013' not in out, f"En dash still present: {out!r}")
    check('-' in out, f"En dash not converted: {out!r}")
    print(f"  PASS: {out!r}")


def test_escape_ellipsis_converted():
    out = escape("wait\u2026")
    check('\u2026' not in out, f"Ellipsis still present: {out!r}")
    check('...' in out, f"Ellipsis not converted: {out!r}")
    print(f"  PASS: {out!r}")


def test_escape_combined_problematic():
    """The exact texts that were broken in production."""
    cases = [
        ("Overanalyzing costs you 75% of good decisions", {"%%"}),
        ("distracted folks get 60%", {"%%"}),
        ("don't follow others' agendas", {'\u2019'}),
        ("you're losing 40% of your focus", {'\u2019', '%%'}),
        ("it's costing you 75%", {'\u2019', '%%'}),
    ]
    for text, expected_markers in cases:
        out = escape(text)
        check("'" not in out, f"ASCII apostrophe in {out!r}")
        check('\\x' not in out, f"\\xHH in {out!r}")
        for marker in expected_markers:
            check(marker in out, f"Expected {marker!r} in {out!r} (from {text!r})")
        print(f"  PASS: {text!r} → {out!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: _is_punchline_number()
# ─────────────────────────────────────────────────────────────────────────────

def test_punchline_percent_lines_detected():
    """Every line containing digits+% must trigger 'number' style."""
    should_match = [
        "75% of good decisions",
        "folks get 60%",
        "you lose 40% focus",
        "only 5% succeed",
        "₹10,000 invested",
        "costs 1 lakh",
        "earned 2 crore",
        "100000 users",
    ]
    for line in should_match:
        check(is_punchline(line), f"Expected punchline match for: {line!r}")
        print(f"  PASS: {line!r} → 'number' style")


def test_punchline_plain_lines_not_detected():
    """Lines without stats must NOT trigger 'number' style."""
    should_not_match = [
        "Overanalyzing costs you",
        "decisions - distracted",
        "don't overthink",
        "your time is precious",
        "stop and breathe",
        "the real cost is focus",
    ]
    for line in should_not_match:
        check(not is_punchline(line), f"Unexpected punchline match for: {line!r}")
        print(f"  PASS: {line!r} → other style (correct)")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3: _create_kinetic_text_overlay() filter string validation
# ─────────────────────────────────────────────────────────────────────────────

def _extract_text_values(filter_str: str) -> list:
    """Pull out every text='...' value from a drawtext filter string."""
    return re.findall(r"text='([^']*)'", filter_str)


def _extract_fontsize_values(filter_str: str) -> list:
    """Pull out every fontsize=... value from a drawtext filter string."""
    return re.findall(r"fontsize=([^\s:,]+)", filter_str)


def test_overlay_no_ascii_apostrophe_in_filter():
    """ASCII apostrophe in input must never reach the FFmpeg filter string."""
    texts = ["don't stop", "it's fine", "you're right"]
    for style in ('hook', 'main', 'insight'):
        for text in texts:
            f = overlay(text, style)
            # The text='...' value must not contain ASCII apostrophe
            # (it would close the quoted segment early)
            for val in _extract_text_values(f):
                check("'" not in val,
                      f"ASCII apostrophe in text value {val!r} (style={style}, input={text!r})")
            print(f"  PASS: style={style} {text!r} — no ASCII apostrophe in filter")


def test_overlay_percent_doubled_in_filter():
    """Percent signs in input must appear as %% in the filter string."""
    texts = ["75% of decisions", "60% gone", "100% sure"]
    for style in ('hook', 'main', 'number', 'insight'):
        for text in texts:
            f = overlay(text, style)
            for val in _extract_text_values(f):
                if '%' in text:
                    raw_pct = val.count('%') - val.count('%%') * 2 + val.count('%%')
                    # Simpler: no single % (only %%) after escaping
                    # Replace %% with placeholder and check no lone % remains
                    cleaned = val.replace('%%', '__PCT__')
                    check('%' not in cleaned,
                          f"Lone % in text value {val!r} (style={style}, input={text!r})")
            print(f"  PASS: style={style} {text!r} — percent correctly doubled")


def test_overlay_number_style_uses_static_fontsize():
    """'number' style must use a plain integer fontsize, not a time-dependent expression."""
    texts = ["75% of decisions", "60% gone", "₹10,000 invested"]
    for text in texts:
        f = overlay(text, 'number')
        for fs in _extract_fontsize_values(f):
            # Must be a plain integer (e.g. "64"), not an expression like "56*if(lt(t,..."
            check(fs.isdigit(),
                  f"fontsize is not a plain integer: fontsize={fs!r} (input={text!r})\n"
                  f"Dynamic fontsize expressions using 't' silently fail on some FFmpeg builds.")
        print(f"  PASS: 'number' style {text!r} — fontsize is static integer: {_extract_fontsize_values(f)}")


def test_overlay_all_styles_produce_drawtext():
    """Every style must produce at least one drawtext filter."""
    for style in ('hook', 'main', 'number', 'insight'):
        f = overlay("test line", style)
        check('drawtext=' in f, f"No drawtext in filter for style={style}: {f!r}")
        print(f"  PASS: style={style} produces drawtext filter")


def test_overlay_no_xhh_in_filter():
    """\\xHH sequences must never appear in the generated filter string."""
    texts = ["don't", "75%", "it's 100%", "you're at 40%"]
    for style in ('hook', 'main', 'number', 'insight'):
        for text in texts:
            f = overlay(text, style)
            check('\\x' not in f,
                  f"\\xHH found in filter (style={style}, input={text!r}):\n{f}")
            print(f"  PASS: style={style} {text!r} — no \\xHH in filter")


def test_overlay_balanced_single_quotes():
    """Every text='...' segment must have balanced single quotes."""
    texts = ["don't stop it's fine", "75% of 60% decisions", "you're losing 40%"]
    for style in ('hook', 'main', 'number', 'insight'):
        for text in texts:
            f = overlay(text, style)
            # Count quotes: each drawtext=...text='VALUE':... contributes exactly 2 quotes
            # around VALUE. We check by confirming each text= match opens and closes cleanly.
            matches = list(re.finditer(r"text='[^']*'", f))
            raw_text_count = f.count("text='")
            check(len(matches) == raw_text_count,
                  f"Unbalanced quotes in filter (style={style}, input={text!r}):\n{f}")
            print(f"  PASS: style={style} {text!r} — {len(matches)} text segment(s), all balanced")


def test_overlay_number_style_larger_than_default():
    """'number' style fontsize must be bigger than 'main' style fontsize."""
    text_with_pct = "75% decisions"
    text_plain = "plain line here"
    f_number = overlay(text_with_pct, 'number')
    f_main   = overlay(text_plain, 'main')
    fs_number = int(_extract_fontsize_values(f_number)[0])
    fs_main   = int(_extract_fontsize_values(f_main)[0])
    check(fs_number > fs_main,
          f"'number' fontsize ({fs_number}) must be > 'main' fontsize ({fs_main})")
    print(f"  PASS: 'number' fontsize={fs_number} > 'main' fontsize={fs_main}")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4: FFmpeg drawtext rendering (requires libfreetype — run on server)
# ─────────────────────────────────────────────────────────────────────────────

_DRAWTEXT_AVAILABLE = "drawtext" in subprocess.run(
    ["ffmpeg", "-filters"], capture_output=True, text=True
).stdout

FONT = vc.FONT_PATH  # uses the real font path from settings


def _render(filter_complex: str, output: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "ffmpeg", "-y",
            "-filter_complex", filter_complex,
            "-frames:v", "1",
            str(output),
        ],
        capture_output=True, text=True,
    )


def _render_text(text: str, style: str, output: Path) -> subprocess.CompletedProcess:
    """Render a single frame using the real overlay filter for the given text+style."""
    drawtext = overlay(text, style)
    fc = (
        f"color=black:size={vc.REEL_W}x{vc.REEL_H}:duration=0.04[bg];"
        f"[bg]{drawtext},format=yuv420p[v]"
    )
    return subprocess.run(
        [
            "ffmpeg", "-y",
            "-filter_complex", fc,
            "-map", "[v]",
            "-frames:v", "1",
            str(output),
        ],
        capture_output=True, text=True,
    )


def _skip_if_no_drawtext():
    if not _DRAWTEXT_AVAILABLE:
        print("  SKIP: drawtext not compiled into this FFmpeg build")
        print("        Install: apt-get install -y ffmpeg  (or build with --enable-libfreetype)")
        return True
    return False


def test_ffmpeg_renders_apostrophe():
    if _skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "apos.png"
        r = _render_text("don't stop", 'main', out)
        check(r.returncode == 0,
              f"FFmpeg exit {r.returncode}:\n{r.stderr[-1000:]}")
        check(out.stat().st_size > 1000, "Output file suspiciously small")
        print(f"  PASS: apostrophe rendered (rc=0, size={out.stat().st_size})")


def test_ffmpeg_renders_percent():
    if _skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pct.png"
        r = _render_text("75% of decisions", 'number', out)
        check(r.returncode == 0,
              f"FFmpeg exit {r.returncode}:\n{r.stderr[-1000:]}")
        check(out.stat().st_size > 1000, "Output file suspiciously small")
        print(f"  PASS: percent rendered (rc=0, size={out.stat().st_size})")


def test_ffmpeg_renders_all_styles():
    if _skip_if_no_drawtext(): return
    cases = [
        ("hook",    "Stop scrolling right now"),
        ("main",    "Most people never learn this"),
        ("number",  "75% of people fail here"),
        ("insight", "The real answer is simple"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for style, text in cases:
            out = Path(tmp) / f"{style}.png"
            r = _render_text(text, style, out)
            check(r.returncode == 0,
                  f"FFmpeg exit {r.returncode} for style={style!r}:\n{r.stderr[-1000:]}")
            check(out.stat().st_size > 1000, f"Output empty for style={style!r}")
            print(f"  PASS: style={style!r} rendered (rc=0, size={out.stat().st_size})")


def test_ffmpeg_renders_combined_problematic():
    """The exact production texts that were invisible before the fix."""
    if _skip_if_no_drawtext(): return
    texts = [
        ("Overanalyzing costs you 75% of good decisions", 'number'),
        ("distracted folks get 60%", 'number'),
        ("don't follow others' agendas", 'main'),
        ("you're losing 40% of your focus", 'number'),
        ("it's costing you 75% of focus", 'number'),
        ("Stop wasting time—focus now", 'hook'),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for i, (text, style) in enumerate(texts):
            out = Path(tmp) / f"prod_{i}.png"
            r = _render_text(text, style, out)
            check(r.returncode == 0,
                  f"FFmpeg exit {r.returncode} for {text!r}:\n{r.stderr[-1000:]}")
            check(out.stat().st_size > 1000, f"Empty output for {text!r}")
            print(f"  PASS: {text!r} (style={style}) rendered ok")


def test_ffmpeg_multi_line_clip():
    """Full multi-line scene — same as production flow for a 4-line clip."""
    if _skip_if_no_drawtext(): return
    scene_text = "Overanalyzing costs you 75% of good decisions—distracted folks get 60%"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "multiline.png"
        r = _render_text(scene_text, 'main', out)
        check(r.returncode == 0,
              f"FFmpeg exit {r.returncode}:\n{r.stderr[-1000:]}")
        check(out.stat().st_size > 1000, "Output empty for multi-line clip")
        print(f"  PASS: full multi-line scene rendered (rc=0, size={out.stat().st_size})")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    # Layer 1 — _escape()
    test_escape_apostrophe_replaced_with_unicode,
    test_escape_left_single_quote_replaced,
    test_escape_percent_doubled,
    test_escape_no_xhh_sequences,
    test_escape_colon_escaped,
    test_escape_backslash_doubled,
    test_escape_em_dash_converted,
    test_escape_en_dash_converted,
    test_escape_ellipsis_converted,
    test_escape_combined_problematic,
    # Layer 2 — _is_punchline_number()
    test_punchline_percent_lines_detected,
    test_punchline_plain_lines_not_detected,
    # Layer 3 — filter string structure
    test_overlay_no_ascii_apostrophe_in_filter,
    test_overlay_percent_doubled_in_filter,
    test_overlay_number_style_uses_static_fontsize,
    test_overlay_all_styles_produce_drawtext,
    test_overlay_no_xhh_in_filter,
    test_overlay_balanced_single_quotes,
    test_overlay_number_style_larger_than_default,
    # Layer 4 — FFmpeg rendering (server only)
    test_ffmpeg_renders_apostrophe,
    test_ffmpeg_renders_percent,
    test_ffmpeg_renders_all_styles,
    test_ffmpeg_renders_combined_problematic,
    test_ffmpeg_multi_line_clip,
]

if __name__ == "__main__":
    print(f"FFmpeg drawtext available: {_DRAWTEXT_AVAILABLE}")
    print(f"Font path: {FONT}")
    for fn in ALL_TESTS:
        run(fn)

    print(f"\n{'='*60}")
    print(f"Results: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print(f"  - {f}")
    sys.exit(0 if not FAILED else 1)
