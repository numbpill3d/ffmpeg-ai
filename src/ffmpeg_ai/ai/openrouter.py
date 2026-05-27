"""OpenRouter client for free-tier LLM calls."""
import asyncio
import json
import os
import re
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
    "morris": (
        "Tone: Hamilton Morris — empirical, intimate, intellectually precise. "
        "Write in first person as a researcher immersed in the subject. "
        "Use specific chemical names, pharmacological mechanisms, historical dates, and named "
        "researchers. Never sensationalise; let facts carry the weight. "
        "Sentences are measured and deliberate, occasionally long and clause-heavy when the "
        "complexity demands it. Personal anecdote and scientific rigour coexist naturally. "
        "Visuals: close macro laboratory shots, archival photographs, molecular structures, "
        "field work scenes. "
        "Structure: personal entry point → historical/chemical deep dive → societal or "
        "philosophical implication → quiet, unresolved conclusion."
    ),
}

# Free models ranked by quality/speed (diverse providers to avoid single-provider rate limits)
# Benchmark 2026-05-20: gpt-oss-120b was the only model to deliver 839/351 words on ibogaine topic.
# mistral-small removed (404 dead endpoint). nemotron sometimes returns null content.
FREE_MODELS = [
    "openai/gpt-oss-120b:free",                  # OpenAI infra, 131k ctx — best landscape quality
    "meta-llama/llama-3.3-70b-instruct:free",    # Meta, 128k ctx, reliable for shorts
    "nousresearch/hermes-3-llama-3.1-405b:free", # Nous, 405B, highest quality when available
    "nvidia/nemotron-3-super-120b-a12b:free",    # NVIDIA, 262k ctx (sometimes null content)
    "qwen/qwen3-next-80b-a3b-instruct:free",     # Alibaba, 80B
    "meta-llama/llama-3.2-3b-instruct:free",     # fast fallback (small)
]


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences if the LLM wrapped its JSON in them."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())
    return raw.strip()


def get_client() -> AsyncOpenAI:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    return AsyncOpenAI(
        api_key=key or "no-key",
        base_url=OPENROUTER_BASE,
    )


def _count_words(result: dict) -> int:
    parts = [
        result.get("hook", {}).get("text", ""),
        result.get("cta", {}).get("text", ""),
        *[s.get("text", "") for s in result.get("segments", [])],
    ]
    return sum(len(t.split()) for t in parts)


