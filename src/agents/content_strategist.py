"""
Content Strategist Agent - Determines topic, hook strategy, and carousel structure.
"""
import json
import random
import logging
import time
from pathlib import Path
from typing import List, Optional, Any
from google import genai
import replicate
from groq import Groq
from replicate.exceptions import ReplicateError
from tavily import TavilyClient
from src.models import ChannelConfig, ContentStrategy, HookType
from src.config import settings


logger = logging.getLogger(__name__)


class ContentStrategist:
    """AI agent that plans content strategy for Instagram posts."""

    def __init__(self):
        """Initialize the Content Strategist with the requested provider."""
        self.provider = settings.llm_provider.lower()
        
        if self.provider == "gemini":
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model = settings.gemini_strategist_model
        elif self.provider == "replicate":
            self.model = settings.replicate_llm_model
        elif self.provider == "groq":
            self.client = Groq(api_key=settings.groq_api_key)
            self.model = settings.groq_model
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _clean_ai_response(self, text: str) -> str:
        """Strip <think> blocks and other AI artifacts."""
        if not text:
            return ""
        # Remove <think>...</think> blocks
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return text.strip()

    def _generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Utility to generate text from the configured provider with retry logic and system instructions."""
        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            try:
                raw_response = ""
                if self.provider == "gemini":
                    # For Gemini, system instructions are set at client or model level
                    from google.genai import types
                    config = None
                    if system_prompt:
                        config = types.GenerateContentConfig(system_instruction=system_prompt)
                    
                    response = self.client.models.generate_content(
                        model=self.model, 
                        contents=prompt,
                        config=config
                    )
                    raw_response = response.text
                elif self.provider == "replicate":
                    input_data = {
                        "prompt": prompt,
                        "max_new_tokens": 4096,
                    }
                    if system_prompt:
                        input_data["system_prompt"] = system_prompt
                        
                    output = replicate.run(
                        self.model,
                        input=input_data
                    )
                    raw_response = "".join(output)
                elif self.provider == "groq":
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})
                    
                    completion = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=4096,
                    )
                    raw_response = completion.choices[0].message.content
                
                return self._clean_ai_response(raw_response)

            except Exception as e:
                # Check if it's a rate limit error (429)
                is_rate_limit = False
                error_msg = str(e).lower()
                
                if self.provider == "replicate" and isinstance(e, ReplicateError):
                    if "429" in error_msg or "throttled" in error_msg:
                        is_rate_limit = True
                elif self.provider == "gemini":
                    if "429" in error_msg or "resource_exhausted" in error_msg:
                        is_rate_limit = True
                elif self.provider == "groq":
                    if "429" in error_msg or "rate_limit" in error_msg:
                        is_rate_limit = True
                
                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logging.getLogger(__name__).warning(f"Rate limited by {self.provider}. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                
                # If not a rate limit or we've exhausted retries, re-raise
                raise e
        return ""

    def _generate_search_queries(self, topic: str, theme: str) -> List[str]:
        """Ask the LLM to generate optimal search queries for this topic."""
        from datetime import datetime
        current_date = datetime.now().strftime("%B %Y")
        
        prompt = f"""You are a research assistant. 
Today's Date: {current_date}
Topic: "{topic}"
Channel Theme: "{theme}"

Generate 3 specific search queries to find the most up-to-date, verifiable data and reports for this topic.
Focus on finding the latest available figures relative to today's date. 
If the topic is historical, focus on that specific era.

