"""
Feedback Analyzer — LLM agent that analyzes post performance and generates
a config patch to improve the channel's content quality over time.
"""
import json
import logging
from typing import Optional

from src.agents.content_generator import ContentGenerator
from src.config import settings
from src.models import ChannelConfig

logger = logging.getLogger(__name__)


class FeedbackAnalyzer:
    """
    Analyzes scored post records and generates a channels.yaml config patch.

    Returns a dict with updated values for:
      - cinematic_hook_examples
      - cinematic_story_example  (None = no change needed)
      - copy_voice_examples
      - reasoning
      - triggered_by (list of record_ids)
    """

    # Max chars for each existing config field shown in the prompt.
    _MAX_FIELD_CHARS = 400

    def __init__(self):
        self.generator = ContentGenerator()

    def _generate_text(self, prompt: str, system_prompt: str) -> str:
        """Generate text using the high-TPM research model to avoid 413 errors."""
        if settings.llm_provider == "groq" and settings.groq_api_key:
            from groq import Groq
            client = Groq(api_key=settings.groq_api_key)
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            completion = client.chat.completions.create(
                model=settings.groq_research_model,
                messages=messages,
                temperature=0.4,
                max_tokens=1024,
            )
            return completion.choices[0].message.content
        # Fallback to ContentGenerator for other providers
        return self.generator._generate_text(prompt, system_prompt=system_prompt)

    def analyze(
        self,
        channel: str,
        records: list[dict],
        channel_config: ChannelConfig,
        config_version_stats: Optional[list[dict]] = None,
    ) -> dict:
        """
        Analyze post performance records and return a config patch dict.

        records: list of post dicts with social metrics + AI scores
        config_version_stats: historical config versions with avg_before/after
        """
        if not records:
            return {}

        avg_likes = sum(r.get("like_count") or 0 for r in records) / len(records)

        # Build a compact performance table for the LLM
        table_rows = []
        for r in records:
            table_rows.append(
                f"- [{r['record_id']}] {r.get('topic', '')} | "
                f"hook: {r.get('hook_text', '')[:60]} | "
                f"reach={r.get('reach') or 0} likes={r.get('like_count') or 0} "
                f"saves={r.get('saved') or 0} | "
                f"hook_quality={r.get('hook_quality') or 'n/a'} "
                f"visual_quality={r.get('visual_quality') or 'n/a'} "
                f"story_clarity={r.get('story_clarity') or 'n/a'} | "
                f"notes: {(r.get('scoring_notes') or '')[:80]}"
            )
        performance_table = "\n".join(table_rows)

        # Config version history (if available)
        version_history = ""
        if config_version_stats:
            lines = []
            for v in config_version_stats[-5:]:  # last 5 versions
                before = f"reach={v.get('avg_reach_before') or 0:.0f} hook={v.get('avg_hook_quality_before') or 0:.1f}"
                after = f"reach={v.get('avg_reach_after') or 0:.0f} hook={v.get('avg_hook_quality_after') or 0:.1f}" if v.get("avg_reach_after") else "pending"
                lines.append(f"  {v['version']}: before=[{before}] after=[{after}]")
            version_history = "CONFIG VERSION HISTORY:\n" + "\n".join(lines)

        # Maturity note — key for new channels with zero engagement
        if avg_likes < 5:
            maturity_note = (
                f"CHANNEL MATURITY: NEW (avg likes={avg_likes:.1f}, channel has no followers yet).\n"
                "Weight AI scores (hook_quality, visual_quality, story_clarity) as the primary signal.\n"
                "Treat reach (views) as secondary. Likes/saves will be near-zero — this is normal.\n"
            )
        elif avg_likes < 50:
            maturity_note = f"CHANNEL MATURITY: GROWING (avg likes={avg_likes:.1f}). Weight reach + saves alongside AI scores.\n"
        else:
            maturity_note = f"CHANNEL MATURITY: ACTIVE (avg likes={avg_likes:.1f}). Weight likes + saves + reach.\n"

        system_prompt = (
            f"You are a content performance analyst for the Instagram channel '{channel}'.\n"
            "Your job: improve the channel config based on what actually performed well.\n"
            "You update example fields in the config to reflect the best-performing content patterns.\n"
            "Be specific — quote actual hook text and story structures from top performers.\n"
        )

        def _trunc(val: str | None) -> str:
            if not val:
                return "(not set)"
            return val[:self._MAX_FIELD_CHARS] + ("..." if len(val) > self._MAX_FIELD_CHARS else "")

        prompt = f"""CHANNEL: {channel}
{maturity_note}
{version_history}

CURRENT CONFIG VALUES:
cinematic_hook_examples:
{_trunc(channel_config.cinematic_hook_examples)}

cinematic_story_example:
{_trunc(channel_config.cinematic_story_example)}

copy_voice_examples:
{_trunc(channel_config.copy_voice_examples)}

PERFORMANCE DATA (most recent {len(records)} scored posts):
{performance_table}

TASK:
1. Identify the top-performing posts (highest hook_quality + reach).
2. Identify the bottom-performing posts (lowest hook_quality or reach).
3. Update cinematic_hook_examples: add 1-2 GOOD examples from top performers with their hook text. Mark 1 bottom performer as a pattern to AVOID.
4. Update copy_voice_examples: if a top performer used a notably effective copy style, add it as an example.
5. Update cinematic_story_example ONLY if a top performer had a significantly better story structure than the current example (otherwise set to null).

OUTPUT (JSON only):
{{
  "cinematic_hook_examples": "full updated value (preserve existing good examples, add new ones)",
  "cinematic_story_example": "full updated value OR null if no change needed",
  "copy_voice_examples": "full updated value OR null if no change needed",
  "reasoning": "1-2 sentences explaining what changed and why",
  "triggered_by": ["record_id_1", "record_id_2"]
}}

Respond with ONLY valid JSON."""

        response = self._generate_text(prompt, system_prompt=system_prompt)

        try:
            data = self.generator._parse_json_response(response)
        except Exception as e:
            logger.error("FeedbackAnalyzer: failed to parse LLM response: %s | raw: %s", e, response[:300])
            return {}

        return {
            "cinematic_hook_examples": data.get("cinematic_hook_examples"),
            "cinematic_story_example": data.get("cinematic_story_example"),
            "copy_voice_examples": data.get("copy_voice_examples"),
            "reasoning": data.get("reasoning", ""),
            "triggered_by": data.get("triggered_by", [r["record_id"] for r in records]),
        }
