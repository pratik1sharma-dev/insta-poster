"""
Feedback store — SQLite data layer for the learning feedback loop.

All functions open/close their own connection (safe for concurrent pipeline + service use).
WAL mode is enabled for reliable concurrent writes.
"""
import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

DB_PATH = Path("output/feedback/feedback.db")
CONFIG_HISTORY_ROOT = Path("output/feedback/config_history")
CHANNELS_YAML = Path("src/config/channels.yaml")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_POSTS = """
CREATE TABLE IF NOT EXISTS posts (
    record_id       TEXT PRIMARY KEY,
    post_id         TEXT,
    channel         TEXT NOT NULL,
    posted_at       TEXT NOT NULL,
    post_type       TEXT,
    config_version  TEXT,
    topic           TEXT,
    angle           TEXT,
    hook_type       TEXT,
    hook_text       TEXT,
    story_spine     TEXT,
    visual_anchor   TEXT,
    cinematic_path  TEXT,
    like_count      INTEGER,
    comments_count  INTEGER,
    saved           INTEGER,
    reach           INTEGER,
    fetched_at      TEXT,
    hook_quality    REAL,
    story_clarity   REAL,
    visual_quality  REAL,
    scoring_notes   TEXT,
    scored_at       TEXT
)
"""

_CREATE_CONFIG_VERSIONS = """
CREATE TABLE IF NOT EXISTS config_versions (
    version             TEXT PRIMARY KEY,
    channel             TEXT NOT NULL,
    applied_at          TEXT NOT NULL,
    triggered_by        TEXT,
    avg_likes_before    REAL,
    avg_saves_before    REAL,
    avg_reach_before    REAL,
    avg_hook_quality_before REAL,
    avg_likes_after     REAL,
    avg_saves_after     REAL,
    avg_reach_after     REAL,
    avg_hook_quality_after REAL
)
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    with _connect() as conn:
        conn.execute(_CREATE_POSTS)
        conn.execute(_CREATE_CONFIG_VERSIONS)
        conn.commit()


# ---------------------------------------------------------------------------
# Post records
# ---------------------------------------------------------------------------

def record_post(
    post_result,
    post_type: str,
    config_version: str,
    hook_text: Optional[str] = None,
    story_spine: Optional[str] = None,
    visual_anchor: Optional[str] = None,
    cinematic_path: Optional[str] = None,
) -> str:
    """Insert a new post record. Returns the record_id."""
    now = datetime.now(timezone.utc)
    record_id = f"{post_result.channel}_{now.strftime('%Y%m%d_%H%M%S')}"

    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO posts
               (record_id, post_id, channel, posted_at, post_type, config_version,
                topic, angle, hook_type, hook_text, story_spine, visual_anchor, cinematic_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record_id,
                post_result.post_id,
                post_result.channel,
                now.isoformat(),
                post_type,
                config_version,
                post_result.strategy.topic if post_result.strategy else None,
                post_result.strategy.angle if post_result.strategy else None,
                str(post_result.strategy.hook_type) if post_result.strategy else None,
                hook_text,
                story_spine,
                visual_anchor,
                cinematic_path,
            ),
        )
        conn.commit()
    logger.info("Feedback record created: %s", record_id)
    return record_id


def get_pending_fetch(channel: str, delay_hours: int = 24) -> list[dict]:
    """Return posts where metrics haven't been fetched yet and delay_hours have passed."""
    cutoff = datetime.now(timezone.utc).timestamp() - delay_hours * 3600
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE channel = ? AND fetched_at IS NULL AND posted_at < ?""",
            (channel, cutoff_iso),
        ).fetchall()
    return [dict(r) for r in rows]


def update_post_metrics(
    record_id: str,
    like_count: int,
    comments_count: int,
    saved: int,
    reach: int,
    fetched_at: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE posts SET like_count=?, comments_count=?, saved=?, reach=?, fetched_at=?
               WHERE record_id=?""",
            (like_count, comments_count, saved, reach, fetched_at, record_id),
        )
        conn.commit()


