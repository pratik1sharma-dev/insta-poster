"""
Feedback Loop — long-running service that polls for metrics, scores content
with Gemini vision, and applies config improvements when enough data is available.
"""
import json
import logging
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import settings
from src.utils.config_loader import load_channel_config
from src.utils.feedback_store import (
    backup_channel_config,
    apply_config_patch,
    compute_avg_metrics,
    get_active_config_version,
    get_config_version_stats,
    get_pending_fetch,
    get_scored_since,
    get_version_applied_at,
    init_db,
    save_config_version,
    update_config_version_after,
    update_post_metrics,
    update_post_scores,
)

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """Orchestrates the automated learning loop for all channels."""

    MIN_POSTS_FOR_ANALYSIS = settings.feedback_min_posts_for_analysis
    METRIC_FETCH_DELAY_HOURS = settings.feedback_metric_delay_hours
    POLL_INTERVAL_SECONDS = settings.feedback_poll_interval

    def run_forever(self, channels: list[str]) -> None:
        """Block forever, polling all channels every POLL_INTERVAL_SECONDS."""
        init_db()
        logger.info("Feedback loop started. Channels: %s | poll=%ds", channels, self.POLL_INTERVAL_SECONDS)
        while True:
            for channel in channels:
                try:
                    self._process_channel(channel)
                except Exception as e:
                    logger.error("Error processing channel '%s': %s", channel, e)
            logger.info("Cycle complete. Sleeping %ds...", self.POLL_INTERVAL_SECONDS)
            time.sleep(self.POLL_INTERVAL_SECONDS)

    def _process_channel(self, channel: str) -> None:
        logger.info("Processing channel: %s", channel)

        # 1. Fetch + score posts that are ready (posted >delay_hours ago, metrics null)
        pending = get_pending_fetch(channel, delay_hours=self.METRIC_FETCH_DELAY_HOURS)
        if pending:
            logger.info("  %d posts pending metric fetch for %s", len(pending), channel)
            self._fetch_and_score(channel, pending)

        # 2. Check if enough new scored data since last config update
        active_version = get_active_config_version(channel)
        applied_at = get_version_applied_at(channel, active_version) or "2000-01-01T00:00:00+00:00"
        new_scored = get_scored_since(channel, applied_at)

        logger.info(
            "  %s: active_version=%s, new_scored_since_update=%d (need %d)",
            channel, active_version, len(new_scored), self.MIN_POSTS_FOR_ANALYSIS,
        )

        if len(new_scored) >= self.MIN_POSTS_FOR_ANALYSIS:
            self._run_analysis_and_apply(channel, new_scored)

    def _fetch_and_score(self, channel: str, records: list[dict]) -> None:
        """Fetch social metrics and run Gemini AI scoring for each record."""
        from src.publishers.postiz_client import PostizClient
        client = PostizClient()
        fetched_at = datetime.now(timezone.utc).isoformat()

        for record in records:
            record_id = record["record_id"]
            post_id = record.get("post_id")

            # 1. Fetch social metrics via Postiz
            metrics = None
            if post_id:
                metrics = client.get_post_analytics(post_id)

            if metrics:
                update_post_metrics(
                    record_id=record_id,
                    like_count=metrics["like_count"],
                    comments_count=metrics["comments_count"],
                    saved=metrics["saved"],
                    reach=metrics["reach"],
                    fetched_at=fetched_at,
                )
                logger.info(
                    "  Metrics fetched for %s: reach=%d likes=%d saves=%d",
                    record_id, metrics["reach"], metrics["like_count"], metrics["saved"],
                )
            else:
                # Mark as fetched even if API returned nothing (avoids infinite retry)
                update_post_metrics(
                    record_id=record_id,
                    like_count=0, comments_count=0, saved=0, reach=0,
                    fetched_at=fetched_at,
                )
                logger.warning("  No metrics available for %s (new channel or API unavailable)", record_id)

            # 2. AI scoring via Gemini vision
            cinematic_path = record.get("cinematic_path")
            scores = self._score_with_gemini(
                cinematic_path=cinematic_path,
                hook_text=record.get("hook_text", ""),
                story_spine=record.get("story_spine", ""),
                channel=channel,
            )
            update_post_scores(
                record_id=record_id,
                hook_quality=scores["hook_quality"],
                story_clarity=scores["story_clarity"],
                visual_quality=scores["visual_quality"],
                scoring_notes=scores["scoring_notes"],
                scored_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.info(
                "  AI scores for %s: hook=%.1f story=%.1f visual=%.1f",
                record_id, scores["hook_quality"], scores["story_clarity"], scores["visual_quality"],
            )

    def _score_with_gemini(
        self,
        cinematic_path: Optional[str],
        hook_text: str,
        story_spine: str,
        channel: str,
    ) -> dict:
        """
        Score a post using Gemini vision (if video exists) or text-only fallback.

        Returns dict: hook_quality, story_clarity, visual_quality, scoring_notes (all 0-10).
        """
        default_scores = {"hook_quality": 5.0, "story_clarity": 5.0, "visual_quality": 5.0, "scoring_notes": "default"}

        try:
            from google import genai
            from google.genai import types

            if not settings.gemini_api_key:
                logger.warning("No GEMINI_API_KEY — using text-only scoring")
                return self._score_text_only(hook_text, story_spine, channel)

            client = genai.Client(api_key=settings.gemini_api_key)
            model = "gemini-2.0-flash"

            # Try to extract a frame from the video
            frame_data = None
            if cinematic_path and Path(cinematic_path).exists():
                frame_data = self._extract_frame(cinematic_path)

            prompt = f"""You are evaluating an Instagram Reel for the channel '{channel}'.

Hook text: "{hook_text}"
Story spine: "{story_spine}"

Score each dimension from 0 to 10:
- hook_quality: Does the hook immediately grab attention and create curiosity?
- story_clarity: Is the narrative clear, coherent, and easy to follow?
- visual_quality: Are the visuals compelling and on-brand? (score 5 if no video available)

Respond with ONLY valid JSON:
{{"hook_quality": 0-10, "story_clarity": 0-10, "visual_quality": 0-10, "scoring_notes": "1-2 sentence assessment"}}"""

            contents = []
            if frame_data:
                contents.append(types.Part.from_bytes(data=frame_data, mime_type="image/jpeg"))
            contents.append(prompt)

            response = client.models.generate_content(model=model, contents=contents)
            raw = response.text

            # Parse JSON from response
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return {
                    "hook_quality": float(data.get("hook_quality", 5)),
                    "story_clarity": float(data.get("story_clarity", 5)),
                    "visual_quality": float(data.get("visual_quality", 5)),
                    "scoring_notes": str(data.get("scoring_notes", "")),
                }
        except Exception as e:
            logger.error("Gemini scoring failed: %s — using defaults", e)

        return default_scores

    def _score_text_only(self, hook_text: str, story_spine: str, channel: str) -> dict:
        """Fallback: score using text-only Gemini call (no vision)."""
        try:
            from google import genai
            client = genai.Client(api_key=settings.gemini_api_key)
            prompt = (
                f"Score this Instagram hook (0-10) for channel '{channel}'.\n"
                f"Hook: \"{hook_text}\"\nStory: \"{story_spine}\"\n\n"
                '{"hook_quality": 0-10, "story_clarity": 0-10, "visual_quality": 5, "scoring_notes": "text-only"}'
            )
            response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            import re, json as _json
            m = re.search(r'\{.*\}', response.text, re.DOTALL)
            if m:
                data = _json.loads(m.group())
                return {
                    "hook_quality": float(data.get("hook_quality", 5)),
                    "story_clarity": float(data.get("story_clarity", 5)),
                    "visual_quality": 5.0,
                    "scoring_notes": str(data.get("scoring_notes", "text-only")),
                }
        except Exception as e:
            logger.error("Text-only scoring failed: %s", e)
        return {"hook_quality": 5.0, "story_clarity": 5.0, "visual_quality": 5.0, "scoring_notes": "scoring unavailable"}

    def _extract_frame(self, video_path: str) -> Optional[bytes]:
        """Extract first frame from video using ffmpeg. Returns JPEG bytes or None."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", tmp_path],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0 and Path(tmp_path).exists():
                with open(tmp_path, "rb") as f:
                    return f.read()
        except Exception as e:
            logger.warning("Frame extraction failed for %s: %s", video_path, e)
        return None

    def _run_analysis_and_apply(self, channel: str, records: list[dict]) -> None:
        """Run LLM analysis on scored records and apply config patch."""
        from src.agents.feedback_analyzer import FeedbackAnalyzer

        logger.info("Running config analysis for '%s' (%d records)...", channel, len(records))

        try:
            channel_config = load_channel_config(channel)
        except Exception as e:
            logger.error("Could not load channel config for '%s': %s", channel, e)
            return

        version_stats = get_config_version_stats(channel)

        # Update avg_after for previous version (now we have post-change data)
        active_version = get_active_config_version(channel)
        if active_version and version_stats:
            prev_versions = [v for v in version_stats if v["version"] != active_version and not v.get("avg_reach_after")]
            if prev_versions:
                prev = prev_versions[-1]
                posts_under_prev = get_scored_since(channel, prev["applied_at"])
                posts_under_prev = [r for r in posts_under_prev if r.get("config_version") == prev["version"]]
                if posts_under_prev:
                    avg_after = compute_avg_metrics(posts_under_prev)
                    update_config_version_after(channel, prev["version"], avg_after)
                    logger.info("Updated avg_after for version %s: %s", prev["version"], avg_after)

        analyzer = FeedbackAnalyzer()
        patch = analyzer.analyze(channel, records, channel_config, version_stats)

        if not patch or not patch.get("cinematic_hook_examples"):
            logger.warning("Analyzer returned empty patch for '%s' — skipping config update", channel)
            return

        # Backup + apply
        version = backup_channel_config(channel)
        avg_before = compute_avg_metrics(records)
        save_config_version(
            channel=channel,
            version=version,
            triggered_by=patch.get("triggered_by", []),
            avg_before=avg_before,
        )

        apply_config_patch(channel, {
            k: patch[k] for k in ("cinematic_hook_examples", "cinematic_story_example", "copy_voice_examples")
            if patch.get(k) is not None
        })

        # Write change log
        self._write_change_log(channel, version, patch, avg_before)
        logger.info(
            "Config updated for '%s' → version %s | reason: %s",
            channel, version, patch.get("reasoning", ""),
        )

    def _write_change_log(self, channel: str, version: str, patch: dict, avg_before: dict) -> None:
        from src.utils.feedback_store import CONFIG_HISTORY_ROOT
        dest_dir = CONFIG_HISTORY_ROOT / channel
        dest_dir.mkdir(parents=True, exist_ok=True)
        log_path = dest_dir / f"config_{version}_changes.md"
        with open(log_path, "w") as f:
            f.write(f"# Config Update — {channel} @ {version}\n\n")
            f.write(f"**Reasoning:** {patch.get('reasoning', '')}\n\n")
            f.write(f"**Triggered by:** {patch.get('triggered_by', [])}\n\n")
            f.write(f"**Avg before:** reach={avg_before.get('reach', 0):.0f} "
                    f"hook_quality={avg_before.get('hook_quality', 0):.1f} "
                    f"likes={avg_before.get('likes', 0):.1f}\n\n")
            f.write("## Changes\n\n")
            for key in ("cinematic_hook_examples", "cinematic_story_example", "copy_voice_examples"):
                if patch.get(key):
                    f.write(f"### {key}\n```\n{patch[key]}\n```\n\n")
