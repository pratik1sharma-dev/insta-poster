"""
Story Architect - Plans narrative structure before slide generation.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from src.models import ContentStrategy, ChannelConfig
from src.models.story_models import StoryOutline, NarrativeBeat


logger = logging.getLogger(__name__)


class StoryArchitect:
    """Plans coherent narrative arcs for carousel content."""

    def __init__(self, generator_client):
        """Initialize with the LLM client from content generator."""
        self.generator = generator_client

    def plan_story(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        raw_output_dir: Optional[Path] = None,
    ) -> StoryOutline:
        """
        Generate narrative structure before writing slides.

        This ensures each slide builds logically on the previous one
        and data is used strategically rather than randomly.
        """

        system_prompt = f"""You are a Master Story Architect for {channel_config.name}.

Your expertise: Taking complex data and transforming it into a narrative that:
- Grabs attention with an unexpected truth
- Builds understanding through logical steps
- Creates an "aha!" moment of realization
- Ends with clear agency (what to do with this insight)

You think in story beats, not bullet points."""

        prompt = self._build_outline_prompt(strategy, channel_config)

        if raw_output_dir:
            try:
                with open(raw_output_dir / "story_prompt.txt", "w") as f:
                    f.write(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{prompt}")
            except Exception:
                pass

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)

        if raw_output_dir:
            try:
                with open(raw_output_dir / "story_outline_raw.txt", "w") as f:
                    f.write(response)
            except Exception:
                pass

        return self._parse_outline(response, strategy.carousel_length)

    def _build_outline_prompt(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
    ) -> str:
        """Build the story planning prompt."""

        data_block = ""
        if strategy.verified_data:
            data_block = f"""
### VERIFIED DATA AVAILABLE:
{strategy.verified_data}

You must distribute these data points strategically across beats.
Do NOT dump all data in one beat.
"""

        return f"""### CONTEXT:
Topic: {strategy.topic}
Angle: {strategy.angle}
Carousel Length: {strategy.carousel_length} slides
Hook Type: {strategy.hook_type}
Visual Theme: {strategy.visual_metaphor}
Target Audience: {channel_config.target_audience}

{data_block}

### YOUR TASK:
Plan a {strategy.carousel_length}-beat story that delivers ONE clear realization.

Think of this like a mini-documentary:
- Beat 1: The hook that breaks a pattern
- Beats 2-3: Build context ("here's why this happens")
- Beats 4-{strategy.carousel_length-2}: Develop the insight ("here's what this means")
- Beat {strategy.carousel_length-1}: Resolution ("here's what to do")
- Beat {strategy.carousel_length}: CTA (engagement question)

### STORY REQUIREMENTS:

1. **One Throughline**: Every beat must advance toward the same realization.
   No tangents, no "also here's an unrelated fact".

2. **Causal Progression**: Each beat should answer a question raised by the previous one.
   Example flow:
   - Beat 1: "X is bigger than Y" (creates surprise)
   - Beat 2: "Here's why X grew faster" (answers "how?")
   - Beat 3: "But there's a hidden cost" (tension)
   - Beat 4: "Here's what you should do" (resolution)

3. **Strategic Data Use**: Assign specific data points to specific beats.
   Use data to SUPPORT the story, not BE the story.

4. **Human Stake**: Every beat must answer "why does this matter to me?"

5. **Earned Resolution**: The final beats should feel inevitable, not tacked on.

### OUTPUT FORMAT (JSON):
{{
  "story_spine": "One sentence: What is the journey from beat 1 to beat {strategy.carousel_length}?",
  "throughline": "The connecting thread that makes each beat lead to the next",
  "audience_takeaway": "The one thing they'll remember tomorrow",
  "resolution_payoff": "Why the ending is satisfying",
  "narrative_beats": [
    {{
      "beat_number": 1,
      "purpose": "hook",
      "emotional_goal": "Create curiosity or surprise",
      "key_message": "The specific insight this beat delivers",
      "data_to_use": ["Data point #1", "Data point #3"],
      "transition_to_next": "The tension or question that leads to beat 2",
      "why_this_matters": "Human stake - why reader cares"
    }},
    // ... beats 2 through {strategy.carousel_length}
  ]
}}

### CRITICAL RULES:
- Every beat must logically follow from the previous
- No random pivots or "oh also here's another fact"
- Data should be distributed (not all in beats 2-3)
- The story must BUILD to something, not just list things
- Beat {strategy.carousel_length-1} must feel like a natural resolution

Generate the story outline now. Respond with ONLY valid JSON."""

    def _parse_outline(self, response_text: str, expected_beats: int) -> StoryOutline:
        """Parse LLM response into StoryOutline."""

        # Try to extract JSON
        import re
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(1)
        elif "{" in response_text:
            # Extract from first { to last }
            start = response_text.index("{")
            end = response_text.rindex("}") + 1
            response_text = response_text[start:end]

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse story outline: {e}")
            return self._get_default_outline(expected_beats)

        # Parse beats
        beats = []
        for beat_data in data.get("narrative_beats", []):
            beats.append(NarrativeBeat(
                beat_number=beat_data.get("beat_number", len(beats) + 1),
                purpose=beat_data.get("purpose", "content"),
                emotional_goal=beat_data.get("emotional_goal", ""),
                key_message=beat_data.get("key_message", ""),
                data_to_use=beat_data.get("data_to_use", []),
                transition_to_next=beat_data.get("transition_to_next"),
                why_this_matters=beat_data.get("why_this_matters"),
            ))

        return StoryOutline(
            story_spine=data.get("story_spine", "Default story spine"),
            throughline=data.get("throughline", "Default throughline"),
            narrative_beats=beats,
            resolution_payoff=data.get("resolution_payoff", ""),
            audience_takeaway=data.get("audience_takeaway", ""),
        )

    def _get_default_outline(self, num_beats: int) -> StoryOutline:
        """Fallback outline if parsing fails."""
        beats = []
        for i in range(1, num_beats + 1):
            purpose = "hook" if i == 1 else ("cta" if i == num_beats else "content")
            beats.append(NarrativeBeat(
                beat_number=i,
                purpose=purpose,
                emotional_goal="Default goal",
                key_message=f"Default message for beat {i}",
                data_to_use=[],
                transition_to_next=f"Leads to beat {i+1}" if i < num_beats else None,
            ))

        return StoryOutline(
            story_spine="Default story structure due to parsing error",
            throughline="Sequential progression",
            narrative_beats=beats,
            resolution_payoff="Default resolution",
            audience_takeaway="Default takeaway",
        )
