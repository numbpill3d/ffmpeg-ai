# ffmpeg-ai

a python cli that generates youtube shorts end-to-end using only free ai services. give it a topic, get back a vertical 1080x1920 video with voiceover, burned captions, and ai-generated visuals.

---

## screenshot — pipeline running

> _replace this with a screenshot of the rich terminal ui during generation_

![pipeline screenshot placeholder](docs/screenshots/pipeline.png)

---

## screenshot — example output

> _replace this with a frame from a generated short or a side-by-side of input/output_

![output screenshot placeholder](docs/screenshots/output.png)

---

## what it does

1. generates a script from your topic via openrouter (free llm tier)
2. fetches ai images from pollinations.ai for each scene (no auth required)
3. synthesizes voiceover using edge-tts (microsoft tts, completely free)
4. transcribes audio locally with faster-whisper to produce captions
5. composes everything into a shorts-ready mp4 via ffmpeg

zero paid api calls required. one openrouter account for the script step is the only external dependency.

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

## free ai services used

| service            | purpose              | auth required |
|--------------------|----------------------|---------------|
| openrouter         | script generation    | free api key  |
| pollinations.ai    | image generation     | none          |
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
