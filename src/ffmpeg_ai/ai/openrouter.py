"""OpenRouter client for free-tier LLM script generation."""
import asyncio
import json
import os
import re
from openai import AsyncOpenAI

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

STYLE_PRESETS: dict[str, str] = {
    "educational": (
        "Tone: authoritative yet accessible — explain like a knowledgeable friend who genuinely "
        "loves the subject. Pacing: measured and clear, one idea per sentence. "
        "Use analogies to make abstract concepts concrete. "
        "Visuals: close-ups of subject, data graphics, diagrams, demonstration shots. "
        "Structure: surprising fact → clear explanation → real-world implication."
    ),
    "dramatic": (
        "Tone: cinematic, high-stakes. Short punchy sentences. Every line raises the tension. "
        "Write as if the fate of something important hangs in the balance. "
        "Visuals: extreme angles, dramatic lighting, motion blur, high contrast, intense close-ups."
        " "
        "Structure: devastating hook → escalating revelation → shocking conclusion."
    ),
    "listicle": (
        "Tone: direct, punchy, slightly irreverent. Number each point explicitly out loud "
        "(say 'Number one', 'Number two'). Very fast pacing — one point, one payoff. "
        "Visuals: bold graphic elements, strong contrast, clear subject per point. "
        "Structure: tease the best item first, deliver it last — classic countdown payoff."
    ),
    "documentary": (
        "Tone: journalistic and reflective. Measured pacing with room to breathe. "
        "Write in third person, past tense where appropriate. Use specific proper nouns, "
        "dates, and named individuals — never vague generalities. "
        "Visuals: naturalistic, archival-style, muted colour palette, establishing shots. "
        "Structure: set the scene → tell the story → reveal the significance."
    ),
    "morris": (
        "Tone: Hamilton Morris — empirical, intimate, intellectually precise. "
        "Write in first person as a researcher immersed in the subject. "
        "Use specific chemical names, pharmacological mechanisms, historical dates, and named "
        "researchers. Never sensationalise; let facts carry the weight. "
        "Sentences are measured and deliberate, occasionally long and clause-heavy when "
        "complexity demands it. Personal anecdote and scientific rigour coexist naturally. "
        "Visuals: close macro laboratory shots, archival photographs, molecular structures, "
        "field work scenes. "
        "Structure: personal entry point → historical/chemical deep dive → societal or "
        "philosophical implication → quiet, unresolved conclusion."
    ),
    "mythology": (
        "Tone: epic oral tradition — as if an elder is telling a story around a fire. "
        "Rich, vivid language. Use the present tense for events to create immediacy. "
        "Name every god, hero, and place specifically. Build wonder without condescension. "
        "Visuals: ancient art, dramatic landscapes, divine imagery, artifact close-ups. "
        "Structure: introduce the world → tell the myth → reveal what it means for us today."
    ),
    "finance": (
        "Tone: smart friend who happens to know money — direct, no jargon, no fluff. "
        "Every claim backed by a specific number or principle. Practical over theoretical. "
        "Visuals: clean data graphics, relatable everyday situations, dollar amounts on screen. "
        "Structure: here is the problem most people have → here is why it happens → "
        "here is exactly what to do instead."
    ),
    "horror": (
        "Tone: slow-burn dread. Understated at first, then escalating. "
        "Let silence and implication do the work — don't over-explain the scary part. "
        "Short declarative sentences at peak tension. "
        "Visuals: low-light environments, isolation, unsettling detail shots, negative space. "
        "Structure: establish normal → introduce wrongness → let it build → end on ambiguity."
    ),
    "curiosity": (
        "Tone: infectious wonder — you can't believe this is real and you need to share it. "
        "Open every line with the most interesting possible angle. "
        "Ask rhetorical questions that the viewer genuinely wants answered. "
        "Visuals: unexpected juxtapositions, scale-revealing shots, before/after comparisons. "
        "Structure: impossible-sounding claim → proof it's true → deeper implication → "
        "what question this raises."
    ),
}

# Free models ranked by quality. Benchmarked 2026-05-20.
FREE_MODELS = [
    "openai/gpt-oss-120b:free",                  # best landscape quality
    "meta-llama/llama-3.3-70b-instruct:free",    # reliable for shorts
    "nousresearch/hermes-3-llama-3.1-405b:free", # highest quality when available
    "nvidia/nemotron-3-super-120b-a12b:free",    # sometimes returns null content
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.2-3b-instruct:free",     # fast fallback
]