Respond with ONLY a comma-separated list of the 3 queries.
"""
        response = self._generate_text(prompt)
        # Parse comma-separated list
        queries = [q.strip().strip('"') for q in response.split(',')]
        return queries[:3]

    def _research_topic(self, topic: str, theme: str) -> str:
        """Search for real-world data about the topic using AI-generated queries."""
        if not settings.tavily_api_key:
            return ""

        try:
            client = TavilyClient(api_key=settings.tavily_api_key)
            queries = self._generate_search_queries(topic, theme)

            research_context = "### REAL-WORLD RESEARCH DATA:\n"

            for query in queries:
                logging.getLogger(__name__).info(f"Researching: {query}")
                response = client.search(query=query, search_depth="advanced", max_results=2)
                for result in response.get('results', []):
                    research_context += f"- Source: {result.get('url')}\n"
                    research_context += f"  Content: {result.get('content')}\n\n"

            return research_context
        except Exception as e:
            logging.getLogger(__name__).error(f"Tavily research failed: {e}")
            return ""

    def plan_content(
        self, channel_config: ChannelConfig, topic_hint: Optional[str] = None, raw_output_dir: Optional[Path] = None
    ) -> ContentStrategy:
        """Plan content strategy for a post."""
        
        # 1. Selection Logic
        if topic_hint:
            topic = topic_hint
        elif channel_config.allow_ai_discovery and random.random() < 0.3:
            topic = self._discover_topic(channel_config, raw_output_dir)
        else:
            topic = random.choice(channel_config.curated_topics)

        # 2. Dynamic Research Step
        research_data = self._research_topic(topic, channel_config.theme)

        # 3. Unified System Persona
        system_prompt = f"""You are the Lead Data Analyst for '{channel_config.name}'. 
Mission: {channel_config.brand_mission or channel_config.theme}
Audience: {channel_config.target_audience}
Tone: {channel_config.tone}

{research_data}

### CORE DIRECTIVE: ANALYTICAL INTEGRITY FIRST
- **SOURCE-LOCK (MANDATORY):** You are FORBIDDEN from using any data, rankings, or financial figures that are not explicitly present in the REAL-WORLD RESEARCH DATA provided above. 
- **CATEGORICAL INTEGRITY:** Ensure every item in your ranking strictly matches the requested category. If the topic is "Fashion houses", you MUST skip "Automotive" or "Technology" brands even if they are in the same luxury report.
- DO NOT invent "surprising" stories or archetypes (like "underdog"). 
- If the research data is insufficient to fulfill the task, respond with: "DATA INSUFFICIENT".
- Appending a source label to a figure not found in the provided snippets is a CRITICAL FAILURE.
"""

        # 4. Ground Rules First
        prompt = f"""### GROUND RULES (NON-NEGOTIABLE):
1. Every number must come from a named authoritative report.
2. If you cannot verify a figure, do not include it. Write "data unavailable".
3. Appending a source label to an unverified number is a CRITICAL FAILURE.
4. No "False Tension": Never call a top-5 global company an "underdog" or "pawn."

### THE TASK:
Develop a strategic blueprint for the topic: "{topic}"

### STRATEGIC RULES:
1. **The Angle:** Focus on providing a clear, high-value educational perspective. This can be a "Comprehensive Guide", "Clean Comparison", or "Top Summary". Do not force drama or "surprising" takes if they don't naturally fit.
2. **Metaphor Feasibility (CRITICAL):** Suggest ONE singular, cinematic visual metaphor that helps explain the data.
3. **Clarity over Hype:** Prioritize making the information easy to digest for your professional audience.

### OUTPUT FORMAT (JSON ONLY):
{{
  "angle": "clear educational focus or summary",
  "hook_type": "curiosity | value_proposition | question | relatability",
  "carousel_length": 6-10,
  "visual_metaphor": "CONCRETE scene description",
  "color_palette": {{ "background": "hex", "primary": "hex", "accent": "hex" }},
  "typography_style": "Font pairing",
  "target_audience_insight": "the educational value for the audience",
  "reasoning": "why this summary/guide is useful"
}}
"""
        
        if raw_output_dir:
            try:
                with open(raw_output_dir / "strategy_PROMPT.txt", "w") as f:
                    f.write(f"SYSTEM PROMPT:\n{system_prompt}\n\nUSER PROMPT:\n{prompt}")
            except Exception: pass

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        
        if raw_output_dir:
            try:
                with open(raw_output_dir / "strategy.txt", "w") as f:
                    f.write(response_text)
            except Exception: pass

        return self._parse_strategy_response(response_text, topic)

    def _discover_topic(self, channel_config: ChannelConfig, raw_output_dir: Optional[Path] = None) -> str:
        """
        Use AI to discover a new trending topic.

        Args:
            channel_config: Channel configuration
            raw_output_dir: Optional directory to save raw response

        Returns:
            New topic suggestion
        """
        system_prompt = f"""You are a content strategist for an Instagram channel about: {channel_config.theme}.
