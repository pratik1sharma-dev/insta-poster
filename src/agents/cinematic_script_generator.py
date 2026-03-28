import logging
import re
from typing import List, Tuple

from src.models import ContentStrategy, ChannelConfig
from src.agents.content_generator import ContentGenerator

logger = logging.getLogger(__name__)


class CinematicScriptGenerator:
    """
    Responsible for generating the scene script (lines + image prompts + motion)
    for a cinematic reel. Extracted from CinematicReelGenerator so that the
    script-generation concern lives independently of video/image rendering.
    """

    STORY_FORMATS = {
        'contrast': {
            'structure': ['setup', 'context', 'insight', 'takeaway'],
            'description': 'Compare two approaches showing difference',
            'best_for': 'financial comparisons, decision frameworks'
        },
        'timeline': {
            'structure': ['past', 'inflection', 'present', 'future'],
            'description': 'Historical progression to future prediction',
            'best_for': 'market trends, technological evolution'
        },
        'myth_buster': {
            'structure': ['common_belief', 'why_it_exists', 'the_truth', 'what_to_do'],
            'description': 'Debunk misconception with evidence',
            'best_for': 'investment myths, behavioral psychology'
        },
        'case_study': {
            'structure': ['situation', 'decision', 'outcome', 'lesson'],
            'description': 'Real example with concrete results',
            'best_for': 'success stories, cautionary tales'
        }
    }

    def __init__(self, generator: ContentGenerator):
        self.generator = generator

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
        Generate a scenes-based story structure.

        Each scene = 1 SD image + 1-3 text caption lines + a motion effect.
        The AI decides how many scenes (3-5) and how many lines per scene (1-3).
        Total lines across all scenes: 6-12, targeting a ~30-60 second reel.

        Returns List[dict] where each dict has: lines, image_prompt, motion
        """
        return self._generate_script_and_prompts(strategy, channel_config, num_images)

    # ------------------------------------------------------------------
    # Story Validation
    # ------------------------------------------------------------------

    def _validate_data_usage(
        self,
        generated_lines: List[str],
        research_numbers: List[str],
        verified_data: str,
        story_format: str = "contrast",
    ) -> None:
        """
        Transparency log: show what numbers the story used alongside the research.

        Regex matching cannot reliably catch semantic fabrications (inverted values,
        derived percentages from absolutes, etc.) and produces too many false positives
        on legitimate values (statutory rates, rounded equivalents, illustrative examples).

        The LLM prompt is the primary defence ("use ONLY numbers from VERIFIED DATA").
        This method just logs what was used so a human can spot-check before publishing.
        """
        all_story_numbers = []
        for line in generated_lines:
            all_story_numbers.extend(
                re.findall(r'[\d,\.]+\s*(?:crore|lakh|million|billion|%|₹|\$)', line)
            )

        if not all_story_numbers:
            logger.info("✓ Story contains no financial figures")
            return

        logger.info("=" * 60)
        logger.info("STORY NUMBERS USED (spot-check against research):")
        logger.info("  Story used: %s", all_story_numbers)
        logger.info("  Research had: %s", research_numbers[:15])
        logger.info("=" * 60)

    def _validate_story_coherence(self, lines: List[str], story_spine: str) -> None:
        """Basic validation to check if story makes sense."""

        # Check for abstract/philosophical keywords that indicate poor storytelling
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
                    logger.warning(f"⚠️  Abstract language detected: '{keyword}' in '{line}'")

        if abstract_count >= 2:
            logger.warning("⚠️  Story may be too abstract. Consider more concrete examples.")

        # Check for numbers (good sign of concrete storytelling)
        has_numbers = any(char.isdigit() for line in lines for char in line)
        if not has_numbers:
            logger.warning("⚠️  No specific numbers found. Story may lack concrete examples.")

        # Check word count consistency
        for i, line in enumerate(lines, 1):
            word_count = len(line.split())
            if word_count < 5:
                logger.warning(f"⚠️  Line {i} too short ({word_count} words): {line}")
            elif word_count > 16:
                logger.warning(f"⚠️  Line {i} too long ({word_count} words): {line}")

    # ------------------------------------------------------------------
    # Channel-Dependent Helpers
    # ------------------------------------------------------------------

    def _get_hook_examples_for_channel(self, channel_config: ChannelConfig) -> str:
        """Return channel-appropriate hook examples for the 5 patterns."""
        name = channel_config.name.lower()
        theme = channel_config.theme.lower()

        if "fertility" in name or "health" in theme:
            return (
                'SHOCKING_STATISTIC: "In nearly half of infertility cases, the factor is male. Nobody talks about it."\n'
                'CONTRARIAN: "Everything your family told you about fertility is missing the full picture"\n'
                'PATTERN_INTERRUPT: "What if the advice you are following is making it harder?"\n'
                'PERSONAL_COST: "Most couples wait 2 years before getting tested. That gap changes outcomes."\n'
                'STATUS_QUO_CHALLENGE: "Standard fertility advice is based on population averages. Your body is not average."'
            )
        elif "book" in name or "page" in name or "book" in theme or "read" in theme:
            return (
                'SHOCKING_STATISTIC: "93% of self-help books are forgotten within 2 weeks of finishing"\n'
                'CONTRARIAN: "Reading more is not making you more productive"\n'
                'PATTERN_INTERRUPT: "What if the best lesson in this book is not the one everyone quotes?"\n'
                'PERSONAL_COST: "You are losing 3 deep work hours daily to habits you think are helping"\n'
                'STATUS_QUO_CHALLENGE: "Highlighting is quietly killing your retention"'
            )
        elif "startup" in name or "founder" in theme:
            return (
                'SHOCKING_STATISTIC: "9 in 10 Indian startups fail before raising a Series A"\n'
                'CONTRARIAN: "Your startup idea is not your biggest risk"\n'
                'PATTERN_INTERRUPT: "What if your strongest conviction is your biggest blind spot?"\n'
                'PERSONAL_COST: "First-time founders overpay for growth before finding PMF"\n'
                'STATUS_QUO_CHALLENGE: "Hiring fast is quietly destroying your startup culture"'
            )
        elif "psych" in name or "mind" in name or "psych" in theme:
            return (
                'SHOCKING_STATISTIC: "Your brain decides 7 seconds before you consciously choose. That feeling of choice? Reconstructed."\n'
                'CONTRARIAN: "Being rational is not as helpful as you think"\n'
                'PATTERN_INTERRUPT: "What if your most confident decisions are the most biased?"\n'
                'PERSONAL_COST: "The sunk cost fallacy costs people 2-3 years of misallocated effort on average"\n'
                'STATUS_QUO_CHALLENGE: "Believing you are logical is the most reliable predictor of bias"'
            )
        elif "rank" in name or "world" in name or "ranking" in theme:
            return (
                'SHOCKING_STATISTIC: "The world spent $2.3 trillion on clean energy in 2024. Emissions still went up."\n'
                'CONTRARIAN: "The country ranked first by GDP is not the one growing fastest"\n'
                'PATTERN_INTERRUPT: "What if the metric everyone uses to rank countries is misleading?"\n'
                'PERSONAL_COST: "India ranks 132nd in this measure. Higher than most expect."\n'
                'STATUS_QUO_CHALLENGE: "The list you think you know looks very different when you change one variable"'
            )
        else:
            # Default / financial (wealthcapsules)
            return (
                'SHOCKING_STATISTIC: "₹7.5 crore lost because of one word: safe"\n'
                'CONTRARIAN: "Your safe investments are the riskiest bet"\n'
                'PATTERN_INTERRUPT: "What if playing it safe made you poor?"\n'
                'PERSONAL_COST: "Every FD costs you ₹2.3 lakh per year in real returns"\n'
                'STATUS_QUO_CHALLENGE: "Fixed deposits are quietly bankrupting your future"'
            )

    def _get_story_example_for_channel(self, channel_config: ChannelConfig) -> str:
        """Return a channel-appropriate story example for the script prompt."""
        name = channel_config.name.lower()
        theme = channel_config.theme.lower()

        if "fertility" in name or "health" in theme:
            return """### GOOD STORY EXAMPLE (myth_buster format):

