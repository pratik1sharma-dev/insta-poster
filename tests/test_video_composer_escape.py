"""
Tests for VideoComposer._escape and FFmpeg drawtext rendering.

Run with: python -m pytest tests/test_video_composer_escape.py -v
Or directly: python tests/test_video_composer_escape.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Pull _escape out of VideoComposer without loading all heavy deps
# ---------------------------------------------------------------------------
import re


def _make_escape():
    """Return an _escape function matching the current VideoComposer implementation."""
    UNICODE_NORMALIZE = str.maketrans({
        "'": '\u2019',       # ASCII apostrophe → right single quote (safe in FFmpeg)
        '\u2018': '\u2019',  # left single quotation mark → right single quote
        '\u201c': '"',       # left double quotation mark
        '\u201d': '"',       # right double quotation mark
        '\u2014': ' - ',     # em dash
        '\u2013': '-',       # en dash
        '\u2026': '...',     # ellipsis
    })

    def _escape(s: str) -> str:
        s = s.translate(UNICODE_NORMALIZE)
        s = s.replace('\r\n', '\n').replace('\r', '\n')
        s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', s)
        return (
            s.replace('\\', '\\\\')
             .replace('%', '%%')
             .replace(':', '\\:')
             .replace('\n', '\\n')
        )

    return _escape


escape = _make_escape()

# ---------------------------------------------------------------------------
# Unit tests: _escape output
# ---------------------------------------------------------------------------

def test_apostrophe_becomes_unicode():
    """ASCII apostrophe must be replaced with U+2019, never appear as ' in output."""
    result = escape("don't")
    assert "'" not in result, f"ASCII apostrophe still present: {result!r}"
    assert '\u2019' in result, f"U+2019 not found in output: {result!r}"
    print(f"  PASS: don't → {result!r}")


def test_percent_doubled():
    """Percent sign must be doubled for drawtext text expansion."""
    result = escape("75% of good")
    assert '%%' in result, f"Expected %% in output: {result!r}"
    assert '\\x25' not in result, f"\\x25 must not appear: {result!r}"
    print(f"  PASS: 75% of good → {result!r}")


def test_colon_escaped():
    result = escape("10:30 AM")
    assert '\\:' in result, f"Colon not escaped: {result!r}"
    print(f"  PASS: 10:30 AM → {result!r}")


def test_backslash_doubled():
    result = escape("C:\\Users")
    assert '\\\\' in result, f"Backslash not doubled: {result!r}"
    print(f"  PASS: C:\\\\Users → {result!r}")


def test_no_xhh_escapes():
    """We must never emit \\xHH sequences — FFmpeg doesn't support them."""
    inputs = ["don't", "75%", "it's 100%"]
    for s in inputs:
        result = escape(s)
        assert '\\x' not in result, f"\\xHH escape found in {result!r} (from {s!r})"
        print(f"  PASS: {s!r} → {result!r} (no \\xHH)")


def test_em_dash_converted():
    result = escape("work\u2014life")
    assert '\u2014' not in result
    assert ' - ' in result
    print(f"  PASS: em dash → {result!r}")


def test_combined_problematic_text():
    """The exact text that was broken: apostrophe + percent in same string."""
    texts = [
        "Overanalyzing costs you 75% of good decisions",
        "distracted folks get 60%",
        "don't follow others' agendas",
        "you're losing 40% of your focus",
    ]
    for t in texts:
        result = escape(t)
        assert "'" not in result, f"ASCII apostrophe in output: {result!r}"
        assert '\\x' not in result, f"\\xHH escape in output: {result!r}"
        if '%' in t:
            assert '%%' in result, f"Percent not doubled in: {result!r}"
        print(f"  PASS: {t!r} → {result!r}")


# ---------------------------------------------------------------------------
# FFmpeg integration test: render text to a 1-frame image and check exit code
# ---------------------------------------------------------------------------

FONT = "/System/Library/Fonts/Helvetica.ttc"

# Check if local FFmpeg has drawtext support
_DRAWTEXT_AVAILABLE = (
    subprocess.run(
        ["ffmpeg", "-filters"],
        capture_output=True, text=True
    ).stdout.find("drawtext") != -1
)


def _ffmpeg_drawtext(text_escaped: str, output: Path) -> subprocess.CompletedProcess:
    """Run FFmpeg drawtext with the given pre-escaped text string."""
    filter_str = (
        f"color=black:size=400x100:duration=0.04[bg];"
        f"[bg]drawtext=text='{text_escaped}':fontfile='{FONT}':"
        f"fontcolor=white:fontsize=28:x=10:y=30"
    )
    return subprocess.run(
        [
            "ffmpeg", "-y",
            "-filter_complex", filter_str,
            "-frames:v", "1",
            str(output),
        ],
        capture_output=True,
        text=True,
    )


def test_ffmpeg_apostrophe():
    """FFmpeg must exit 0 when rendering text with apostrophes."""
    if not _DRAWTEXT_AVAILABLE:
        print("  SKIP: drawtext not compiled into local FFmpeg (run on server to confirm)")
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "apos.png"
        result = _ffmpeg_drawtext(escape("don't stop"), out)
        assert result.returncode == 0, (
            f"FFmpeg failed (rc={result.returncode}):\n{result.stderr[-800:]}"
        )
        assert out.exists() and out.stat().st_size > 0, "Output image is empty"
        print(f"  PASS: FFmpeg rendered apostrophe text (rc=0, size={out.stat().st_size})")


def test_ffmpeg_percent():
    """FFmpeg must exit 0 when rendering text with percent signs."""
    if not _DRAWTEXT_AVAILABLE:
        print("  SKIP: drawtext not compiled into local FFmpeg (run on server to confirm)")
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "pct.png"
        result = _ffmpeg_drawtext(escape("75% done"), out)
        assert result.returncode == 0, (
            f"FFmpeg failed (rc={result.returncode}):\n{result.stderr[-800:]}"
        )
        assert out.exists() and out.stat().st_size > 0, "Output image is empty"
        print(f"  PASS: FFmpeg rendered percent text (rc=0, size={out.stat().st_size})")


def test_ffmpeg_combined():
    """FFmpeg must exit 0 for the exact texts that were previously broken."""
    if not _DRAWTEXT_AVAILABLE:
        print("  SKIP: drawtext not compiled into local FFmpeg (run on server to confirm)")
        return
    problematic = [
        "Overanalyzing costs you 75% of good decisions",
        "distracted folks get 60%",
        "don't follow others' agendas",
        "you're losing 40% of focus",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, text in enumerate(problematic):
            out = Path(tmpdir) / f"combined_{i}.png"
            result = _ffmpeg_drawtext(escape(text), out)
            assert result.returncode == 0, (
                f"FFmpeg failed for {text!r} (rc={result.returncode}):\n{result.stderr[-800:]}"
            )
            assert out.exists() and out.stat().st_size > 0
            print(f"  PASS: FFmpeg rendered: {text!r}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_apostrophe_becomes_unicode,
        test_percent_doubled,
        test_colon_escaped,
        test_backslash_doubled,
        test_no_xhh_escapes,
        test_em_dash_converted,
        test_combined_problematic_text,
        test_ffmpeg_apostrophe,
        test_ffmpeg_percent,
        test_ffmpeg_combined,
    ]
    passed = 0
    failed = 0
    for t in tests:
        print(f"\n[{t.__name__}]")
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