def update_post_scores(
    record_id: str,
    hook_quality: float,
    story_clarity: float,
    visual_quality: float,
    scoring_notes: str,
    scored_at: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE posts SET hook_quality=?, story_clarity=?, visual_quality=?,
               scoring_notes=?, scored_at=? WHERE record_id=?""",
            (hook_quality, story_clarity, visual_quality, scoring_notes, scored_at, record_id),
        )
        conn.commit()


def get_scored_since(channel: str, since_iso: str) -> list[dict]:
    """Return scored posts for channel posted after since_iso."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE channel = ? AND scored_at IS NOT NULL AND posted_at > ?
               ORDER BY posted_at ASC""",
            (channel, since_iso),
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_config_version(channel: str) -> Optional[str]:
    """Return the version string of the latest config_version entry for this channel."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT version FROM config_versions WHERE channel = ?
               ORDER BY applied_at DESC LIMIT 1""",
            (channel,),
        ).fetchone()
    return row["version"] if row else None


def get_version_applied_at(channel: str, version: Optional[str]) -> Optional[str]:
    if not version:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT applied_at FROM config_versions WHERE channel = ? AND version = ?",
            (channel, version),
        ).fetchone()
    return row["applied_at"] if row else None


# ---------------------------------------------------------------------------
# Config versions
# ---------------------------------------------------------------------------

def save_config_version(
    channel: str,
    version: str,
    triggered_by: list[str],
    avg_before: dict,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO config_versions
               (version, channel, applied_at, triggered_by,
                avg_likes_before, avg_saves_before, avg_reach_before, avg_hook_quality_before)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                version,
                channel,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(triggered_by),
                avg_before.get("likes"),
                avg_before.get("saves"),
                avg_before.get("reach"),
                avg_before.get("hook_quality"),
            ),
        )
        conn.commit()


def update_config_version_after(channel: str, version: str, avg_after: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE config_versions SET
               avg_likes_after=?, avg_saves_after=?, avg_reach_after=?, avg_hook_quality_after=?
               WHERE channel = ? AND version = ?""",
            (
                avg_after.get("likes"),
                avg_after.get("saves"),
                avg_after.get("reach"),
                avg_after.get("hook_quality"),
                channel,
                version,
            ),
        )
        conn.commit()


def get_config_version_stats(channel: str) -> list[dict]:
    """Return all config_versions for channel ordered by applied_at."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM config_versions WHERE channel = ? ORDER BY applied_at ASC",
            (channel,),
        ).fetchall()
    return [dict(r) for r in rows]


def compute_avg_metrics(records: list[dict]) -> dict:
    """Compute averages from a list of post record dicts."""
    def _avg(key):
        vals = [r[key] for r in records if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "likes": _avg("like_count"),
        "saves": _avg("saved"),
        "reach": _avg("reach"),
        "hook_quality": _avg("hook_quality"),
        "visual_quality": _avg("visual_quality"),
    }


# ---------------------------------------------------------------------------
# Config backup + patch
# ---------------------------------------------------------------------------

def backup_channel_config(channel: str) -> str:
    """
    Copy channels.yaml to config_history/{channel}/config_{version}.yaml.
    Returns the version string (timestamp).
    """
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = CONFIG_HISTORY_ROOT / channel
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"config_{version}.yaml"
    shutil.copy2(str(CHANNELS_YAML), str(dest))
    logger.info("Config backed up to %s", dest)
    return version


def apply_config_patch(channel: str, patch: dict) -> None:
    """
    Update only the specified fields of the given channel in channels.yaml.
    Preserves all other channels and fields untouched.
    """
    with open(CHANNELS_YAML, "r") as f:
        all_configs = yaml.safe_load(f)

    if channel not in all_configs:
        raise KeyError(f"Channel '{channel}' not found in channels.yaml")

    for key, value in patch.items():
        if value is None:
            continue
        # LLM occasionally returns lists instead of strings — coerce to string
        if isinstance(value, list):
            value = "\n".join(str(item) for item in value)
            logger.warning("apply_config_patch: field '%s' was a list — coerced to string", key)
        if not isinstance(value, str):
            logger.warning("apply_config_patch: field '%s' has unexpected type %s — skipping", key, type(value).__name__)
            continue
        all_configs[channel][key] = value

    with open(CHANNELS_YAML, "w") as f:
        yaml.dump(all_configs, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info("Config patch applied for channel '%s': keys=%s", channel, list(patch.keys()))