Scene 1 [zoom_in]:
  - "Everyone says stress is why you are not getting pregnant"
  - "Doctors hear it from families. Patients hear it from friends."
Scene 2 [pan_right]:
  - "The research tells a different story"
  - "Stress is a factor. It is rarely the only one."
Scene 3 [zoom_out]:
  - "In nearly 50% of cases, there is a measurable physical cause"
  - "And half of those are on the male side"
Scene 4 [zoom_in]:
  - "The first step: a full workup for both partners, not just one"
"""
        elif "book" in name or "page" in name or "book" in theme or "read" in theme:
            return """### GOOD STORY EXAMPLE (contrast format):

Scene 1 [zoom_in]:
  - "You highlight the good parts. You feel productive."
  - "Two weeks later, you cannot remember a single line."
Scene 2 [pan_right]:
  - "Highlighting is comfortable. But comfort is not learning."
Scene 3 [zoom_out]:
  - "The readers who retain most do something different"
  - "They write one sentence: what does this change for me?"
Scene 4 [zoom_in]:
  - "Close the book. Write one sentence now. That is the whole system."
"""
        elif "startup" in name or "founder" in theme:
            return """### GOOD STORY EXAMPLE (case_study format):

Scene 1 [zoom_in]:
  - "Zerodha launched in 2010. No VC money. No marketing budget."
  - "Just a product that solved a real problem."
Scene 2 [pan_right]:
  - "Their first customers told 10 more. Those told 10 more."
Scene 3 [zoom_out]:
  - "By 2019 they were profitable. No dilution. No pressure."
  - "Today: India's largest broker by active users."
