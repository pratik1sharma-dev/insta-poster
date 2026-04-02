"""
Master Scheduler — posts to all channels on their configured schedule,
runs the feedback loop in the background, and exposes a small HTTP API
for manual triggers.

Usage:
    python3 -m src.scheduler                              # all channels, live post
    python3 -m src.scheduler --channels wealthcapsules,pagecapsules
    python3 -m src.scheduler --dry-run                    # generate but don't post
    python3 -m src.scheduler --port 8000                  # API port (default 8000)

API:
    POST /trigger/{channel}                    trigger with channel's default post type
    POST /trigger/{channel}?post_type=carousel override post type
    POST /trigger/{channel}?dry_run=true       trigger without posting
    GET  /status                               running jobs + next scheduled slots
    GET  /health                               liveness check
"""
import argparse
import logging
import threading
import time
import yaml
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Shared state (scheduler loop ↔ API handlers) ───────────────────────────
# Protected by _state_lock for thread-safe reads/writes.
_state_lock = threading.Lock()
_active_threads: dict = {}       # channel → Thread
_scheduled_channels: list = []   # channels known to scheduler
_scheduler_dry_run: bool = False  # global dry-run flag set at startup


# ── Fired-jobs tracker ──────────────────────────────────────────────────────

_FIRED_FILE = Path("output/scheduler_fired.txt")


def _load_fired() -> set:
    if _FIRED_FILE.exists():
        return set(_FIRED_FILE.read_text().splitlines())
    return set()


def _mark_fired(key: str, fired: set) -> None:
    fired.add(key)
    _FIRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FIRED_FILE.write_text("\n".join(sorted(fired)))


def _prune_fired(fired: set) -> set:
    today = date.today().isoformat()
    return {k for k in fired if today in k}


# ── Channel pipeline runner ─────────────────────────────────────────────────

def _run_channel(channel: str, dry_run: bool, post_type_override: Optional[str] = None) -> None:
    """Run the full content pipeline for one channel. Called in its own thread."""
    from src.pipelines.ContentPipeline import ContentPipeline, PostType
    from src.utils import load_channel_config

    try:
        cfg = load_channel_config(channel)
        post_type_str = (post_type_override or getattr(cfg, "default_post_type", "cinematic")).lower()
        type_map = {
            "cinematic": PostType.CINEMATIC,
            "carousel": PostType.CAROUSEL,
            "reel": PostType.REEL,
        }
        post_type = type_map.get(post_type_str, PostType.CINEMATIC)

        with_voice = getattr(cfg, "with_voice", False)
        logger.info("[%s] ▶ Starting pipeline  type=%s  voice=%s  dry_run=%s", channel, post_type_str, with_voice, dry_run)
        pipeline = ContentPipeline()
        result = pipeline.run(
            channel_name=channel,
            dry_run=dry_run,
            post_types={post_type},
            with_voice=with_voice,
        )
        logger.info("[%s] ✓ Done  status=%s  post_id=%s", channel, result.status, result.post_id)
    except Exception as e:
        logger.error("[%s] ✗ Pipeline failed: %s", channel, e, exc_info=True)


# ── Feedback loop runner ────────────────────────────────────────────────────

def _run_feedback_loop(channels: list) -> None:
    from src.agents.feedback_loop import FeedbackLoop
    try:
        FeedbackLoop().run_forever(channels)
    except Exception as e:
        logger.error("Feedback loop crashed: %s", e, exc_info=True)


# ── API server ──────────────────────────────────────────────────────────────

