# ffmpeg-ai

a python cli that generates youtube shorts end-to-end using only free ai services. give it a topic, get back a vertical 1080x1920 video with voiceover, burned captions, and ai-generated visuals.

---

## screenshot — pipeline running

![pipeline screenshot](docs/Sffmpgaiss.png)

---

## screenshot — example output

![output screenshot](docs/ffmpeg2.png)

---

## what it does

1. generates a script from your topic via openrouter
2. fetches high-quality AI images (supports **Flux 1.1** via BFL/Fal.ai/Prodia, or free fallbacks)
3. **Semantic Sync:** images are semantically linked to script segments for maximum relevance
4. synthesizes voiceover using edge-tts (microsoft tts, completely free)
5. transcribes audio locally with faster-whisper to produce captions
6. composes everything into a shorts-ready mp4 via ffmpeg with cinematic motion

---

## install

requires python 3.11+, ffmpeg on your `$PATH`, and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/numbpill3d/ffmpeg-ai.git
cd ffmpeg-ai
uv pip install -e ".[dev]"
```

copy `.env.example` to `.env` and add your openrouter key:

```bash
cp .env.example .env
# edit .env — get a free key at https://openrouter.ai
```

---

## usage

```bash
# generate a short from a topic
python -m ffmpeg_ai generate "the history of the moon"

# preview the pipeline steps without making api calls
python -m ffmpeg_ai generate --dry-run "any topic"
```

or via the installed entrypoint:

```bash
ffmpeg-ai generate "deep sea creatures ranked"
```

---

## output spec

| property   | value              |
|------------|--------------------|
| resolution | 1080 x 1920 (9:16) |
| framerate  | 30 fps             |
| max length | 60 seconds         |
| video codec| h.264              |
| audio codec| aac                |
| captions   | burned-in (ass)    |

---

## ai services used

| service            | purpose              | auth required |
|--------------------|----------------------|---------------|
| openrouter         | script generation    | api key       |
| **Flux (BFL/Fal)** | premium images       | optional      |
| pollinations.ai    | free image fallback  | none          |
| edge-tts           | voiceover / tts      | none          |
| faster-whisper     | local transcription  | none (local)  |

---

## project structure

```
src/ffmpeg_ai/
├── cli.py           # typer entrypoint
├── pipeline.py      # full generation pipeline
├── ai/
│   ├── openrouter.py    # llm client
│   ├── images.py        # pollinations image fetcher
│   └── tts.py           # edge-tts voiceover
├── video/
│   ├── composer.py      # all ffmpeg subprocess calls
│   ├── captions.py      # whisper + ass/srt generation
│   └── shorts.py        # shorts constants and helpers
└── ui/
    ├── display.py        # ascii banner, pipeline status
    └── widgets.py        # rich renderables
```

---

## dev

```bash
uv pip install -e ".[dev]"
pytest
ruff check src/
```

---

## license

mit
