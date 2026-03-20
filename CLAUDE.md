# ffmpeg-ai — Claude Code Project Config

## What This Is
A Python CLI tool that generates YouTube Shorts (1080x1920, vertical 9:16) using free AI services.
Full pipeline: topic → script → images/visuals → TTS → captions → ffmpeg composition → output.

## Goals
- Rich, data-driven terminal UI: ASCII art headers, live progress widgets, spinners, stats panels
- Use only free AI: OpenRouter free-tier models, Pollinations.ai (images, no auth), edge-tts (TTS)
- Output quality Shorts that are better than naive AI generation (proper pacing, B-roll logic, burned captions)
- Keep dependencies minimal and installable via pip/uv

## Stack
- **Python 3.11+**
- **rich** — progress bars, panels, tables, live displays, ASCII widgets
- **textual** (optional) — interactive TUI widgets if needed
- **ffmpeg** — all video/audio composition (called via subprocess, not ffmpeg-python wrapper)
- **httpx** — async HTTP for OpenRouter + Pollinations API calls
- **edge-tts** — free Microsoft TTS (no key needed)
- **openai SDK** pointed at OpenRouter base URL for free model access
- **faster-whisper** or **whisper.cpp** — local transcription for auto-captions

## Free AI Services
- **OpenRouter free models**: `meta-llama/llama-3.1-8b-instruct:free`, `google/gemma-3-12b-it:free`, etc.
- **Pollinations.ai**: `https://image.pollinations.ai/prompt/{prompt}` — free image gen, no auth
- **edge-tts**: pip package, wraps Microsoft Edge TTS, completely free
- **Whisper** (local): for caption generation from audio

## Project Structure
```
ffmpeg-ai/
├── CLAUDE.md
├── pyproject.toml
├── src/ffmpeg_ai/
│   ├── cli.py          # Typer CLI entry point
│   ├── pipeline.py     # Orchestrates the full Short generation pipeline
│   ├── ai/
│   │   ├── openrouter.py   # OpenRouter client (script, prompts)
│   │   ├── images.py       # Pollinations image generation
│   │   └── tts.py          # edge-tts voiceover
│   ├── video/
│   │   ├── composer.py     # ffmpeg subprocess calls
│   │   ├── captions.py     # whisper + ASS/SRT subtitle generation
│   │   └── shorts.py       # YouTube Shorts-specific constants + helpers
│   └── ui/
│       ├── widgets.py      # Custom rich renderables (progress, stats)
│       └── display.py      # ASCII banner, pipeline status display
└── assets/
    └── fonts/              # fonts for ffmpeg subtitle rendering
```

## Key Conventions
- All ffmpeg calls go through `video/composer.py` — never call ffmpeg inline elsewhere
- YouTube Shorts: 1080x1920, 9:16, ≤60s, 30fps, H.264, AAC audio
- Use `rich.live` + `rich.panel` for real-time pipeline status
- Async-first for AI API calls (httpx.AsyncClient), sync for ffmpeg subprocess
- Store generated assets in a temp dir per run, clean up after output
- OpenRouter key loaded from `OPENROUTER_API_KEY` env var (or `.env` file)

## Dev Commands
```bash
uv pip install -e ".[dev]"   # install in editable mode
python -m ffmpeg_ai generate "your topic here"
python -m ffmpeg_ai generate --dry-run   # show pipeline without running
```

## Autonomy
Ask before: pushing to git, installing system packages, making API calls that cost money.
Auto-approved: file edits, creating project files, running ffmpeg locally, pip installs.
