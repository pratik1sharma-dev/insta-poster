# insta-poster

Instagram content automation pipeline for AI-generated carousels, reels, and cinematic reels.

## Commands

```bash
source venv/bin/activate

# Generate content
python3 -m src.main --channel <name> --carousel
python3 -m src.main --channel <name> --reel
python3 -m src.main --channel <name> --cinematic

# Common flags
--dry-run           # Skip publishing
--topic "..."       # Override topic discovery
--voice             # Add TTS narration (cinematic/reel)
--generate-variants # Generate hook variants
```

Channels: `pagecapsules`, `wealthcapsules`, `psychecapsules`, `startupcapsules`, `worldinranks`, `fertilitycapsules`

## Architecture

```
main.py → ContentPipeline.run()
  Phase 1: ContentStrategist.plan_content()     → strategy.topic/angle/hook_type
  Phase 2: DataResearcher.research_with_tools() → strategy.verified_data (5-8 bullets)
  Phase 3: [carousel | reel | cinematic] generator
  Phase 4: ImageGenerator (Stable Diffusion)
  Phase 5: VideoAssembler (reels/cinematic only)
  Phase 6: Publisher (Instagram Graph API)
```

Key agents: `src/agents/` — `content_strategist.py`, `data_researcher.py`, `content_generator.py`, `cinematic_script_generator.py`

## Environment Variables

```
GROQ_API_KEY          # Primary LLM (default)
GEMINI_API_KEY        # Fallback LLM
REPLICATE_API_TOKEN   # Image generation fallback
TAVILY_API_KEY        # Web research (required for cinematic)
SD_API_URL            # Stable Diffusion API (default: http://100.67.231.93:7860)
```

Copy `.env.example` → `.env` and fill in keys.

## Core Patterns

### No hardcoded channel data in Python
Channel-specific config (theme, audience, tone, voice, localization) lives in `src/config/channels.yaml`. Python code reads it via `ChannelConfig`. Do not add `if channel == "wealthcapsules"` branches in agent code.

### No Python heuristics when the LLM can decide
Bad: keyword-scoring dicts, regex-based format selection, `_STORY_FORMAT_KEYWORDS` matching.
Good: put the decision criteria in the prompt and let the model choose.

### Research is pre-summarized — don't re-summarize
`DataResearcher.synthesize_research()` already compacts web research into 5-8 verified bullet points stored in `strategy.verified_data`. Agents must use this directly. Never add a `_summarise_research` step downstream.

### Currency/localization via prompting, not regex
Inject a `currency_rule` string into the prompt when `localization_type == "india"`. Do not parse or transform monetary values in Python.

### Multi-turn LLM sessions
Use `ContentGenerator._generate_conversation(messages, system_prompt)` for multi-turn flows (e.g., cinematic: Turn 1 = hooks, Turn 2 = script). Groq supports full message history; other providers fall back to single-turn automatically. Do not duplicate state across separate `_generate_text` calls.

### Class constants for magic values
Put thresholds, limits, and fixed strings as class-level constants (`VALID_MOTIONS`, `MAX_CAPTION_WORDS`, etc.). No inline magic numbers or repeated string literals.

### Extend ChannelConfig for new optional fields
Add new per-channel optional fields to `ChannelConfig` in `src/models/content_models.py` and to `channels.yaml` as optional keys. Do not add new Python dicts keyed by channel name.

## Providers

| Type  | Default | Fallback         | Notes                        |
|-------|---------|------------------|------------------------------|
| LLM   | groq    | gemini/replicate | Groq supports multi-turn     |
| Image | sd      | replicate        | SD at `SD_API_URL`           |
| TTS   | edge    | —                | Per-channel `voice_id` field |

Provider is set in `src/config/settings.py` (`llm_provider`, `groq_model`).
