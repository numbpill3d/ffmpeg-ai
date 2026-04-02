"""OpenRouter client for free-tier LLM calls."""
import asyncio
import os
from openai import AsyncOpenAI

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Free models ranked by quality/speed (diverse providers to avoid single-provider rate limits)
# Note: gemma models don't support system prompts via Google AI Studio — excluded
FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",           # Meta, 128k ctx, reliable
    "nousresearch/hermes-3-llama-3.1-405b:free",        # Nous, 405B, high quality
    "openai/gpt-oss-120b:free",                         # OpenAI infra, 131k ctx
    "mistralai/mistral-small-3.1-24b-instruct:free",    # Mistral, 128k ctx
    "nvidia/nemotron-3-super-120b-a12b:free",           # NVIDIA, 262k ctx
    "qwen/qwen3-next-80b-a3b-instruct:free",            # Alibaba, 80B
    "meta-llama/llama-3.2-3b-instruct:free",            # fast fallback (small)
]


def get_client() -> AsyncOpenAI:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    return AsyncOpenAI(
        api_key=key or "no-key",
        base_url=OPENROUTER_BASE,
    )


async def generate_script(topic: str, duration: int = 45, model: str = FREE_MODELS[0]) -> dict:
    """Try model, fall back through FREE_MODELS list on rate-limit or null response."""
    models_to_try = [model] + [m for m in FREE_MODELS if m != model]
    last_err = None
    for m in models_to_try:
        try:
            result = await _generate_script(topic, duration=duration, model=m)
            if result is not None:
                return result
            last_err = RuntimeError(f"Model {m} returned empty content")
        except Exception as e:
            import json as _json
            msg = str(e).lower()
            is_rate = any(x in msg for x in ("429", "rate", "temporarily", "overloaded"))
            is_retriable = isinstance(e, _json.JSONDecodeError) or is_rate or any(x in msg for x in (
                "404", "400", "upstream", "provider", "no endpoints",
                "unterminated", "jsondecode", "bad request",
                "developer instruction", "invalid_argument",
                "timeout", "timed out", "connection",
            ))
            if is_retriable:
                last_err = e
                if is_rate:
                    await asyncio.sleep(8)  # brief backoff before trying next model
                continue
            raise
    raise last_err


async def _generate_script(topic: str, duration: int = 45, model: str = FREE_MODELS[0]) -> dict:
    """
    Generate a YouTube Shorts script for the given topic.
    Returns: { "hook": str, "segments": [{"text": str, "duration": float}], "cta": str }
    """
    client = get_client()
    system = (
        "You are an expert YouTube Shorts scriptwriter and visual creative director. "
        "You craft emotionally compelling, viral vertical video scripts with precise cinematic visual direction. "
        "Output strict JSON only — no markdown fences, no extra text, no comments."
    )
    n_segments = max(5, duration // 7)
    user = f"""Write a {duration}-second YouTube Short script about: "{topic}"

Return JSON with exactly this shape:
{{
  "title": "punchy curiosity-gap title, 5-8 words",
  "hook": "opening line — ≤12 words, shocking stat, bold claim, or question that stops the scroll",
  "segments": [
    {{
      "text": "narration — direct, conversational, no filler words",
      "duration": 7,
      "visual": "precise visual direction: subject + action + framing + lighting mood"
    }}
  ],
  "cta": "urgent closing CTA — max 10 words, creates FOMO or triggers follow",
  "image_prompts": [
    "ultra-detailed AI image generation prompt: subject, specific camera angle, lighting type, color palette, mood, photo style"
  ]
}}

Requirements:
- Produce exactly {n_segments} segments
- Segment durations vary between 4–10s each — vary the pacing for rhythm (fast punchy opener, build in middle, climax near end)
- Segments total duration ≈ {duration - 6}s
- Produce exactly {n_segments} image_prompts (one per segment, in same order)
- Image prompts MUST be highly specific: include subject, camera angle (low angle / bird's eye / extreme close-up / dutch tilt), lighting (golden hour / dramatic rim light / neon glow / harsh shadows / soft diffused), color palette (muted desaturated / vivid saturated / monochromatic / warm/cool contrast), visual style (photorealistic / cinematic / documentary / macro photography)
- Image prompts MUST suit 9:16 vertical framing — tall subjects, vertical leading lines, portrait orientation
- Script language: active voice, second person ("you"), present tense, conversational — no filler
- Pacing: short punchy segments at start, slower deliberate builds in middle, high-energy climax near end
- Each segment creates a distinct visual beat — varied energy, no two consecutive segments identical mood"""

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.8,
        max_tokens=2048,
        timeout=60,
    )
    import json
    content = resp.choices[0].message.content
    if not content:
        return None
    raw = content.strip()
    # strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
