"""
Data Researcher Agent - handles web research, synthesis, and basic quality assessment.
"""
import logging
import time
from datetime import datetime
from typing import List, Optional
import json

from tavily import TavilyClient

from src.config import settings


logger = logging.getLogger(__name__)

# Unified base system prompt used by research-related LLM calls.
SYSTEM_PROMPT_BASE = (
    "You are a Research Assistant with two capabilities: generate high-precision web-search queries,"
    " and synthesize raw search results into VERIFIED DATA POINTS.\n"
    "Behavioral rules:\n"
    "- Be concise and precise.\n"
    "- Prefer authoritative sources and numeric/figure-seeking language.\n"
    "- When asked for queries, return exactly the requested format (e.g., comma-separated list).\n"
    "- When asked to synthesize, return machine-readable VERIFIED DATA POINTS starting with the exact line 'VERIFIED DATA POINTS:'.\n"
    "- If you cannot verify a number, mark it as 'data unavailable' or prefix low-confidence items with '⚠️'.\n"
    "\nResearch purpose and prioritization:\n"
    "- The goal of research is to produce concise, verifiable facts that directly support creation of social content for a specific channel.\n"
    "- Prioritise facts that are relevant to the provided CHANNEL METADATA and User Context (audience, tone, strategist persona, localization).\n"
    "- When synthesizing, prefer items that the channel can act on (numbers, dates, authoritative source labels, and concrete examples).\n"
    "\nController instructions:\n"
    "- When acting as the Research Controller, you MUST respond with exactly one JSON object and nothing else.\n"
    "- JSON action shape: {\"action\": \"search|search_batch|synthesize|final\", ...}\n"
    "  * For \"search\": include \"query\" (string).\n"
    "  * For \"search_batch\": include \"queries\" (array of strings).\n"
    "  * For \"synthesize\": request the system to synthesize accumulated results.\n"
    "  * For \"final\": include \"content\" (string) with the final output.\n"
    "- Do NOT include explanatory text, code fences, or any other surrounding text when returning the JSON.\n"
)