_RETRIABLE = (
    "429", "rate", "temporarily", "overloaded",
    "404", "400", "upstream", "provider", "no endpoints",
    "unterminated", "jsondecode", "bad request",
    "developer instruction", "invalid_argument",
    "timeout", "timed out", "connection",
)


def _strip_fences(raw: str) -> str:
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
    """Try model, falling back through FREE_MODELS on rate-limit or null response."""
    models_to_try = [model] + [m for m in FREE_MODELS if m != model]
    client = get_client()
    last_err: Exception | None = None
    for m in models_to_try:
        try:
            result = await _generate_script(
                topic, duration=duration, model=m, style=style, mode=mode, client=client
            )
            if result is None:
                last_err = RuntimeError(f"model {m} returned empty content")
                continue
            # Retry once if word count is too low
            min_words = result.get("_min_words")
            if min_words and _count_words(result) < min_words:
                retry = await _generate_script(
                    topic, duration=duration, model=m, style=style, mode=mode, client=client
                )
                if retry is not None and _count_words(retry) >= _count_words(result):
                    result = retry
            return result
        except Exception as e:
            msg = str(e).lower()
            is_retriable = (
                isinstance(e, json.JSONDecodeError)
                or any(x in msg for x in _RETRIABLE)
            )
            if is_retriable:
                last_err = e
                if any(x in msg for x in ("429", "rate", "overloaded")):
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
) -> dict | None:
    if client is None:
        client = get_client()
    if mode == "landscape":
        return await _generate_landscape_script(
            topic, duration=duration, model=model, style=style, client=client
        )
    return await _generate_shorts_script(
        topic, duration=duration, model=model, style=style, client=client
    )