Scene 4 [zoom_in]:
  - "The lesson: distribution follows product quality. Not the other way around."
"""
        elif "psych" in name or "mind" in name or "psych" in theme:
            return """### GOOD STORY EXAMPLE (myth_buster format):

Scene 1 [zoom_in]:
  - "You stayed in the job longer than you should have"
  - "Not because you wanted to. Because you already gave 3 years."
Scene 2 [pan_right]:
  - "That is the sunk cost fallacy. It is not a flaw."
  - "It is your brain doing exactly what evolution built it to do."
Scene 3 [zoom_out]:
  - "Losses feel twice as painful as equivalent gains feel good"
  - "Your brain is not broken. It is protecting you from perceived loss."
Scene 4 [zoom_in]:
  - "The fix: ask one question before staying. What would I do if I started fresh today?"
"""
        elif "rank" in name or "world" in name or "ranking" in theme:
            return """### GOOD STORY EXAMPLE (timeline format):

Scene 1 [zoom_in]:
  - "In 2010, China's economy was half the size of America's"
  - "Most economists said it would take 50 years to close the gap"
Scene 2 [pan_right]:
  - "By 2023, it was at 65%. The gap closed in 13 years."
Scene 3 [zoom_out]:
  - "But here is the number nobody talks about"
  - "GDP per person in China is still 6x lower than the US"
Scene 4 [zoom_in]:
  - "One number tells you a country's total output. The other tells you how it feels to live there."
"""
        else:
            # Default / financial
            return """### GOOD STORY EXAMPLE (contrast format):

Scene 1 [zoom_in]:
  - "Rohan kept ₹5,000/month in FD since age 25"
  - "Safe, guaranteed, parent-approved"
Scene 2 [pan_right]:
  - "His cousin started a SIP in Nifty 50 instead"
Scene 3 [zoom_out]:
  - "At 60, Rohan: ₹42L. Cousin: ₹2.3 crore"
  - "Same ₹5,000. Same 35 years. Very different ending."
Scene 4 [zoom_in]:
  - "Start a ₹500 SIP in Nifty 50 this week — increase it ₹500 every 6 months."
"""

    # ------------------------------------------------------------------
    # Research Summarisation
    # ------------------------------------------------------------------

    def _summarise_research(self, topic: str, raw_research: str) -> str:
        """
        Use LLM to compress raw research into key facts before passing
        to the main script prompt. Keeps all numbers/stats intact.
        Only called when research exceeds the token budget threshold.
        """
        prompt = (
            f"Topic: {topic}\n\n"
            f"Research:\n{raw_research}\n\n"
            "Summarise the above into 6-8 bullet points. "
            "Rules: preserve every specific number, percentage, date, and named entity exactly as written. "
            "Drop filler sentences that have no data. Plain text bullets only, no headers."
        )
        summary = self.generator._generate_text(
            prompt,
            system_prompt="You are a research summariser. Output only bullet points.",
        )
        logger.info("Research summarised: %d chars → %d chars", len(raw_research), len(summary))
        return summary.strip()

    # ------------------------------------------------------------------
    # Hook Generation
    # ------------------------------------------------------------------

    def _generate_hook_variants(
        self,
        topic: str,
        angle: str,
        audience_insight: str,
        channel_config: ChannelConfig,
        verified_data: str = ""
    ) -> dict:
        """
        Generate and score 5 hook variants using proven patterns.

        Returns:
            {
                'best_hook': str,
                'best_score': float,
                'reasoning': str,
                'all_variants': [
                    {
                        'hook': str,
                        'pattern': str,
                        'curiosity_gap': int,
                        'relevance': int,
                        'emotional_trigger': int,
                        'total_score': float
                    }
                ]
            }
        """
        logger.info("Generating hook variants for: %s", topic)

        hook_examples = self._get_hook_examples_for_channel(channel_config)

        system_prompt = (
            f"You are a Hook Architect for '{channel_config.name}'.\n"
            f"Channel: {channel_config.theme}\n"
            f"Audience: {channel_config.target_audience}\n"
            "Your hooks must stop scrollers in their tracks within 0.5 seconds.\n"
            "Write hooks that feel native to this channel's voice and audience."
        )

        prompt = f"""### TOPIC: {topic}
### ANGLE: {angle}
### TARGET AUDIENCE: {audience_insight}
{f'### VERIFIED DATA: {verified_data[:500]}' if verified_data else ''}

### YOUR TASK:
Generate 5 distinct hooks using proven psychological patterns.

### HOOK PATTERNS WITH EXAMPLES FOR THIS CHANNEL:

**1. SHOCKING STATISTIC**
Format: "[Specific number] [surprising fact]"
{hook_examples.split(chr(10))[0]}
Psychology: Numbers + surprise = pattern interrupt

**2. CONTRARIAN STATEMENT**
Format: "Everything you know about [X] is incomplete"
{hook_examples.split(chr(10))[1]}
Psychology: Challenges existing belief = curiosity

