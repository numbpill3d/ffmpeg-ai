# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Python CLI that generates YouTube Shorts (1080×1920, ≤58s) end-to-end from a topic string, using only free AI services. Zero paid API calls — one OpenRouter account (free tier) is the only external dependency.

Pipeline: topic → LLM script → parallel image generation → TTS segments → whisper captions → ffmpeg compose → final encode.

## Commands

```bash
# install
uv pip install -e ".[dev]"

# run
ffmpeg-ai generate "your topic"
python -m ffmpeg_ai generate "your topic"   # equivalent

# dry-run (script only, no video)
ffmpeg-ai generate "your topic" --dry-run

# lint
ruff check src/

# no test suite exists yet
```

`.env` file is supported — `OPENROUTER_API_KEY` is required, `HF_TOKEN` is optional (enables HuggingFace image provider).

## Architecture

### Pipeline flow (`pipeline.py`)

`run_pipeline()` is async and runs inside `asyncio.run()` called from the CLI. All work happens inside a single `tempfile.TemporaryDirectory` — nothing intermediate is persisted. Stages in order:

1. **Script** — `ai/openrouter.py` calls OpenRouter via the `openai` SDK pointed at a different base URL. Returns JSON with `hook`, `segments`, `cta`, `image_prompts`. Has automatic fallback through all `FREE_MODELS` on rate limit, empty response, or provider errors.
2. **TTS** — `ai/tts.py` uses `edge-tts` (no key). Hook, each segment, and CTA are synthesised in parallel then concatenated into `narration.mp3`.
3. **Images** — `ai/images.py` runs all image generations concurrently (semaphore of 3). Provider order: pollinations → huggingface → PIL placeholder. Each prompt gets cinematic style modifiers appended before generation.
4. **Video clips** — each image becomes a clip with a Ken Burns motion via `zoompan` filter. Motion styles are picked so no two adjacent clips use the same style (`_pick_motions`).
5. **Concat** — clips are joined with random `xfade` transitions via a single `filter_complex` chain.
6. **Audio merge** — narration merged in, trimmed to shortest.
7. **Captions** — `video/captions.py` transcribes narration with `faster-whisper` (base, int8, cpu). Primary output is an ASS file with word-level `\kf` karaoke timing (CapCut / TikTok style, 4 words per line). Falls back to SRT if whisper returns no word timestamps.
8. **Music** (optional) — sidechain-compressed background music via `sidechaincompress` filter.
9. **Final encode** — `SHORTS_VIDEO_ARGS` from `video/shorts.py` applied once to produce the output file.

### Key constraints

- All ffmpeg calls live in `video/composer.py`. Never add ffmpeg subprocess calls elsewhere.
- `video/shorts.py` is the single source of truth for format constants (`WIDTH`, `HEIGHT`, `FPS`, `SHORTS_VIDEO_ARGS`).
- The `openai` package is used **only** for OpenRouter calls — base URL is overridden to `https://openrouter.ai/api/v1`.
- Image generation is fire-and-forget with graceful degradation: any provider failure returns `None` and the next is tried; PIL placeholder is the guaranteed last resort.
- `clamp_duration()` enforces the 58s ceiling on the actual narration duration (not the requested duration).

### Free AI services

| Service | Used for | Auth |
|---|---|---|
| OpenRouter free models | LLM script generation | `OPENROUTER_API_KEY` |
| Pollinations.ai (`flux-realism`, `flux`) | Image generation | none |
| HuggingFace Inference API | Image fallback | `HF_TOKEN` (optional) |
| edge-tts | TTS voiceover | none |
| faster-whisper (local) | Caption transcription | none |
