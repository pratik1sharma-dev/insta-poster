import logging
from typing import List, Optional

from src.models import ContentStrategy, ChannelConfig
from src.agents.content_generator import ContentGenerator

logger = logging.getLogger(__name__)


class CinematicScriptGenerator:
    """
    Generates the scene script (lines + image prompts + motion) for a cinematic
    reel using a two-turn conversation session:

    Turn 1 — Hook generation: AI proposes 5 hook variants with scores.
    Turn 2 — Script generation: AI writes the full scene story, building
              naturally on the hooks it already produced in Turn 1.

    A single system prompt is set once and shared across both turns.
    """

    VALID_MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "static")

    MIN_LINES_REQUIRED = 4
    RECOMMENDED_MIN_LINES = 6
    MAX_CAPTION_WORDS = 16
    TRUNCATED_CAPTION_WORDS = 14

    _CAPTION_PREFIXES = (
        "here's the caption text:", "here's the caption:", "caption text:",
        "caption:", "text:", "line:", "slide:", "here's the text:",
    )

    def __init__(self, generator: ContentGenerator):
        self.generator = generator
        self.last_hook_text: str = ""
        self.last_story_spine: str = ""
        self.last_visual_anchor: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> List[dict]:
        """
        Generate a scenes-based story structure via a two-turn conversation.

        Each scene = 1 SD image + 1-3 text caption lines + a motion effect.
        Returns List[dict] where each dict has: lines, image_prompt, motion
        """
        return self._generate_script_and_prompts(strategy, channel_config, num_images)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        channel_config: ChannelConfig,
        currency_rule: str,
        copy_voice_section: str,
    ) -> str:
        character_section = ""
        if channel_config.character_description:
            character_section = (
                f"\nPROTAGONIST: This channel has a fixed character — {channel_config.character_description}.\n"
                "Every scene image must feature her as the main subject in a real-life situation.\n"
                "She is not named. The viewer becomes her.\n"
            )
        strategic_core_section = (
            f"\n{channel_config.strategic_core.strip()}\n"
            if getattr(channel_config, 'strategic_core', None) else ""
        )
        return (
            f"You are a content writer for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Target Audience: {channel_config.target_audience}\n"
            + (f"Cultural Context: {channel_config.cultural_context}\n" if channel_config.cultural_context else "")
            + (f"Brand Mission: {channel_config.brand_mission}\n" if channel_config.brand_mission else "")
            + character_section
            + strategic_core_section
            + f"{currency_rule}\n"
            + copy_voice_section
            + "Your goal: Explain one useful idea clearly across 3-5 short visual scenes.\n"
            "Priority: CLARITY and SIMPLICITY. Simple and direct beats dramatic and poetic every time.\n"
            "Write like you are explaining this to a friend — not writing a movie script.\n"
            "Each line must be immediately understood by someone with zero prior knowledge of the topic.\n"
            "End with one concrete action or takeaway the viewer can use today."
        )

    # ------------------------------------------------------------------
    # Turn 1 — Hook generation
    # ------------------------------------------------------------------

    def _hook_prompt(self, strategy: ContentStrategy, channel_config: ChannelConfig) -> str:
        verified_snippet = f"### VERIFIED DATA: {strategy.verified_data[:500]}" if strategy.verified_data else ""
        hook_examples_section = ""
        if getattr(channel_config, 'cinematic_hook_examples', None):
            hook_examples_section = (
                f"\n### THIS CHANNEL'S HOOK STYLE — follow this voice and format:\n"
                f"{channel_config.cinematic_hook_examples.strip()}\n"
                "Apply the generic patterns below through the lens of this channel's hook style.\n"
            )
        return f"""### TOPIC: {strategy.topic}
### ANGLE: {strategy.angle}
### TARGET AUDIENCE: {strategy.target_audience_insight}
{verified_snippet}
{hook_examples_section}
### YOUR TASK:
Generate 5 distinct hooks using proven psychological patterns. Score each one.

### HOOK PATTERNS:

**1. SHOCKING STATISTIC** — "[Specific number] [surprising fact]"
Psychology: Numbers + surprise = pattern interrupt

**2. CONTRARIAN STATEMENT** — "Everything you know about [X] is incomplete"
Psychology: Challenges existing belief = curiosity

**3. PATTERN INTERRUPT QUESTION** — "What if [opposite of common belief]?"
Psychology: Cognitive dissonance = engagement

**4. PERSONAL COST/BENEFIT** — "You are losing/gaining [specific outcome] by [action]"
Psychology: Self-interest + specificity = relevance

**5. STATUS QUO CHALLENGE** — "[Common action] is quietly [negative outcome]"
Psychology: Hidden danger + urgency = emotional trigger

### SCORING (rate each 0-10):
- **curiosity_gap**: Does it make them NEED to know what comes next?
- **relevance**: Does it feel personal to THIS audience?
- **emotional_trigger**: Does it create fear, desire, anger, or shock?

### REQUIREMENTS:
- Match this channel's hook style (see above if provided)
- Keep hooks under 14 words
- Must be immediately understandable with ZERO prior context
- Each hook must use a DIFFERENT pattern
- If comparing two numbers, state WHAT causes the difference in the hook itself
  BAD: "₹42 lakh in 7 years—but ₹28 crore by 60?"
  GOOD: "Same ₹3,000 SIP: ₹42 lakh at 29, ₹28 crore at 60"

### OUTPUT (JSON only):
{{
  "hooks": [
    {{
      "hook": "The actual hook text (8-14 words)",
      "pattern": "shocking_statistic | contrarian_statement | pattern_interrupt | personal_cost | status_quo_challenge",
      "curiosity_gap": 0-10,
      "relevance": 0-10,
      "emotional_trigger": 0-10,
      "reasoning": "Why this hook works for this audience (1 sentence)"
    }}
  ]
}}

Respond with ONLY valid JSON."""

    def _score_hooks(self, hook_response: str, topic: str, angle: str) -> dict:
        """Parse hook JSON from Turn 1 and return scored result."""
        try:
            data = self.generator._parse_json_response(hook_response)
            hooks = data.get("hooks", [])

            if not hooks:
                return self._fallback_hook(topic, angle)

            scored = []
            for h in hooks:
                curiosity = int(h.get("curiosity_gap", 5))
                relevance = int(h.get("relevance", 5))
                emotional = int(h.get("emotional_trigger", 5))
                # Emotional triggers matter most for scroll-stopping
                total = curiosity * 0.3 + relevance * 0.35 + emotional * 0.35
                scored.append({
                    'hook': h.get("hook", ""),
                    'pattern': h.get("pattern", "unknown"),
                    'curiosity_gap': curiosity,
                    'relevance': relevance,
                    'emotional_trigger': emotional,
                    'total_score': round(total, 2),
                    'reasoning': h.get("reasoning", ""),
                })

            scored.sort(key=lambda x: x['total_score'], reverse=True)
            best = scored[0]

            logger.info("=" * 60)
            logger.info("HOOK VARIANTS (Turn 1):")
            logger.info("-" * 60)
            for i, v in enumerate(scored, 1):
                logger.info("%d. [%.1f] %s", i, v['total_score'], v['hook'])
                logger.info("   %s | C:%d R:%d E:%d | %s",
                            v['pattern'], v['curiosity_gap'], v['relevance'],
                            v['emotional_trigger'], v['reasoning'])
            logger.info("BEST: %s (%.1f)", best['hook'], best['total_score'])
            logger.info("=" * 60)

            return {'best_hook': best['hook'], 'best_score': best['total_score'],
                    'reasoning': best['reasoning'], 'all_variants': scored}

        except Exception as e:
            logger.error("Hook scoring failed: %s", e)
            return self._fallback_hook(topic, angle)

    def _fallback_hook(self, topic: str, angle: str) -> dict:
        hook = f"Here's what most people miss about {topic[:40]}"
        return {
            'best_hook': hook, 'best_score': 5.0,
            'reasoning': 'Fallback hook', 'all_variants': []
        }

    # ------------------------------------------------------------------
    # Turn 2 — Script generation
    # ------------------------------------------------------------------

    def _script_prompt(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        hook_result: dict,
        currency_rule: str,
        is_india: bool,
    ) -> str:
        best_hook = hook_result['best_hook']
        research_text = strategy.verified_data or ""
        is_character_channel = bool(channel_config.character_description)
        character_desc = channel_config.character_description or ""

        if is_character_channel:
            image_prompt_rules = f"""### SD IMAGE PROMPT RULES (CHARACTER CHANNEL):
- EVERY scene image must show the protagonist ({character_desc}) as the main subject
- Show her in a REAL situation: sitting, standing, walking, working, resting — not posing
- NEVER feature hands as the main close-up subject
- NEVER show screens, dashboards, or readable text in the image
- Shot variety to match emotional beat:
  - Close-up / extreme close-up → emotional intensity, inner conflict
  - Medium shot → everyday action, interaction
  - Wide shot → isolation, freedom, scale
- Describe the LOCATION and LIGHTING specifically (cafe, office, apartment, street — golden hour, soft lamp, blue dusk)
- Do NOT repeat the same location across all scenes"""
        else:
            image_prompt_rules = """### SD IMAGE PROMPT RULES:
- NEVER feature hands as the main close-up subject
- NEVER render screen content (dashboards, numbers on screen)
- Show DEVICE/OBJECT in context (laptop on desk, phone on table)
- One recurring visual element across ALL scenes for continuity
- Shot variety: Extreme close-up / Close-up / Medium / Wide"""

        story_example_section = ""
        if getattr(channel_config, 'cinematic_story_example', None):
            story_example_section = (
                f"\n### CHANNEL STORY EXAMPLE — match this structure, tone, and final beat style:\n"
                f"{channel_config.cinematic_story_example.strip()}\n"
            )
        return f"""Great. Now write the full cinematic story using your best hook.

### BEST HOOK: "{best_hook}"
Use this exactly as Scene 1, Line 1 — no rewording.

### VERIFIED DATA (use these facts):
{research_text}
{story_example_section}
### YOUR TASK:
Create a 3-5 scene cinematic story. Total 6-12 caption lines across all scenes.
Target duration: 30-60 seconds (each line ~4-5 seconds on screen).

The story must:
1. **Open with the hook above** as Scene 1, Line 1 — word for word
2. **Build logically** — each line follows naturally from the previous
3. **Use concrete specifics** — real scenarios and numbers where appropriate for this channel
4. **Stay focused** — every line serves the single core insight
5. **End with the final beat** — last line is one specific, concrete action or moment true to this channel's voice. Follow your channel story example for what this looks like.
{currency_rule}
### SCENE DESIGN:
- Group related narrative beats into the same scene (same location/setting)
- Scene breaks = visual shift (new setting, new moment in time, new perspective)
- Prefer 2 lines per scene; 1 line only for a punchline moment
- Motion effect: pick what serves the emotional moment

### LINE RULES (8-14 words each):
- Simple and direct. If it sounds like a movie trailer, rewrite it.
- One idea per line. If a line needs to be explained, it failed — rewrite it.
- No metaphors, no jargon, no abstract concepts ("weaponize", "unlock", "journey", "signal")
- Conversational — like texting a smart friend, not writing an essay
- Specific situations and facts, not general observations about life

{image_prompt_rules}

### MOTION EFFECTS:
- **zoom_in**: builds tension, draws viewer in
- **zoom_out**: reveals full picture, sense of scale
- **pan_left / pan_right**: movement through time or contrast
- **static**: weight and stillness for punchline moments

### OUTPUT (JSON only):
{{
  "visual_anchor": "The ONE element appearing in all scene images",
  "story_spine": "One sentence: what does this story teach?",
  "scenes": [
    {{
      "lines": ["Line 1", "Line 2"],
      "image_prompt": "Medium shot of [subject], [lighting], [mood], cinematic",
      "motion": "zoom_in"
    }}
  ]
}}

### CHECKLIST:
- [ ] Scene 1 Line 1 is exactly the hook above (no rewording)
- [ ] Each line follows logically from the previous
- [ ] Numbers from VERIFIED DATA only
- [ ] Last line is a topic-specific action, not generic
- [ ] 3-5 scenes, 6-10 lines total (minimum 4)
- [ ] No "Caption:", "Line X:", or similar prefixes in lines
{f'- [ ] All monetary values in ₹/lakh/crore (NO $)' if is_india else ''}

Respond with ONLY valid JSON."""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_story_coherence(self, lines: List[str], story_spine: str) -> None:
        abstract_keywords = [
            'illusion', 'mirror', 'mask', 'journey', 'destination',
            'perception', 'construct', 'authentic', 'identity'
        ]
        abstract_count = 0
        for line in lines:
            line_lower = line.lower()
            for keyword in abstract_keywords:
                if keyword in line_lower:
                    abstract_count += 1
                    logger.warning("⚠️  Abstract language: '%s' in '%s'", keyword, line)

        if abstract_count >= 2:
            logger.warning("⚠️  Story may be too abstract.")

        if not any(char.isdigit() for line in lines for char in line):
            logger.warning("⚠️  No specific numbers found.")

        for i, line in enumerate(lines, 1):
            wc = len(line.split())
            if wc < 5:
                logger.warning("⚠️  Line %d too short (%d words): %s", i, wc, line)
            elif wc > self.MAX_CAPTION_WORDS:
                logger.warning("⚠️  Line %d too long (%d words): %s", i, wc, line)

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> List[dict]:
        if not strategy.verified_data or len(strategy.verified_data) < 100:
            logger.warning(
                "No verified research data for '%s' — proceeding with best-effort script (no sourced numbers).",
                strategy.topic,
            )

        is_india = getattr(channel_config, 'localization_type', 'global').lower() == 'india'
        currency_rule = (
            "\n### CURRENCY (CRITICAL): India-targeted channel. "
            "Use ONLY ₹, lakh, crore. NEVER $, USD, or Western units.\n"
            if is_india else ""
        )
        copy_voice_section = (
            f"\n{channel_config.copy_voice_examples.strip()}\n"
            if channel_config.copy_voice_examples else ""
        )

        # Single system prompt shared across both turns
        system_prompt = self._build_system_prompt(channel_config, currency_rule, copy_voice_section)
        logger.info("Cinematic system prompt set for '%s'", channel_config.name)

        # ── Turn 1: Hook generation ────────────────────────────────────
        messages = [{"role": "user", "content": self._hook_prompt(strategy, channel_config)}]
        hook_response = self.generator._generate_conversation(messages, system_prompt=system_prompt)
        logger.debug("Hook response (Turn 1): %s", hook_response)

        hook_result = self._score_hooks(hook_response, strategy.topic, strategy.angle)

        # ── Turn 2: Script generation ──────────────────────────────────
        messages.append({"role": "assistant", "content": hook_response})
        messages.append({"role": "user", "content": self._script_prompt(
            strategy, channel_config, hook_result, currency_rule, is_india
        )})
        script_response = self.generator._generate_conversation(messages, system_prompt=system_prompt)
        logger.debug("Script response (Turn 2): %s", script_response)

        # ── Parse scenes ───────────────────────────────────────────────
        data = self.generator._parse_json_response(script_response)
        scenes_raw = data.get("scenes", [])
        visual_anchor = data.get("visual_anchor", "subject")
        story_spine = data.get("story_spine", strategy.topic)

        if not scenes_raw or len(scenes_raw) < 2:
            raise RuntimeError(
                f"Script generation returned too few scenes ({len(scenes_raw)}). "
                f"Raw: {script_response[:300]}"
            )

        scenes = []
        for i, s in enumerate(scenes_raw):
            raw_lines = s.get("lines", [])
            if not raw_lines:
                raise RuntimeError(f"Scene {i+1} has no lines. Raw: {script_response[:300]}")

            trimmed_lines = []
            for line in raw_lines:
                line = str(line).strip()
                lower = line.lower()
                for prefix in self._CAPTION_PREFIXES:
                    if lower.startswith(prefix):
                        line = line[len(prefix):].strip()
                        break
                words = line.split()
                if len(words) > self.MAX_CAPTION_WORDS:
                    line = " ".join(words[:self.TRUNCATED_CAPTION_WORDS]) + "..."
                if line:
                    trimmed_lines.append(line)

            image_prompt = str(s.get("image_prompt", ""))

            motion = str(s.get("motion", "zoom_in")).lower()
            if motion not in self.VALID_MOTIONS:
                motion = "zoom_in"

            scenes.append({"lines": trimmed_lines, "image_prompt": image_prompt, "motion": motion, "visual_anchor": visual_anchor})

        all_lines_flat = [l for sc in scenes for l in sc["lines"]]

        logger.info("=" * 60)
        logger.info("GENERATED CINEMATIC STORY:")
        logger.info("STORY SPINE: %s", story_spine)
        logger.info("VISUAL ANCHOR: %s", visual_anchor)
        logger.info("SCENES: %d | TOTAL LINES: %d", len(scenes), len(all_lines_flat))
        logger.info("-" * 60)
        for i, sc in enumerate(scenes, 1):
            logger.info("SCENE %d [%s]:", i, sc["motion"])
            for j, line in enumerate(sc["lines"], 1):
                logger.info("  Line %d: %s", j, line)
            logger.info("  IMAGE: %s...", sc["image_prompt"][:120])
            logger.info("")
        logger.info("=" * 60)

        if len(all_lines_flat) < self.MIN_LINES_REQUIRED:
            raise RuntimeError(
                f"Story has only {len(all_lines_flat)} lines "
                f"(minimum {self.MIN_LINES_REQUIRED}). Raw: {script_response[:300]}"
            )
        if len(all_lines_flat) < self.RECOMMENDED_MIN_LINES:
            logger.warning(
                "Story has %d lines (recommended %d+). Reel ~%ds — short but acceptable.",
                len(all_lines_flat), self.RECOMMENDED_MIN_LINES, len(all_lines_flat) * 5
            )

        self._validate_story_coherence(all_lines_flat, story_spine)

        self.last_hook_text = hook_result.get('best_hook', '')
        self.last_story_spine = story_spine
        self.last_visual_anchor = visual_anchor

        return scenes