**3. PATTERN INTERRUPT QUESTION**
Format: "What if [opposite of common belief]?"
{hook_examples.split(chr(10))[2]}
Psychology: Cognitive dissonance = engagement

**4. PERSONAL COST/BENEFIT**
Format: "You are losing/gaining [specific outcome] by [action]"
{hook_examples.split(chr(10))[3]}
Psychology: Self-interest + specificity = relevance

**5. STATUS QUO CHALLENGE**
Format: "[Common action] is quietly [negative outcome]"
{hook_examples.split(chr(10))[4] if len(hook_examples.split(chr(10))) > 4 else ''}
Psychology: Hidden danger + urgency = emotional trigger

### SCORING CRITERIA:

**Curiosity Gap (0-10):**
- 10: Must know what happens next
- 5: Mildly interesting
- 0: Predictable/boring

**Relevance to Audience (0-10):**
- 10: "This is about MY situation"
- 5: Generally interesting
- 0: Not applicable to me

**Emotional Trigger (0-10):**
- 10: Fear, desire, anger, shock
- 5: Mild interest
- 0: Neutral/indifferent

### REQUIREMENTS:
- Use specific numbers from VERIFIED DATA when available
- Keep hooks under 14 words
- Must be immediately understandable with ZERO prior context — a stranger must get it in 1 second
- Focus on OUTCOME, not process
- Each hook must use a DIFFERENT pattern
- If comparing two numbers, state WHAT causes the difference in the hook itself
  BAD: "₹42 lakh in 7 years—but ₹28 crore by 60?" (viewer doesn't know why the jump)
  GOOD: "Same ₹3,000 SIP: ₹42 lakh at 29, ₹28 crore at 60"
- Avoid "X—but Y?" patterns where Y has no standalone meaning

### OUTPUT FORMAT (JSON):
{{
  "hooks": [
    {{
      "hook": "The actual hook text (8-14 words)",
      "pattern": "shocking_statistic | contrarian_statement | pattern_interrupt | personal_cost | status_quo_challenge",
      "curiosity_gap": 0-10,
      "relevance": 0-10,
      "emotional_trigger": 0-10,
      "reasoning": "Why this hook works for this audience (1 sentence)"
    }},
    ... (5 total)
  ]
}}

Respond with ONLY valid JSON."""

        try:
            response = self.generator._generate_text(prompt, system_prompt=system_prompt)
            logger.debug("Hook variants raw response: %s", response)

            data = self.generator._parse_json_response(response)
            hooks = data.get("hooks", [])

            if not hooks or len(hooks) < 5:
                logger.warning("Insufficient hooks generated (%d), using fallback", len(hooks))
                return self._fallback_hooks(topic, angle, verified_data)

            # Score each hook
            scored_variants = []
            for h in hooks:
                curiosity = int(h.get("curiosity_gap", 5))
                relevance = int(h.get("relevance", 5))
                emotional = int(h.get("emotional_trigger", 5))

                # Weighted scoring: emotional triggers matter most for scrolling
                total_score = (
                    curiosity * 0.3 +
                    relevance * 0.35 +
                    emotional * 0.35
                )

                scored_variants.append({
                    'hook': h.get("hook", ""),
                    'pattern': h.get("pattern", "unknown"),
                    'curiosity_gap': curiosity,
                    'relevance': relevance,
                    'emotional_trigger': emotional,
                    'total_score': round(total_score, 2),
                    'reasoning': h.get("reasoning", "")
                })

            # Sort by total score
            scored_variants.sort(key=lambda x: x['total_score'], reverse=True)

            best = scored_variants[0]

            # Log all variants
            logger.info("=" * 60)
            logger.info("HOOK VARIANTS GENERATED:")
            logger.info("-" * 60)
            for i, variant in enumerate(scored_variants, 1):
                logger.info(
                    "%d. [Score: %.1f] %s",
                    i, variant['total_score'], variant['hook']
                )
                logger.info(
                    "   Pattern: %s | C:%d R:%d E:%d",
                    variant['pattern'],
                    variant['curiosity_gap'],
                    variant['relevance'],
                    variant['emotional_trigger']
                )
                logger.info("   Reasoning: %s", variant['reasoning'])
                logger.info("")
            logger.info("BEST HOOK SELECTED: %s (Score: %.1f)", best['hook'], best['total_score'])
            logger.info("=" * 60)

            return {
                'best_hook': best['hook'],
                'best_score': best['total_score'],
                'reasoning': best['reasoning'],
                'all_variants': scored_variants
            }

        except Exception as e:
            logger.error("Hook generation failed: %s", e)
            return self._fallback_hooks(topic, angle, verified_data)

    def _fallback_hooks(self, topic: str, angle: str, verified_data: str) -> dict:
        """Generate fallback hooks when LLM generation fails."""
        # Try to extract a number from verified data
        numbers = re.findall(
            r'[\d,\.]+(?:\s*(?:crore|lakh|million|billion|%|₹|\$))',
            verified_data
        ) if verified_data else []

        number_phrase = numbers[0] if numbers else "the numbers"

        fallback_variants = [
            {
                'hook': f"Let's talk about {topic[:40]}",
                'pattern': 'generic',
                'curiosity_gap': 3,
                'relevance': 5,
                'emotional_trigger': 2,
                'total_score': 3.3,
                'reasoning': 'Generic fallback'
            },
            {
                'hook': f"Here's what most people miss about {topic[:30]}",
                'pattern': 'contrarian_statement',
                'curiosity_gap': 5,
                'relevance': 6,
                'emotional_trigger': 4,
                'total_score': 5.0,
                'reasoning': 'Fallback contrarian'
            },
            {
                'hook': f"The truth about {topic[:40]}",
                'pattern': 'status_quo_challenge',
                'curiosity_gap': 4,
                'relevance': 6,
                'emotional_trigger': 3,
                'total_score': 4.3,
                'reasoning': 'Fallback challenge'
            },
            {
                'hook': f"{number_phrase} you need to know",
                'pattern': 'shocking_statistic',
                'curiosity_gap': 6,
                'relevance': 5,
                'emotional_trigger': 5,
                'total_score': 5.3,
                'reasoning': 'Fallback with data'
            },
            {
                'hook': f"Why {angle[:50]}",
                'pattern': 'pattern_interrupt',
                'curiosity_gap': 5,
                'relevance': 7,
                'emotional_trigger': 4,
                'total_score': 5.4,
                'reasoning': 'Fallback angle-based'
            }
        ]

        fallback_variants.sort(key=lambda x: x['total_score'], reverse=True)
        best = fallback_variants[0]

        logger.warning("Using fallback hooks (best score: %.1f)", best['total_score'])

        return {
            'best_hook': best['hook'],
            'best_score': best['total_score'],
            'reasoning': best['reasoning'],
            'all_variants': fallback_variants
        }

    # ------------------------------------------------------------------
    # Script Generation
    # ------------------------------------------------------------------

    def _get_format_guidelines(self, format_name: str, structure: List[str]) -> str:
        """Generate format-specific guidelines for story structure."""

        guidelines = {
            'contrast': """
**Line 1 - SETUP:**
Introduce the first approach/option with concrete details.
Example: "Your parents saved ₹50 lakh in FDs over 30 years"
NOT: "Safety is an illusion we cling to"

**Line 2 - CONTEXT:**
Show the result or reasoning behind the first approach.
Example: "It grew to ₹1.2 crore. They felt safe."
NOT: "The mirror shows what others want to see"

**Line 3 - INSIGHT:**
Reveal the alternative approach and its result. This is the comparison moment.
Example: "The same amount in Nifty 50? ₹8.7 crore."
NOT: "Behind every mask is another mask"

**Line 4 - TAKEAWAY:**
Quantify the difference and its meaning.
Example: "Playing it safe cost them ₹7.5 crore."
NOT: "Authenticity is the final illusion"
""",
            'timeline': """
**Line 1 - PAST:**
Establish where things were historically.
Example: "In 2010, solar energy made up 2% of India's power"
NOT: "The past is a mirror we don't recognize"

**Line 2 - INFLECTION:**
Show the turning point or key change.
Example: "Then came the 2015 solar mission with subsidies"
NOT: "Change happens when we least expect it"

**Line 3 - PRESENT:**
Reveal current state with specific data.
Example: "Today it's 15% and growing 25% yearly"
NOT: "We stand at a crossroads"

**Line 4 - FUTURE:**
Project forward based on the trend.
Example: "By 2030, India could hit 40% solar capacity"
NOT: "The future is what we make it"
""",
            'myth_buster': """
**Line 1 - COMMON BELIEF:**
State the misconception people hold.
Example: "Everyone says gold is the safest investment"
NOT: "Beliefs are comfortable lies we tell ourselves"

**Line 2 - WHY IT EXISTS:**
Explain why people believe this (history, culture).
Example: "Our grandparents survived on gold during crises"
NOT: "Tradition chains us to outdated thinking"

**Line 3 - THE TRUTH:**
Reveal what data actually shows.
Example: "But gold gave 8% returns vs Nifty's 14% over 20 years"
NOT: "Reality shatters our illusions"

**Line 4 - WHAT TO DO:**
Provide the actionable correction.
Example: "Diversify: 30% gold, 70% equity beats both"
NOT: "Question everything you know"
""",
            'case_study': """
**Line 1 - SITUATION:**
Set up the specific example/scenario.
Example: "Ravi had ₹10 lakh to invest in 2018"
NOT: "Every journey begins with a choice"

**Line 2 - DECISION:**
Show what action was taken.
Example: "He split it: ₹3L in fixed deposits, ₹7L in index funds"
NOT: "He chose the path less traveled"

**Line 3 - OUTCOME:**
Reveal the concrete results.
Example: "By 2024: FD → ₹4.2L, Index → ₹15.8L"
NOT: "Success came with patience and wisdom"

**Line 4 - LESSON:**
Extract the actionable insight.
Example: "His mixed approach gave 15% returns with lower risk"
NOT: "Balance is the key to everything"
"""
        }

        return guidelines.get(format_name, guidelines['contrast'])

    def _select_story_format(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig
    ) -> Tuple[str, str]:
        """
        Analyze topic, angle, and verified_data to select the best story format.

        Returns:
            Tuple of (format_name, reasoning)
        """
        topic = strategy.topic.lower()
        angle = strategy.angle.lower()
        verified_data = (strategy.verified_data or "").lower()

        # Keywords for each format
        contrast_keywords = ['vs', 'versus', 'compare', 'comparison', 'better', 'worse',
                           'difference', 'alternative', 'instead', 'choice']
        timeline_keywords = ['history', 'evolution', 'growth', 'trend', 'past', 'future',
                           'years', 'decade', 'century', 'progression', 'change over time']
        myth_keywords = ['myth', 'misconception', 'wrong', 'believe', 'think', 'assume',
                        'truth', 'reality', 'actually', 'debunk', 'false']
        case_study_keywords = ['example', 'case', 'story', 'how', 'success', 'failure',
                             'real', 'actual', 'happened', 'result', 'outcome']

        # Score each format
        scores = {
            'contrast': 0,
            'timeline': 0,
            'myth_buster': 0,
            'case_study': 0
        }

        # Check topic and angle
        combined_text = f"{topic} {angle}"

        for keyword in contrast_keywords:
            if keyword in combined_text:
                scores['contrast'] += 2

        for keyword in timeline_keywords:
            if keyword in combined_text:
                scores['timeline'] += 2

        for keyword in myth_keywords:
            if keyword in combined_text:
                scores['myth_buster'] += 2

        for keyword in case_study_keywords:
            if keyword in combined_text:
                scores['case_study'] += 2

        # Check verified data patterns
        if verified_data:
            # Timeline indicators: years, historical data
            if any(year in verified_data for year in ['2010', '2015', '2020', '2024']):
                scores['timeline'] += 1

            # Contrast indicators: multiple data points to compare
            numbers = re.findall(r'\d+(?:\.\d+)?(?:\s*(?:crore|lakh|million|billion|%|₹|\$))', verified_data)
            if len(numbers) >= 4:
                scores['contrast'] += 1

            # Myth buster indicators: sources, studies
            if any(word in verified_data for word in ['study', 'research', 'found', 'shows']):
                scores['myth_buster'] += 1

            # Case study indicators: specific examples, names
            if any(word in verified_data for word in ['example', 'company', 'person', 'case']):
                scores['case_study'] += 1

        # Financial content defaults to contrast (best for comparisons)
        if any(word in topic for word in ['invest', 'money', 'finance', 'stock', 'fund', 'saving']):
            scores['contrast'] += 1

        # Select format with highest score
        selected_format = max(scores, key=scores.get)

        # Default to contrast if all scores are 0 or tied
        if scores[selected_format] == 0 or list(scores.values()).count(scores[selected_format]) > 1:
            selected_format = 'contrast'
            reasoning = "Default format (no strong indicators for other formats)"
        else:
            format_info = self.STORY_FORMATS[selected_format]
            reasoning = f"Selected for {format_info['best_for']} (score: {scores[selected_format]})"

        logger.info("=" * 60)
        logger.info("STORY FORMAT SELECTION:")
        logger.info(f"Topic: {strategy.topic}")
        logger.info(f"Angle: {strategy.angle}")
        logger.info(f"Format Scores: {scores}")
        logger.info(f"Selected: {selected_format.upper()}")
        logger.info(f"Reasoning: {reasoning}")
        logger.info(f"Structure: {' → '.join(self.STORY_FORMATS[selected_format]['structure'])}")
        logger.info("=" * 60)

        return selected_format, reasoning

    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> List[dict]:
        """
        Generate a scenes-based story structure.

        Each scene = 1 SD image + 1-3 text caption lines + a motion effect.
        The AI decides how many scenes (3-5) and how many lines per scene (1-3).
        Total lines across all scenes: 6-12, targeting a ~30-60 second reel.

        Returns List[dict] where each dict has: lines, image_prompt, motion
        """
        # Enforce research requirement
        if not strategy.verified_data or len(strategy.verified_data) < 100:
            raise ValueError(
                f"Cannot generate cinematic reel without research data. "
                f"Topic: {strategy.topic} - Enable Tavily API or provide manual data."
            )

        # Extract numbers for later validation
        research_numbers = re.findall(
            r'[\d,\.]+(?:\s*(?:crore|lakh|million|billion|%|₹|\$))?',
            strategy.verified_data
        )
        logger.info("Extracted %d numbers from research for validation", len(research_numbers))

        # Select story format
        selected_format, format_reasoning = self._select_story_format(strategy, channel_config)
        format_info = self.STORY_FORMATS[selected_format]

        # Generate hook variants
        hook_result = self._generate_hook_variants(
            topic=strategy.topic,
            angle=strategy.angle,
            audience_insight=strategy.target_audience_insight,
            channel_config=channel_config,
            verified_data=strategy.verified_data,
        )
        best_hook = hook_result['best_hook']
        all_hook_variants = hook_result['all_variants']

        # Currency instruction for India channels
        is_india = getattr(channel_config, 'localization_type', 'global').lower() == 'india'
        currency_rule = (
            "\n### CURRENCY (CRITICAL): This is an India-targeted channel. "
            "Use ONLY ₹, lakh, crore for ALL monetary values. "
            "NEVER use $, USD, or Western units. Convert if needed.\n"
            if is_india else ""
        )

        copy_voice_section = ""
        if channel_config.copy_voice_examples:
            copy_voice_section = f"\n{channel_config.copy_voice_examples.strip()}\n"

        system_prompt = (
            f"You are a Story Architect for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Target Audience: {channel_config.target_audience}\n"
            + (f"Cultural Context: {channel_config.cultural_context}\n" if channel_config.cultural_context else "")
            + (f"Brand Mission: {channel_config.brand_mission}\n" if channel_config.brand_mission else "")
            + f"{currency_rule}\n"
            + copy_voice_section
            + "Your goal: Tell a clear, coherent story across 3-5 visual scenes that the audience can follow, learn from, and act on.\n"
            "Priority: STORY COHERENCE over shock value. Each line must logically connect to the next.\n"
            "Use concrete examples and specific situations the audience recognizes.\n"
            "The story MUST end with a clear, explicit action the viewer can take TODAY."
        )

        hook_variants_text = "\n".join([
            f"  {i}. [{v['pattern']}] \"{v['hook']}\" (Score: {v['total_score']:.1f})"
            for i, v in enumerate(all_hook_variants, 1)
        ])

        story_example = self._get_story_example_for_channel(channel_config)

        # Summarise research if too large to fit in the token budget
        _RESEARCH_SUMMARISE_THRESHOLD = 1200
        research_text = (strategy.verified_data or "")
        if len(research_text) > _RESEARCH_SUMMARISE_THRESHOLD:
            logger.info("Research (%d chars) exceeds threshold — summarising before prompt injection", len(research_text))
            research_text = self._summarise_research(strategy.topic, research_text)

        prompt = f"""### TOPIC: {strategy.topic}
### CORE ANGLE: {strategy.angle}
### TARGET AUDIENCE: {channel_config.target_audience}
### AUDIENCE INSIGHT: {strategy.target_audience_insight}
{f'### VERIFIED DATA (USE THESE FACTS): {research_text}' if research_text else ''}

### HOOK OPTIMIZATION:
**BEST HOOK (Score: {hook_result['best_score']:.1f}):** "{best_hook}"
**Reasoning:** {hook_result['reasoning']}

Use the best hook as your Scene 1 opening line.

### STORY FORMAT: {selected_format.upper()}
**Why:** {format_reasoning}
**Structure:** {' → '.join(format_info['structure'])}

### YOUR TASK:
Create a 3-5 scene cinematic story. Total 6-12 caption lines across all scenes.
Target duration: 30-60 seconds (each line ~4-5 seconds on screen).

The story must:
1. **Open with a hook** — the best hook above (Scene 1, Line 1)
2. **Build logically** — each line follows naturally from the previous
3. **Use concrete specifics** — real numbers from VERIFIED DATA, real scenarios
4. **Stay focused** — every line serves the single core insight
5. **End with action** — the LAST line is one specific, topic-relevant action the viewer can take TODAY that directly applies this reel's lesson. It must name the exact behaviour, not a generic platform step. BAD: "Open a demat account", "Start investing today", "Download an app". GOOD (stop-loss reel): "Set a 15% stop-loss on your worst holding this week". GOOD (SIP reel): "Increase your SIP by ₹500 this month".
{currency_rule}
### SCENE DESIGN RULES:
- Group related narrative beats into the same scene (same location/setting)
- Scene breaks = visual shift (new setting, new moment in time, new perspective)
- Prefer 2 lines per scene — gives enough space to build the beat
- Use 1 line only for a single punchline moment
- Motion effect: pick what serves the emotional moment (see options below)

### CAPTION RULES (8-14 words each):
- Conversational language, like explaining to a friend over chai
- Include specific numbers from VERIFIED DATA when relevant
- No abstract philosophical statements
- No jargon without immediate plain-language explanation

{story_example}
### SD IMAGE PROMPT RULES:
- NEVER feature hands as the main close-up subject (SD artifact nightmare)
- NEVER ask SD to render screen content (dashboards, numbers on screen) — SD cannot do this
- Instead: show the DEVICE/OBJECT in context (laptop on desk, phone on table, notebook open)
- One recurring visual element across ALL scenes for continuity (same person OR same setting)
- Shot variety: vary between Extreme close-up / Close-up / Medium shot / Wide shot

### MOTION EFFECTS (pick one per scene):
- **zoom_in**: Slow zoom in — builds tension, draws viewer in. Good for setups and reveals.
- **zoom_out**: Slow zoom out — reveals full picture, sense of scale. Good for outcomes and comparisons.
- **pan_left**: Slow pan left — movement through time or space. Good for transitions.
- **pan_right**: Slow pan right — same. Good for contrasts.
- **static**: No movement — weight and stillness. Good for punchline moments.

### OUTPUT FORMAT (JSON only):
{{
  "visual_anchor": "The ONE element appearing in all scene images for continuity",
  "story_spine": "One sentence: what does this story teach?",
  "scenes": [
    {{
      "lines": ["Line 1", "Line 2"],
      "image_prompt": "Medium shot of [specific subject], [lighting], [mood], 35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos",
      "motion": "zoom_in"
    }},
    {{
      "lines": ["Line 3"],
      "image_prompt": "Close-up of [specific subject], [lighting], [mood], 35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos",
      "motion": "pan_right"
    }}
  ]
}}

### FINAL CHECKLIST:
- [ ] Scene 1 Line 1 is exactly the best hook (no rewording)
- [ ] Each line follows logically from the previous
- [ ] Numbers come from VERIFIED DATA only
- [ ] Last line is a TOPIC-SPECIFIC action (no generic "open a demat account" / "start investing today" — must apply the specific lesson)
- [ ] 3-5 scenes, ideally 6-10 lines total (minimum 4)
- [ ] Caption values are plain text only — no "Here's the text:", "Caption:", "Line X:" prefixes
{f'- [ ] All monetary values in ₹/lakh/crore (NO $)' if is_india else ''}

Respond with ONLY valid JSON."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)

        logger.info("Cinematic Script System Prompt: %s", system_prompt)
        logger.info("Cinematic Script User Prompt: %s", prompt)
        logger.debug("Cinematic Script Raw Response: %s", response)

        data = self.generator._parse_json_response(response)
        scenes_raw = data.get("scenes", [])
        visual_anchor = data.get("visual_anchor", "subject")
        story_spine = data.get("story_spine", strategy.topic)

        if not scenes_raw or len(scenes_raw) < 2:
            raise RuntimeError(
                f"Script generation returned too few scenes ({len(scenes_raw)}). "
                f"Raw response: {response[:300]}"
            )

        # Validate and clean each scene
        scenes = []
        for i, s in enumerate(scenes_raw):
            raw_lines = s.get("lines", [])
            if not raw_lines:
                raise RuntimeError(f"Scene {i+1} has no lines. Raw response: {response[:300]}")

            # Trim lines to max 16 words; strip common LLM preamble prefixes
            _CAPTION_PREFIXES = (
                "here's the caption text:", "here's the caption:", "caption text:",
                "caption:", "text:", "line:", "slide:", "here's the text:",
            )
            trimmed_lines = []
            for line in raw_lines:
                line = str(line).strip()
                lower = line.lower()
                for prefix in _CAPTION_PREFIXES:
                    if lower.startswith(prefix):
                        line = line[len(prefix):].strip()
                        break
                words = line.split()
                if len(words) > 16:
                    line = " ".join(words[:14]) + "..."
                if line:
                    trimmed_lines.append(line)

            image_prompt = str(s.get("image_prompt", ""))
            # Ensure no-text suffix
            if "no text" not in image_prompt.lower():
                image_prompt += ", 35mm film grain, 9:16 portrait, photorealistic, NO text, NO watermarks, NO logos"

            motion = str(s.get("motion", "zoom_in")).lower()
            if motion not in ("zoom_in", "zoom_out", "pan_left", "pan_right", "static"):
                motion = "zoom_in"

            scenes.append({
                "lines": trimmed_lines,
                "image_prompt": image_prompt,
                "motion": motion,
            })

        # Log the full story
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

        # Enforce minimum lines — hard fail only if truly too sparse (< 4 lines)
        # 5 lines at 4-5s each = ~25s reel, which is acceptable
        if len(all_lines_flat) < 4:
            raise RuntimeError(
                f"Story has only {len(all_lines_flat)} lines (minimum 4 required). "
                f"Raw response: {response[:300]}"
            )
        if len(all_lines_flat) < 6:
            logger.warning(
                "Story has %d lines (recommended 6+). Reel will be ~%ds — acceptable but short.",
                len(all_lines_flat), len(all_lines_flat) * 5
            )

        # Validate story coherence (warnings only, using flat lines)
        self._validate_story_coherence(all_lines_flat, story_spine)

        # Validate data usage
        self._validate_data_usage(all_lines_flat, research_numbers, strategy.verified_data, selected_format)

        return scenes
