    def _generate_script_and_prompts(
        self,
        strategy: ContentStrategy,
        channel_config: ChannelConfig,
        num_images: int,
    ) -> Tuple[List[str], List[str]]:
        """
        Generate caption lines and matching SD image prompts in one call.

        Caption lines: 8-12 words, second-person, emotionally charged.
        Image prompts: cinematic human moment, portrait 9:16, no text.
        """
        system_prompt = (
            f"You are the Visionary Creative Director for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Brand Mission: {channel_config.brand_mission}\n"
            f"Target Audience: {channel_config.target_audience}\n"
            f"Cultural Context: {channel_config.cultural_context}\n\n"
            "Your goal is to create a 'Mood Film' Reel. We don't explain; we reveal. "
            "We use 'spiky' insights—statements that are bold, slightly polarizing, or deeply personal—"
            "to stop the scroll. Avoid generic advice."
        )

        prompt = f"""### TOPIC TO TRANSFORM: {strategy.topic}
### CORE ANGLE: {strategy.angle}
### STRATEGY INSIGHT: {strategy.target_audience_insight}

### TASK:
Create a {num_images}-image cinematic Reel. This is a high-end visual narrative.

### CAPTION RULES (8-12 words):
- Use 'Spiky' Statements: Bold, counter-intuitive, or visceral.
- No 'Intro' or 'Summary' lines. Every line must hit like a realization.
- Tone: Cold, objective, and deeply observant.
- Progression: Start with a common lie/behavior, end with a harsh but empowering truth.

### IMAGE PROMPT RULES (Stable Diffusion):
- AVOID generic scenes like 'person thinking' or 'laptop on desk'.
- USE Concrete Visual Metaphors: 
  - Instead of 'Stress', use 'A single lit cigarette in a dark room with heavy smoke' or 'Clenched fists underwater'.
  - Instead of 'Growth', use 'A single green sprout breaking through cracked concrete'.
- STYLE: Cinematic noir, neo-realism, moody lighting (chiaroscuro), 35mm film grain, 9:16 portrait.
- ABSOLUTE: No text or typographic elements in the scene.

### OUTPUT FORMAT (JSON):
{{
  "lines": [
    "Spiky Line 1",
    "Spiky Line 2",
    ...
  ],
  "image_prompts": [
    "Concrete Visual Metaphor 1",
    "Concrete Visual Metaphor 2",
    ...
  ]
}}

Respond with ONLY valid JSON. Exactly {num_images} lines and {num_images} image_prompts."""

        response = self.generator._generate_text(prompt, system_prompt=system_prompt)
        
        # Log Prompts
        logger.debug("Cinematic Script System Prompt: %s", system_prompt)
        logger.debug("Cinematic Script User Prompt: %s", prompt)
        logger.debug("Cinematic Script Raw Response: %s", response)

        try:
            data    = self.generator._parse_json_response(response)
            lines   = data.get("lines", [])
            prompts = data.get("image_prompts", [])

            # Validate counts
            if len(lines) != num_images or len(prompts) != num_images:
                logger.warning(
                    "Count mismatch (lines=%d, prompts=%d, expected=%d)",
                    len(lines), len(prompts), num_images
                )
                # Pad or trim to match
                while len(lines)   < num_images: lines.append(strategy.topic)
                while len(prompts) < num_images: prompts.append(
                    f"Cinematic portrait of a person in thought, natural light, "
                    f"film grain, shallow depth of field, 9:16"
                )
                lines   = lines[:num_images]
                prompts = prompts[:num_images]

            # Enforce word count on captions
            trimmed_lines = []
            for line in lines:
                words = str(line).split()
                if len(words) > 14:
                    line = " ".join(words[:12]) + "."
                trimmed_lines.append(str(line))

            # Append no-text instruction to every image prompt
            clean_prompts = []
            for p in prompts:
                p = str(p)
                if "no text" not in p.lower():
                    p += (
                        ", cinematic noir, neo-realism, moody lighting, "
                        "35mm film grain, 9:16 portrait, NO text NO watermarks"
                    )
                clean_prompts.append(p)

            return trimmed_lines, clean_prompts

        except Exception as e:
            logger.error("Script generation failed: %s", e)
            # Fallback: use topic as single caption
            fallback_line   = [strategy.topic[:60]] * num_images
            fallback_prompt = [
                "Cinematic portrait, person sitting alone in soft light, "
                "film grain, shallow depth of field, 9:16, no text"
            ] * num_images
            return fallback_line, fallback_prompt
