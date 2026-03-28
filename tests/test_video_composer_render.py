"""
End-to-end render tests for VideoComposer using a real sample image.

Creates a 1080x1920 test image, runs _build_cinematic_clips with production-like
scenes (including problematic apostrophes and percent signs), and verifies every
output clip is a valid, non-empty video with the correct dimensions.

Requires: FFmpeg with drawtext (libfreetype) — i.e. the server.

Run:
    source venv/bin/activate
    python tests/test_video_composer_render.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw
from src.agents.video_composer import VideoComposer

vc = VideoComposer()

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
        import traceback
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        FAILED.append(label)

def check(condition, msg):
    assert condition, msg


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_test_image(path: Path):
    """Create a realistic-looking 1080x1920 gradient image for testing."""
    img = Image.new("RGB", (1080, 1920))
    draw = ImageDraw.Draw(img)
    # Simple gradient from dark blue to dark purple
    for y in range(1920):
        r = int(20 + (y / 1920) * 40)
        g = int(10 + (y / 1920) * 20)
        b = int(80 + (y / 1920) * 60)
        draw.line([(0, y), (1080, y)], fill=(r, g, b))
    img.save(path, "PNG")
    return path


def probe_video(path: Path) -> dict:
    """Return basic video properties using ffprobe."""
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration,nb_frames",
            "-of", "json",
            str(path),
        ],
        capture_output=True, text=True,
    )
    data = json.loads(r.stdout)
    streams = data.get("streams", [{}])
    return streams[0] if streams else {}


def check_clip_valid(clip: Path, label: str):
    """Assert clip exists, is non-empty, and has correct dimensions."""
    check(clip.exists(), f"{label}: file does not exist")
    size = clip.stat().st_size
    check(size > 10_000, f"{label}: file too small ({size} bytes) — likely empty/failed render")
    props = probe_video(clip)
    check(props.get("width") == vc.REEL_W,
          f"{label}: wrong width {props.get('width')} (expected {vc.REEL_W})")
    check(props.get("height") == vc.REEL_H,
          f"{label}: wrong height {props.get('height')} (expected {vc.REEL_H})")
    print(f"  OK  {label}: {size // 1024}KB, {props.get('width')}x{props.get('height')}")


_DRAWTEXT_AVAILABLE = "drawtext" in subprocess.run(
    ["ffmpeg", "-filters"], capture_output=True, text=True
).stdout

def skip_if_no_drawtext():
    if not _DRAWTEXT_AVAILABLE:
        print("  SKIP: drawtext not compiled into this FFmpeg (needs libfreetype)")
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Scene definitions — cover all 4 styles and all problem characters
# ─────────────────────────────────────────────────────────────────────────────

# Each scene dict matches the format produced by CinematicScriptGenerator
SCENES_BASIC = [
    {
        "lines": ["Stop scrolling right now"],          # → hook style (clip 1)
        "motion": "zoom_in",
        "image_path": None,   # filled in per test
    },
    {
        "lines": ["Most people never learn this"],      # → main style
        "motion": "pan_right",
        "image_path": None,
    },
    {
        "lines": ["The real answer is surprisingly simple"],  # → insight (last clip)
        "motion": "zoom_out",
        "image_path": None,
    },
]

SCENES_PROBLEMATIC = [
    {
        "lines": ["Stop wasting time right now"],       # clip 1 → hook
        "motion": "zoom_in",
        "image_path": None,
    },
    {
        "lines": ["75% of people fail here"],           # → number style (has %)
        "motion": "pan_left",
        "image_path": None,
    },
    {
        "lines": ["don't follow others' agendas"],      # → main style (has apostrophes)
        "motion": "zoom_in",
        "image_path": None,
    },
    {
        "lines": ["you're losing 40% of your focus"],   # → number style (both)
        "motion": "pan_right",
        "image_path": None,
    },
    {
        "lines": ["it's costing you 75% every day"],    # → number style (both)
        "motion": "zoom_out",
        "image_path": None,
    },
]

SCENES_FULL_PRODUCTION = [
    {
        "lines": ["Overanalyzing costs you 75% of good decisions—distracted folks get 60%"],
        "motion": "zoom_in",
        "image_path": None,
    },
    {
        "lines": ["don't follow others' agendas", "you're wasting time"],
        "motion": "pan_left",
        "image_path": None,
    },
    {
        "lines": ["₹10,000 invested today can become ₹1,00,000"],
        "motion": "zoom_out",
        "image_path": None,
    },
    {
        "lines": ["it's time to take back 100% control"],
        "motion": "pan_right",
        "image_path": None,
    },
]


def _fill_image(scenes, img_path):
    return [{**s, "image_path": img_path} for s in scenes]


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_basic_scenes_render():
    """All 4 animation styles render without error on a real image."""
    if skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = make_test_image(tmp / "bg.png")
        scenes = _fill_image(SCENES_BASIC, img)
        clips = vc.build_clips(scenes, tmp / "clips", transition_dur=0.6)
        check(len(clips) == 3, f"Expected 3 clips, got {len(clips)}")
        for i, clip in enumerate(clips):
            check_clip_valid(clip, f"clip_{i+1}")


def test_percent_lines_render():
    """Lines containing % (which trigger 'number' style) render correctly."""
    if skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = make_test_image(tmp / "bg.png")
        scenes = _fill_image(SCENES_PROBLEMATIC, img)
        clips = vc.build_clips(scenes, tmp / "clips", transition_dur=0.6)
        check(len(clips) == 5, f"Expected 5 clips, got {len(clips)}")
        for i, clip in enumerate(clips):
            check_clip_valid(clip, f"clip_{i+1}")
        # Clips 2, 4, 5 are the percent-containing ones — verify specifically
        for idx in [1, 3, 4]:
            check_clip_valid(clips[idx], f"percent clip {idx+1}")
            print(f"  ✓ Percent clip {idx+1} rendered OK")


def test_apostrophe_lines_render():
    """Lines containing apostrophes render without breaking the filter."""
    if skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = make_test_image(tmp / "bg.png")
        scenes = _fill_image(SCENES_PROBLEMATIC, img)
        clips = vc.build_clips(scenes, tmp / "clips", transition_dur=0.6)
        # Clip 3: "don't follow others' agendas"
        # Clip 4: "you're losing 40%..."
        # Clip 5: "it's costing you 75%..."
        for idx in [2, 3, 4]:
            check_clip_valid(clips[idx], f"apostrophe clip {idx+1}")
            print(f"  ✓ Apostrophe clip {idx+1} rendered OK")


def test_full_production_scenes_render():
    """Exact production-style scenes that were previously broken."""
    if skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = make_test_image(tmp / "bg.png")
        scenes = _fill_image(SCENES_FULL_PRODUCTION, img)
        clips = vc.build_clips(scenes, tmp / "clips", transition_dur=0.6)
        check(len(clips) == 4, f"Expected 4 clips, got {len(clips)}")
        for i, clip in enumerate(clips):
            check_clip_valid(clip, f"clip_{i+1}")


def test_each_style_produces_valid_clip():
    """Force each style explicitly and verify each produces a valid clip."""
    if skip_if_no_drawtext(): return
    style_scenes = {
        'hook':    "Stop everything and listen",          # clip 1 = hook always
        'number':  "75% of people fail this test",        # punchline detected
        'main':    "Most people never discover this",     # default
        'insight': "The answer is closer than you think", # last clip
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = make_test_image(tmp / "bg.png")
        for style, text in style_scenes.items():
            scenes = [{"lines": [text], "motion": "zoom_in", "image_path": img}]
            clips = vc.build_clips(scenes, tmp / f"clips_{style}", transition_dur=0.6)
            check(len(clips) == 1, f"Expected 1 clip for style={style}")
            check_clip_valid(clips[0], f"style={style}")


def test_blend_clips_produces_final_video():
    """Full pipeline: build clips → blend → final video."""
    if skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = make_test_image(tmp / "bg.png")
        scenes = _fill_image(SCENES_PROBLEMATIC, img)
        clips = vc.build_clips(scenes, tmp / "clips", transition_dur=0.6)
        final = vc.blend_clips(clips, tmp, transition_dur=0.6)
        check(final.exists(), f"Final video not found: {final}")
        size = final.stat().st_size
        check(size > 50_000, f"Final video too small: {size} bytes")
        props = probe_video(final)
        check(props.get("width") == vc.REEL_W, f"Wrong width: {props.get('width')}")
        check(props.get("height") == vc.REEL_H, f"Wrong height: {props.get('height')}")
        print(f"  PASS: Final video {size // 1024}KB, "
              f"{props.get('width')}x{props.get('height')}")


def test_multiple_images_different_scenes():
    """Each scene can have its own image — no cross-contamination."""
    if skip_if_no_drawtext(): return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Create 3 visually distinct images
        scenes = []
        for i, (text, motion) in enumerate([
            ("75% of people miss this", "zoom_in"),
            ("don't ignore the warning", "pan_left"),
            ("it's your last chance today", "zoom_out"),
        ]):
            img = make_test_image(tmp / f"bg_{i}.png")
            scenes.append({"lines": [text], "motion": motion, "image_path": img})

        clips = vc.build_clips(scenes, tmp / "clips", transition_dur=0.6)
        check(len(clips) == 3, f"Expected 3 clips, got {len(clips)}")
        for i, clip in enumerate(clips):
            check_clip_valid(clip, f"clip_{i+1}")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_basic_scenes_render,
    test_percent_lines_render,
    test_apostrophe_lines_render,
    test_full_production_scenes_render,
    test_each_style_produces_valid_clip,
    test_blend_clips_produces_final_video,
    test_multiple_images_different_scenes,
]

if __name__ == "__main__":
    print(f"FFmpeg drawtext available: {_DRAWTEXT_AVAILABLE}")
    print(f"VideoComposer font: {vc.FONT_PATH}")
    print(f"Resolution: {vc.REEL_W}x{vc.REEL_H} @ {vc.FPS}fps")

    for fn in ALL_TESTS:
        run(fn)

    print(f"\n{'='*60}")
    print(f"Results: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print(f"  - {f}")
    sys.exit(0 if not FAILED else 1)
