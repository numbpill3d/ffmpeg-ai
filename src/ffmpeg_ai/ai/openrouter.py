"""OpenRouter client for free-tier LLM calls."""
import asyncio
import os
from openai import AsyncOpenAI

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

STYLE_PRESETS: dict[str, str] = {
    "educational": (
        "Tone: authoritative yet accessible — explain like a knowledgeable friend. "
        "Pacing: measured and clear. "
        "Visuals: close-ups of subject, data graphics, diagrams. "
        "Structure: surprising fact → explanation → implication."
    ),
    "dramatic": (
        "Tone: cinematic, intense, high stakes. Short punchy sentences. Relentless pacing. "
        "Visuals: extreme angles, dramatic lighting, motion blur, high contrast. "
        "Structure: escalating tension from hook to climax."
    ),
    "listicle": (
        "Tone: direct and punchy. Number each point explicitly (1... 2... 3...). Very fast cuts. "
        "Visuals: bold graphic elements, strong contrast. "
        "Structure: countdown or ranked list with a payoff at the end."
    ),
    "documentary": (
        "Tone: journalistic and reflective, like a mini-documentary. "
        "Deliberate pacing with moments to breathe. "
        "Visuals: naturalistic, observational, muted colour palette. "
        "Structure: context → story → insight."
    ),
}

# Free models ranked by quality/speed (diverse providers to avoid single-provider rate limits)
FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",        # Meta, 128k ctx, reliable
    "nousresearch/hermes-3-llama-3.1-405b:free",     # Nous, 405B, high quality
    "openai/gpt-oss-120b:free",                      # OpenAI infra, 131k ctx
    "mistralai/mistral-small-3.1-24b-instruct:free", # Mistral, 128k ctx
    "nvidia/nemotron-3-super-120b-a12b:free",        # NVIDIA, 262k ctx
    "qwen/qwen3-next-80b-a3b-instruct:free",         # Alibaba, 80B
    "meta-llama/llama-3.2-3b-instruct:free",         # fast fallback (small)
]


def get_client() -> AsyncOpenAI:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    return AsyncOpenAI(
        api_key=key or "no-key",
        base_url=OPENROUTER_BASE,
    )


async def generate_script(
    topic: str,
    duration: int = 45,
    model: str = FREE_MODELS[0],
    style: str | None = None,
) -> dict:
    """Try model, fall back through FREE_MODELS list on rate-limit or null response."""
    models_to_try = [model] + [m for m in FREE_MODELS if m != model]
    last_err: Exception | None = None
    for m in models_to_try:
        try:
            result = await _generate_script(topic, duration=duration, model=m, style=style)
            if result is not None:
                return result
            last_err = RuntimeError(f"Model {m} returned empty content")
        except Exception as e:
            import json as _json
            msg = str(e).lower()
            is_rate = any(x in msg for x in ("429", "rate", "temporarily", "overloaded"))
            _retriable_phrases = (
                "404", "400", "upstream", "provider", "no endpoints",
                "unterminated", "jsondecode", "bad request",
                "developer instruction", "invalid_argument",
                "timeout", "timed out", "connection",
            )
            is_retriable = (
                isinstance(e, _json.JSONDecodeError)
                or is_rate
                or any(x in msg for x in _retriable_phrases)
            )
            if is_retriable:
                last_err = e
                if is_rate:
                    await asyncio.sleep(8)
                continue
            raise
    raise last_err or RuntimeError("all models exhausted without a usable response")


async def _generate_script(
    topic: str,
    duration: int = 45,
    model: str = FREE_MODELS[0],
    style: str | None = None,
) -> dict:
    client = get_client()
    system = (
        "You are an expert YouTube Shorts scriptwriter and visual creative director. "
        "You craft emotionally compelling, viral vertical video scripts "
        "with precise cinematic visual direction. "
        "Output strict JSON only — no markdown fences, no extra text, no comments."
    )
    if style and style in STYLE_PRESETS:
        system += (
            f"\n\nSTYLE DIRECTIVE — apply this tone and structure throughout:"
            f"\n{STYLE_PRESETS[style]}"
        )

    # YouTube Shorts are best under 50s to avoid the 60s hard limit.
    target_dur = min(duration, 50)
    n_segments = max(4, target_dur // 8)

    user = f"""Write a YouTube Short script about: "{topic}"

Return JSON with exactly this shape:
{{
  "title": "punchy curiosity-gap title, 5-8 words",
  "hook": {{
    "text": "opening line — ≤12 words, shocking stat or question",
    "visual_prompts": ["AI image prompt for the hook"]
  }},
  "segments": [
    {{
      "text": "narration — direct, conversational, no filler words",
      "visual_prompts": [
        "AI image prompt 1 (highly specific: subject, action, framing, lighting, 8k, cinematic)",
        "AI image prompt 2 (variation: different angle or detail of the same scene)"
      ]
    }}
  ],
  "cta": {{
    "text": "urgent closing CTA — max 12 words, end with a question to drive comments",
    "visual_prompts": ["AI image prompt for the CTA"]
  }},
  "viral_package": {{
    "hashtags": ["#tag1", "#tag2", "#tag3"],
    "description": "100-character description for upload",
    "thumbnail_prompt": "High-contrast thumbnail prompt, bold text, viral style"
  }}
}}

Requirements:
- Produce exactly {n_segments} segments.
- Total narration word count MUST be under 130 words.
- Each segment MUST have 2 distinct "visual_prompts".
- Hook and CTA MUST each have 1 distinct "visual_prompts".
- Script MUST conclude with a question in the CTA to drive comments.
- Script language: active voice, second person ("you"), present tense."""

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.7,
        max_tokens=3500,
        timeout=60,
    )
    import json
    content = resp.choices[0].message.content
    if not content:
        return None
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
