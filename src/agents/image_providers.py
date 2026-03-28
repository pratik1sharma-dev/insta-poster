"""
Shared image provider utilities — raw API calls for SD, Replicate, and Gemini.
Used by both ImageGenerator (carousel) and CinematicImageGenerator (reels).
"""
import base64
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


def call_sd_api(
    api_url: str,
    timeout: int,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    negative_prompt: str = "",
    cfg_scale: float = 7,
    sampler_name: str = "DPM++ 2M Karras",
) -> bytes:
    """POST to a local SD WebUI API and return decoded image bytes."""
    payload = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler_name,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    response = requests.post(api_url, json=payload, timeout=timeout)
    response.raise_for_status()
    return base64.b64decode(response.json()["images"][0])


def call_replicate_api(model: str, input_params: dict) -> str:
    """Run a Replicate model and return the output image URL."""
    import replicate
    output = replicate.run(model, input=input_params)
    return output[0] if isinstance(output, list) else str(output)


def call_gemini_image_api(prompt: str, model: str, api_key: str) -> Optional[bytes]:
    """Call Gemini image generation and return raw image bytes, or None on failure."""
    from google import genai as genai_client
    from google.genai import types

    client = genai_client.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data
    return None


def download_image_url(url: str, timeout: int = 60) -> bytes:
    """Download image bytes from a URL."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content