class DataResearcher:
    """Performs topic research, synthesizes results, and provides a light quality check.

    This class expects a callable `generate_text(prompt, system_prompt=None)` to be
    passed on initialization so it can use the existing LLM wrapper in other agents.
    """

    def __init__(self, generate_text_callable):
        self.generate_text = generate_text_callable


    def research_with_tools(
        self,
        topic: str,
        theme: str,
        localization: str = "global",
        user_conversation: Optional[str] = None,
        channel_metadata: Optional[dict] = None,
        max_steps: int = 3,
    ) -> str:
        """Orchestrate a single-session research conversation where the LLM can request searches.

        The LLM is provided a controller/system prompt and may return JSON actions:
          - {"action": "search", "query": "..."}
          - {"action": "search_batch", "queries": ["...", "..."]}
          - {"action": "synthesize"}
          - {"action": "final", "content": "..."}

        The method executes requested searches via Tavily (if configured), appends results
        to an accumulated context, and feeds them back to the LLM until the model returns
        a final content or max_steps is reached. Returns synthesized final research.
        """
        # Use the canonical SYSTEM_PROMPT_BASE for controller behavior so there
        # is a single source of truth for system-level instructions.

        client = TavilyClient(api_key=settings.tavily_api_key) if settings.tavily_api_key else None

        user_block = f"User Context:\n{user_conversation}\n\n" if user_conversation else ""
        channel_block = (
            f"CHANNEL METADATA:\n{json.dumps(channel_metadata, indent=2)}\n\n" if channel_metadata else ""
        )

        base_context = (
            f"{user_block}{channel_block}Topic: {topic}\nTheme: {theme}\nLocalization: {localization}\nDate: {datetime.now().strftime('%B %Y')}\n\n"
        )

        accumulated = ""
        seen_queries: List[str] = []

        for step in range(max_steps):
            prompt = base_context + f"PREVIOUS_QUERIES: {seen_queries}\n\nPREVIOUS_RESULTS:\n{accumulated[:8000]}\n\nNow respond with a single JSON action."

            resp = self.generate_text(prompt, system_prompt=SYSTEM_PROMPT_BASE)

            # Extract JSON
            obj_text = None
            if "{" in resp:
                start = resp.find("{")
                end = resp.rfind("}")
                obj_text = resp[start : end + 1]
            else:
                obj_text = resp

            try:
                action_obj = json.loads(obj_text)
            except Exception:
                logger.warning("Controller returned non-JSON; falling back to synthesize_research")
                final = self.synthesize_research(accumulated or "", topic, user_conversation=user_conversation)
                logger.info("Research final (fallback synth) for topic '%s' | queries=%s | result_preview=%s", topic, seen_queries, (final[:400] + '...') if len(final) > 400 else final)
                return final

            action = action_obj.get("action")
            if action == "search":
                query = action_obj.get("query")
                if not query:
                    logger.warning("Search action missing query; skipping")
                    continue
                seen_queries.append(query)
                tool_results = ""
                if client:
                    try:
                        logging.getLogger(__name__).info(f"Tool search: {query}")
                        search_response = client.search(query=query, search_depth="advanced", max_results=3)
                        i = 1
                        for result in search_response.get("results", []):
                            tool_results += f"--- SEARCH RESULT [{i}] ---\n"
                            tool_results += f"SOURCE URL: {result.get('url')}\n"
                            tool_results += f"EXTRACTED CONTENT: {result.get('content')}\n\n"
                            i += 1
                    except Exception as e:
                        logging.getLogger(__name__).error(f"Tavily search failed for query '{query}': {e}")
                accumulated += tool_results
                # continue to next step so LLM can refine or finalize
                continue

            elif action == "search_batch":
                queries = action_obj.get("queries", []) or []
                for q in queries:
                    seen_queries.append(q)
                    tool_results = ""
                    if client:
                        try:
                            logging.getLogger(__name__).info(f"Tool search: {q}")
                            search_response = client.search(query=q, search_depth="advanced", max_results=3)
                            i = 1
                            for result in search_response.get("results", []):
                                tool_results += f"--- SEARCH RESULT [{i}] ---\n"
                                tool_results += f"SOURCE URL: {result.get('url')}\n"
                                tool_results += f"EXTRACTED CONTENT: {result.get('content')}\n\n"
                                i += 1
                        except Exception as e:
                            logging.getLogger(__name__).error(f"Tavily search failed for query '{q}': {e}")
                    accumulated += tool_results
                continue

            elif action == "synthesize":
                final = self.synthesize_research(accumulated or "", topic, user_conversation=user_conversation)
                logger.info("Research final (synth) for topic '%s' | queries=%s | result_preview=%s", topic, seen_queries, (final[:400] + '...') if len(final) > 400 else final)
                return final

            elif action == "final":
                content = action_obj.get("content") or ""
                if content.strip():
                    logger.info("Research final (model) for topic '%s' | queries=%s | result_preview=%s", topic, seen_queries, (content[:400] + '...') if len(content) > 400 else content)
                    return content
                else:
                    final = self.synthesize_research(accumulated or "", topic, user_conversation=user_conversation)
                    logger.info("Research final (empty model content -> synth) for topic '%s' | queries=%s | result_preview=%s", topic, seen_queries, (final[:400] + '...') if len(final) > 400 else final)
                    return final

            else:
                logger.warning("Unknown action from controller: %s", action)
                break

        # fallback - synthesize whatever we have collected so far
        final = self.synthesize_research(accumulated or "", topic, user_conversation=user_conversation)
        logger.info(
            "Research final (fallback end) for topic '%s' | queries=%s | result_preview=%s",
            topic,
            seen_queries,
            (final[:400] + '...') if len(final) > 400 else final,
        )
        return final

    # Max chars of raw research to send in a single synthesis prompt.
    # qwen/qwen3-32b has a 6000 TPM limit on Groq's on-demand tier; keeping
    # this at ~8000 chars (~2000 tokens) leaves ample room for system + output.
    _MAX_RESEARCH_CHARS = 8_000

    def synthesize_research(self, raw_research: str, topic: str, user_conversation: Optional[str] = None) -> str:
        """Process raw search results into a clean, structured data block using the LLM.

        Uses a strict system prompt (Research Analyst) so the model returns
        VERIFIED DATA POINTS in a predictable, machine-readable format.
        The optional `user_conversation` is included to let the LLM prioritise
        facts relevant to the user's intent / channel voice.
        """
        if not raw_research or len(raw_research) < 100:
            return "No verifiable data found."

        if len(raw_research) > self._MAX_RESEARCH_CHARS:
            logger.warning(
                "Raw research too large (%d chars) — truncating to %d to stay within model token limit",
                len(raw_research), self._MAX_RESEARCH_CHARS,
            )
            raw_research = raw_research[:self._MAX_RESEARCH_CHARS]

        # System prompt: build from unified base and add synthesis-specific constraints
        system_prompt = (
            SYSTEM_PROMPT_BASE
            + "\nSynthesis-specific constraints:\n"
            "- When asked to synthesize, extract 5-8 VERIFIED DATA POINTS in the strict format: '[SOURCE NAME]: [FACT with NUMBER] (Year: YYYY)'.\n"
            "- Start output with the exact line: VERIFIED DATA POINTS:\n"
            "- Prefix low-confidence items with '⚠️' and mark conflicting values clearly.\n"
        )

        user_block = f"User Context:\n{user_conversation}\n\n" if user_conversation else ""
        prompt = f"""{user_block}Topic: "{topic}"

RAW SEARCH DATA:
{raw_research}

### TASK:
Extract 5-8 VERIFIED DATA POINTS in STRICT FORMAT as specified in the system prompt.

Respond only with the list starting with "VERIFIED DATA POINTS:" and nothing else.
"""

        synthesized = self.generate_text(prompt, system_prompt=system_prompt)

        # Basic checks and warnings
        if "VERIFIED DATA POINTS:" not in synthesized:
            logger.warning("Research synthesis didn't follow format")

        if "⚠️" in synthesized or "(DATED)" in synthesized:
            logger.warning("Some research data has quality issues:\n%s", synthesized[:200])

        return synthesized

    # assess_research_quality removed: the interactive research loop is used instead.