Target audience: {channel_config.target_audience}
Your goal is to find timely, relevant, and engaging topics that have high viral potential."""

        prompt = f"""Current curated topics:
{chr(10).join(f"- {topic}" for topic in channel_config.curated_topics[:10])}

Suggest ONE new, trending topic that would resonate with this audience.
The topic should be:
1. Timely and relevant
2. Different from existing curated topics
3. Engaging for the target audience
4. Suitable for a carousel post (has multiple key points)

Respond with ONLY the topic name (e.g., "Book Title by Author" or "Concept Name").
"""

        response_text = self._generate_text(prompt, system_prompt=system_prompt)
        
        if raw_output_dir:
            try:
                with open(raw_output_dir / "discovery.txt", "w") as f:
                    f.write(response_text)
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to save raw discovery: {e}")
            
        return response_text.strip().strip('"').strip("'")

    def _build_strategy_prompt(self, channel_config: ChannelConfig, topic: str) -> str:
        """Build prompt for strategy determination."""
        return f"""You are an Instagram content expert. 
Create a clear and engaging strategy for a post about: "{topic}"

**Channel:** {channel_config.theme}
**Audience:** {channel_config.target_audience}

**Your Task:**
1. Decide on a unique angle for this topic.
2. Choose a hook to grab attention.
3. Define a visual theme/metaphor for the slides.
4. Choose a professional color palette.

**Output Format (JSON):**
{{
  "angle": "The core idea or perspective of the post.",
  "hook_type": "curiosity | controversy | relatability | value_proposition | question",
  "carousel_length": 5-8,
  "visual_metaphor": "The visual theme for the images.",
  "color_palette": "Background, Primary, and Accent colors.",
  "typography_style": "Font style and weights.",
  "target_audience_insight": "Why the audience will care.",
  "reasoning": "Brief explanation of this strategy."
}}

Respond with ONLY JSON.
"""

    def _parse_strategy_response(self, response_text: str, topic: str) -> ContentStrategy:
        """
        Parse LLM's strategy response into ContentStrategy model.

        Args:
            response_text: Raw response from LLM
            topic: Topic being planned

        Returns:
            ContentStrategy instance
        """
        if not response_text:
            return self._get_default_strategy(topic)

        # 1. Try to find content within markdown code blocks
        import re
        data = None
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Try to find anything that looks like a JSON object
        if not data:
            json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

        # 3. Last ditch: clean the whole string
        if not data:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse strategy JSON: {response_text[:200]}...")
                return self._get_default_strategy(topic)

        # Create ContentStrategy
        return ContentStrategy(
            topic=topic,
            angle=data["angle"],
            hook_type=HookType(data["hook_type"]),
            carousel_length=max(3, min(10, data["carousel_length"])),
            visual_metaphor=data["visual_metaphor"],
            color_palette=data["color_palette"],
            typography_style=data["typography_style"],
            target_audience_insight=data["target_audience_insight"],
            reasoning=data.get("reasoning"),
        )

    def _get_default_strategy(self, topic: str) -> ContentStrategy:
        """Return a fallback strategy if LLM fails."""
        return ContentStrategy(
            topic=topic,
            angle="A default angle because the LLM response was not valid JSON.",
            hook_type=HookType.VALUE_PROPOSITION,
            carousel_length=7,
            visual_metaphor="No visual metaphor due to parsing error.",
            color_palette="A default color palette.",
            typography_style="A default typography style.",
            target_audience_insight="Seeking actionable insights",
            reasoning="Default strategy due to parsing error",
        )