async def generate_script(
    topic: str,
    duration: int = 45,
    model: str = FREE_MODELS[0],
    style: str | None = None,
    mode: str = "shorts",
) -> dict:
    """Try model, fall back through FREE_MODELS list on rate-limit or null response."""
    models_to_try = [model] + [m for m in FREE_MODELS if m != model]
    client = get_client()
    last_err: Exception | None = None
    for m in models_to_try:
        try:
            result = await _generate_script(
                topic, duration=duration, model=m, style=style, mode=mode, client=client
            )
            if result is None:
                last_err = RuntimeError(f"Model {m} returned empty content")
                continue
            min_words = result.get("_min_words")
            if min_words and _count_words(result) < min_words:
                retry = await _generate_script(
                    topic, duration=duration, model=m, style=style, mode=mode, client=client
                )
                if retry is not None and _count_words(retry) >= _count_words(result):
                    result = retry
            return result
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
    mode: str = "shorts",
    client: AsyncOpenAI | None = None,
) -> dict:
    if client is None:
        client = get_client()

    if mode == "landscape":
        return await _generate_landscape_script(
            topic, duration=duration, model=model, style=style, client=client
        )

    system = (
        "You are an expert YouTube Shorts scriptwriter and visual creative director. "
        "You craft emotionally compelling, viral vertical video scripts "
        "with precise cinematic visual direction. "
        "The script must read as a single cohesive story from hook to CTA — "
        "never a collection of disconnected facts. "
        "Output strict JSON only — no markdown fences, no extra text, no comments.\n\n"
        "CRITICAL — writing visual_prompts:\n"
        "Every visual_prompt MUST depict the exact subject named in its segment's narration. "
        "Name a concrete noun: a specific person, organism, object, location, or action "
        "from the text. "
        "Never write a generic atmosphere or landscape prompt unless the narration "
        "explicitly describes one.\n"
        "BAD: 'dramatic sky at sunset, cinematic vertical shot'\n"
        "GOOD: 'close-up of scientist in white lab coat injecting compound into lab mouse, "
        "fluorescent laboratory lighting, photorealistic, 8k'\n"
        "Each prompt must answer: what specific thing from the narration is visible?"
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
    "text": "1 complete sentence — shocking stat or question that sets up the story",
    "visual_prompts": ["AI image prompt for the hook"]
  }},
  "segments": [
    {{
      "text": "1-3 complete sentences continuing directly from the previous segment",
      "visual_prompts": [
        "AI image prompt 1 (highly specific: subject, action, framing, lighting, 8k, cinematic)",
        "AI image prompt 2 (variation: different angle or detail of the same scene)"
      ]
    }}
  ],
  "cta": {{
    "text": "1-2 sentences wrapping up the story, ending with a question about what was covered",
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
- All text MUST be complete sentences — never truncate mid-thought to hit a word count.
- Each segment MUST have 2 distinct "visual_prompts".
- Hook and CTA MUST each have 1 distinct "visual_prompts".
- Every visual_prompt MUST name the specific subject from that segment's narration text.
  Generic atmosphere, cityscapes, or abstract scenes are forbidden unless the narration
  explicitly describes them.
- Segments MUST form a continuous narrative — each picks up directly where the last left off.
- The hook MUST introduce the central question or tension the segments resolve.
- The CTA MUST feel like a natural conclusion to the story — not a detached call to action.
- Script language: active voice, second person ("you"), present tense."""

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.7,
        max_tokens=3500,
        timeout=60,
    )
    content = resp.choices[0].message.content
    if not content:
        return None
    return json.loads(_strip_fences(content))


async def _generate_landscape_script(
    topic: str,
    duration: int = 300,
    model: str = FREE_MODELS[0],
    style: str | None = None,
    client: AsyncOpenAI | None = None,
) -> dict:
    """Generate a script for a landscape (16:9) YouTube video up to 10 minutes."""
    if client is None:
        client = get_client()

    system = (
        "You are an expert YouTube video scriptwriter and visual creative director. "
        "You craft well-paced, engaging landscape (16:9) YouTube videos "
        "with precise cinematic visual direction. "
        "The script must read as a single cohesive story from hook to CTA — "
        "never a collection of disconnected facts. "
        "Output strict JSON only — no markdown fences, no extra text, no comments.\n\n"
        "CRITICAL — writing visual_prompts:\n"
        "Every visual_prompt MUST depict the exact subject named in its segment's narration. "
        "Name a concrete noun: a specific person, organism, object, location, or action "
        "from the text. "
        "Never write a generic atmosphere or landscape prompt unless the narration "
        "explicitly describes one.\n"
        "BAD: 'dramatic sky at sunset, cinematic wide shot'\n"
        "GOOD: 'close-up of scientist in white lab coat examining compound under microscope, "
        "fluorescent laboratory lighting, photorealistic, 8k'\n"
        "Each prompt must answer: what specific thing from the narration is visible?"
    )
    if style and style in STYLE_PRESETS:
        system += (
            f"\n\nSTYLE DIRECTIVE — apply this tone and structure throughout:"
            f"\n{STYLE_PRESETS[style]}"
        )

    target_dur = min(duration, 600)
    # edge-tts GuyNeural at +0% rate ≈ 130 WPM (deliberate documentary pacing)
    words_per_min = 130
    target_words = int(target_dur / 60 * words_per_min)
    min_words = int(target_words * 0.90)
    # one segment every ~22 seconds gives good visual rhythm
    n_segments = max(10, target_dur // 22)
    seg_min = max(60, target_words // (n_segments + 2))  # +2 for hook+cta
    seg_max = seg_min + 30

    user = f"""Write a YouTube video script about: "{topic}"
Target duration: {target_dur} seconds ({target_dur // 60}m {target_dur % 60}s).
This script will be read aloud at approximately {words_per_min} words per minute.

Return JSON with exactly this shape:
{{
  "title": "descriptive, search-optimised title, 6-10 words",
  "hook": {{
    "text": "EXACTLY 60-80 words. 3-4 complete sentences introducing the central question.",
    "visual_prompts": [
      "AI image prompt — wide establishing shot, cinematic, 8k",
      "AI image prompt — close detail or reaction shot"
    ]
  }},
  "segments": [
    {{
      "text": "EXACTLY {seg_min}-{seg_max} words. 4-6 sentences. Dense prose, no padding.",
      "visual_prompts": [
        "AI image prompt 1 (highly specific: subject, action, framing, lighting, 8k, cinematic)",
        "AI image prompt 2 (different angle or complementary detail)"
      ]
    }}
  ],
  "cta": {{
    "text": "EXACTLY 50-70 words. 3-4 sentences. Conclude, call back to hook, end with a question.",
    "visual_prompts": [
      "AI image prompt — warm conclusive wide shot",
      "AI image prompt — close call-to-action graphic style"
    ]
  }},
  "viral_package": {{
    "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
    "description": "150-character YouTube description with primary keyword",
    "thumbnail_prompt": "High-contrast YouTube thumbnail, bold text, focal element, 16:9"
  }}
}}

CRITICAL WORD COUNT REQUIREMENTS — these are hard constraints, not suggestions:
- Produce EXACTLY {n_segments} segments.
- Each segment text MUST be {seg_min}-{seg_max} words. Count carefully before writing.
- Hook text MUST be 60-80 words.
- CTA text MUST be 50-70 words.
- Total narration word count (hook + all segments + cta) MUST be at least {min_words} words.
- A short segment is a failure. Dense, substantive prose is required — not thin summaries.
- All text MUST be complete sentences — never truncate mid-thought.
- Each segment MUST have 2 distinct "visual_prompts".
- Hook MUST have 2 visual_prompts. CTA MUST have 2 visual_prompts.
- Every visual_prompt MUST name the specific subject from that segment's narration text.
  Generic atmosphere, cityscapes, or abstract scenes are forbidden unless the narration
  explicitly describes them.
- Segments MUST form a continuous narrative — each picks up directly where the last left off.
- Structure: setup → development → payoff → conclusion across the segments.
- Script MUST conclude with a specific comment-driving question in the CTA."""

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.7,
        max_tokens=12000,
        timeout=120,
    )
    content = resp.choices[0].message.content
    if not content:
        return None
    result = json.loads(_strip_fences(content))
    result["_target_words"] = target_words
    result["_min_words"] = min_words
    return result