async def _generate_shorts_script(
    topic: str,
    duration: int = 45,
    model: str = FREE_MODELS[0],
    style: str | None = None,
    client: AsyncOpenAI | None = None,
) -> dict | None:
    if client is None:
        client = get_client()

    system = (
        "You are an expert YouTube Shorts scriptwriter and visual creative director. "
        "You craft emotionally compelling, viral vertical video scripts "
        "with precise cinematic visual direction. "
        "The script must read as a single cohesive story from hook to CTA — "
        "never a collection of disconnected facts. "
        "Output strict JSON only — no markdown fences, no extra text, no comments.\n\n"
        "RULE — writing visual_prompts:\n"
        "Every visual_prompt MUST depict the exact subject named in its segment's narration. "
        "Name a concrete noun: a specific person, organism, object, location, or action. "
        "Generic atmosphere or abstract scenes are forbidden unless the narration describes them.\n"
        "BAD: 'dramatic sky at sunset, cinematic vertical shot'\n"
        "GOOD: 'close-up of Marie Curie in her Paris laboratory, holding a glowing radium "
        "sample, dramatic side-lighting, photorealistic, 8k'"
    )
    if style and style in STYLE_PRESETS:
        system += f"\n\nSTYLE DIRECTIVE:\n{STYLE_PRESETS[style]}"

    target_dur = min(duration, 50)
    n_segments = max(4, target_dur // 8)

    user = f"""Write a YouTube Short script about: "{topic}"

Return JSON with exactly this shape:
{{
  "title": "punchy curiosity-gap title, 5-8 words",
  "hook": {{
    "text": "1 sentence — shocking stat or question that sets up the story",
    "visual_prompts": ["specific AI image prompt for the hook"]
  }},
  "segments": [
    {{
      "text": "1-3 sentences continuing directly from the previous segment",
      "visual_prompts": [
        "highly specific prompt: subject, action, framing, lighting, 8k, cinematic",
        "second prompt: different angle or detail of the same scene"
      ]
    }}
  ],
  "cta": {{
    "text": "1-2 sentences wrapping the story, ending with a question",
    "visual_prompts": ["specific AI image prompt for the CTA"]
  }},
  "viral_package": {{
    "hashtags": ["#tag1", "#tag2", "#tag3"],
    "description": "100-character description for upload",
    "thumbnail_prompt": "High-contrast thumbnail, bold text, viral style"
  }}
}}

Hard requirements:
- Exactly {n_segments} segments.
- Total narration MUST be under 130 words.
- All text must be complete sentences — never truncate mid-thought.
- Each segment needs exactly 2 visual_prompts; hook and CTA need exactly 1.
- Every prompt names the specific subject from that segment's narration.
- Segments form a continuous narrative — each picks up where the last left off.
- Script language: active voice, second person ("you"), present tense."""

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.72,
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
) -> dict | None:
    """Generate a landscape (16:9) script up to 10 minutes long."""
    if client is None:
        client = get_client()

    system = (
        "You are an expert YouTube scriptwriter producing substantial, well-paced "
        "landscape (16:9) videos. Every video must have the density and craft of "
        "a professional documentary or explainer — not thin filler. "
        "Output strict JSON only — no markdown fences, no extra text, no comments.\n\n"
        "RULE — writing visual_prompts:\n"
        "Every visual_prompt MUST depict the exact subject named in its segment's narration. "
        "Name a concrete noun: a specific person, object, location, or action. "
        "Generic landscapes or abstract scenes are forbidden unless the narration describes them.\n"
        "BAD: 'dramatic wide shot of mountains'\n"
        "GOOD: 'wide shot of Gallipoli beach at dawn showing Allied troops landing on shore, "
        "documentary cinematography, muted tones, photorealistic, 8k'"
    )
    if style and style in STYLE_PRESETS:
        system += f"\n\nSTYLE DIRECTIVE:\n{STYLE_PRESETS[style]}"

    target_dur = min(duration, 600)
    words_per_min = 130          # edge-tts GuyNeural at +0% ≈ 130 WPM
    target_words  = int(target_dur / 60 * words_per_min)
    min_words     = int(target_words * 0.88)
    n_segments    = max(10, target_dur // 22)   # visual cut every ~22s
    seg_min       = max(55, target_words // (n_segments + 2))
    seg_max       = seg_min + 35

    user = f"""Write a YouTube video script about: "{topic}"
Target duration: {target_dur}s ({target_dur // 60}m {target_dur % 60}s).
Read aloud at approximately {words_per_min} words per minute.

Return JSON with exactly this shape:
{{
  "title": "search-optimised title, 6-10 words",
  "hook": {{
    "text": "EXACTLY 65-85 words. 4-5 complete sentences. "
            "Open with the single most striking or counterintuitive fact about this topic. "
            "End with the central question the video will answer.",
    "visual_prompts": [
      "wide establishing shot — cinematic, 8k",
      "close detail or reaction shot"
    ]
  }},
  "segments": [
    {{
      "text": "EXACTLY {seg_min}-{seg_max} words. 4-6 dense sentences. No padding. "
              "Each sentence must advance the story or add a specific new fact.",
      "visual_prompts": [
        "highly specific prompt: subject, action, framing, lighting, 8k, cinematic",
        "different angle or complementary detail of the same subject"
      ]
    }}
  ],
  "cta": {{
    "text": "EXACTLY 50-70 words. 3-4 sentences. "
            "Summarise the core insight. Call back to the hook. "
            "End with a specific question that invites debate in the comments.",
    "visual_prompts": [
      "warm conclusive wide shot",
      "close call-to-action graphic style"
    ]
  }},
  "viral_package": {{
    "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
    "description": "150-character YouTube description with primary keyword",
    "thumbnail_prompt": "High-contrast YouTube thumbnail, bold text, focal element, 16:9"
  }}
}}

HARD CONSTRAINTS — failure to meet these is a broken response:
- Exactly {n_segments} segments.
- Each segment: EXACTLY {seg_min}–{seg_max} words. Count before writing.
- Hook: EXACTLY 65–85 words.
- CTA: EXACTLY 50–70 words.
- Total word count (hook + segments + cta) MUST be ≥ {min_words} words.
- All text is complete sentences — no truncation.
- Hook has 2 visual_prompts; each segment has 2; CTA has 2.
- Every visual_prompt names the specific subject from that segment's narration.
- Segments form a continuous narrative with clear setup → development → payoff → conclusion.
- CTA ends with a specific comment-driving question."""

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.68,
        max_tokens=14000,
        timeout=120,
    )
    content = resp.choices[0].message.content
    if not content:
        return None
    result = json.loads(_strip_fences(content))
    result["_target_words"] = target_words
    result["_min_words"]    = min_words
    return result