def _build_api():
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import JSONResponse

    api = FastAPI(title="insta-poster API", docs_url="/docs")

    @api.get("/health")
    def health():
        return {"status": "ok", "time": datetime.now().isoformat()}

    @api.get("/status")
    def status():
        from src.utils import load_channel_config
        with _state_lock:
            running = {ch for ch, t in _active_threads.items() if t.is_alive()}

        schedule = []
        for ch in _scheduled_channels:
            try:
                cfg = load_channel_config(ch)
                times = getattr(cfg, "post_times", None) or []
                ptype = getattr(cfg, "default_post_type", "cinematic")
                schedule.append({"channel": ch, "post_times": times, "post_type": ptype,
                                  "running": ch in running})
            except Exception:
                schedule.append({"channel": ch, "error": "config load failed"})

        return {"scheduler_dry_run": _scheduler_dry_run, "channels": schedule}

    @api.post("/trigger/{channel}")
    def trigger(
        channel: str,
        post_type: Optional[str] = Query(default=None, description="cinematic | carousel | reel"),
        dry_run: bool = Query(default=False),
    ):
        if channel not in _scheduled_channels:
            raise HTTPException(status_code=404, detail=f"Channel '{channel}' not known to scheduler")

        with _state_lock:
            existing = _active_threads.get(channel)
            if existing and existing.is_alive():
                raise HTTPException(status_code=409, detail=f"Pipeline already running for '{channel}'")

            effective_dry_run = dry_run or _scheduler_dry_run
            t = threading.Thread(
                target=_run_channel,
                args=(channel, effective_dry_run, post_type),
                name=f"pipeline-{channel}-api",
                daemon=True,
            )
            t.start()
            _active_threads[channel] = t

        logger.info("[%s] ▶ API trigger  post_type=%s  dry_run=%s", channel, post_type or "default", effective_dry_run)
        return {"triggered": channel, "post_type": post_type or "default", "dry_run": effective_dry_run}

    return api


def _start_api_server(port: int) -> None:
    import uvicorn
    api = _build_api()
    logger.info("API server starting on http://0.0.0.0:%d  (docs: /docs)", port)
    uvicorn.run(api, host="0.0.0.0", port=port, log_level="warning")


# ── Main scheduler loop ─────────────────────────────────────────────────────

def run_scheduler(channels: list, dry_run: bool = False, api_port: int = 8000) -> None:
    global _scheduled_channels, _scheduler_dry_run
    _scheduled_channels = channels
    _scheduler_dry_run = dry_run

    from src.utils import load_channel_config

    logger.info("=" * 70)
    logger.info("insta-poster scheduler starting")
    logger.info("=" * 70)
    for ch in channels:
        try:
            cfg = load_channel_config(ch)
            times = getattr(cfg, "post_times", None) or []
            ptype = getattr(cfg, "default_post_type", "cinematic")
            logger.info("  %-22s %s  [%s]", ch, times if times else "(no times set)", ptype)
        except Exception:
            logger.warning("  %-22s (config load failed)", ch)
    logger.info("API  →  http://localhost:%d/docs", api_port)
    logger.info("=" * 70)

    # Feedback loop
    threading.Thread(
        target=_run_feedback_loop, args=(channels,), daemon=True, name="feedback-loop"
    ).start()
    logger.info("Feedback loop started (poll every %ds)", _feedback_poll_interval())

    # API server
    threading.Thread(
        target=_start_api_server, args=(api_port,), daemon=True, name="api-server"
    ).start()

    fired = _load_fired()

    while True:
        now = datetime.now()
        today = now.date().isoformat()
        current_hhmm = now.strftime("%H:%M")

        if current_hhmm == "00:01":
            fired = _prune_fired(fired)

        for channel in channels:
            with _state_lock:
                running = _active_threads.get(channel)
            if running and running.is_alive():
                continue

            try:
                cfg = load_channel_config(channel)
            except Exception as e:
                logger.error("Config load failed for %s: %s", channel, e)
                continue

            for slot in (getattr(cfg, "post_times", None) or []):
                job_key = f"{channel}_{today}_{slot}"
                if slot == current_hhmm and job_key not in fired:
                    _mark_fired(job_key, fired)
                    logger.info("[%s] ⏰ Firing scheduled post (slot=%s)", channel, slot)
                    t = threading.Thread(
                        target=_run_channel,
                        args=(channel, dry_run),
                        name=f"pipeline-{channel}",
                        daemon=True,
                    )
                    t.start()
                    with _state_lock:
                        _active_threads[channel] = t

        time.sleep(60)


def _feedback_poll_interval() -> int:
    try:
        from src.config import settings
        return settings.feedback_poll_interval
    except Exception:
        return 1800


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="insta-poster master scheduler")
    parser.add_argument("--channels", help="Comma-separated channel names (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't post")
    parser.add_argument("--port", type=int, default=8000, help="API server port (default: 8000)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.channels:
        channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    else:
        with open("src/config/channels.yaml") as f:
            channels = list(yaml.safe_load(f).keys())

    run_scheduler(channels, dry_run=args.dry_run, api_port=args.port)


if __name__ == "__main__":
    main()
