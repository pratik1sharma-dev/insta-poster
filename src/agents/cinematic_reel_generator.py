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
            f"You are the Creative Director for '{channel_config.name}'.\n"
            f"Channel Theme: {channel_config.theme}\n"
            f"Brand Mission: {channel_config.brand_mission}\n\n"
            "Your goal is to create short, cinematic mood Reels that emotionally reinforce our brand mission. "
            "You transform specific data-driven topics into powerful human realizations."
        )

        prompt = f"""### TOPIC TO TRANSFORM: {strategy.topic}
### CORE ANGLE: {strategy.angle}
### TARGET AUDIENCE: {channel_config.target_audience}

### TASK:
Create a {num_images}-image cinematic Instagram Reel that brings the above topic to life emotionally. 
It must feel like an atmospheric extension of the main carousel post.

Each image gets:
1. ONE caption line (the text burned onto the image)
2. ONE image prompt (the visual scene description for Stable Diffusion)

### CAPTION RULES:
- 8-12 words MAXIMUM per line — be extremely punchy.
- Second person ("you", "your") — make the reader the protagonist of the story.
- Progressive storytelling: 
  - Line 1: The Tension or Myth
  - Line 2-3: The Shift or Insight
  - Final Line: The Resolution (align this with our brand mission)
- No hashtags, no emojis, no labels. Just raw, powerful text.

### IMAGE PROMPT RULES:
- Cinematic, high-quality, portrait 9:16.
- NO text, letters, or logos in the image.
- Visual metaphor: The scene must visually represent the *emotion* of the caption line.
- Human-centric: Hands, faces, movement, shadows, natural light.

### GOOD EXAMPLES FOR '{channel_config.name}':
- "You're waiting for the perfect moment."
- "The market doesn't care about your timing."
- "Start before you're ready."
- "That's how wealth is actually built."

### OUTPUT FORMAT (JSON):
{{
  "lines": [
    "Line 1",
    "Line 2",
    ...
  ],
  "image_prompts": [
    "Stable Diffusion prompt 1",
    "Stable Diffusion prompt 2",
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
                        ", cinematic, photorealistic, film grain, "
                        "shallow depth of field, natural lighting, "
                        "9:16 portrait, NO text NO watermarks NO logos"
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
