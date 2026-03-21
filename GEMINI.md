# Project Rules & Standards: Insta-Poster

## 1. Engineering Standards (Mandatory)
- **User Confirmation FIRST:** You MUST NOT modify, commit, or push any code changes without first describing the proposed changes and receiving explicit approval from the user.
- **Syntax Check First:** BEFORE any `git commit` or `git push`, you MUST run `python3 -m py_compile src/**/*.py` to verify there are no syntax or indentation errors.
- **Surgical Edits:** Prefer `replace` over `write_file` for large files to maintain context efficiency.
- **Clean Architecture:** Use standard Python `logging` module. Do not pass custom logger objects into agents.
- **Explicit Data Paths:** Pass specific `Path` objects for directories instead of complex class instances.

## 2. Data Integrity (Non-Negotiable)
- **Zero Hallucination:** Every number or financial statistic must be traceable to a specific 2024 report (e.g., Brand Finance, Interbrand, Forbes).
- **Source Citation:** Data slides must cite their source. 
- **Integrity First:** Appending a source label to a fabricated or "guessed" number is a CRITICAL FAILURE.
- **Verification Gate:** Always perform a Phase 1.5 factual validation before generating final slides.

## 3. Visual & Narrative Brand
- **Unified Persona:** Maintain the "Lead Data Analyst" identity for the specific channel across all AI agents.
- **Feasible Visuals:** Image prompts must be CONCRETE and LITERAL (objects, positions). Avoid abstract metaphors that AI cannot draw.
- **Integrated Backgrounds:** Prioritize `blurred_hook` background style for Slides 2-10 to maintain high-end brand continuity.
- **Responsive Typography:** Always use `white-space: pre-wrap` in HTML templates to respect AI-generated formatting and prevent truncation.

## 4. Provider Strategy
- **Text (LLM):** Default to **Groq (Llama 3.1 70B)** for speed and reliability. Fallback to Gemini 1.5 Flash.
- **Images:** Default to **Ideogram v2** via Replicate for superior typography.
