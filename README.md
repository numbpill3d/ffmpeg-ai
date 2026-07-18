# ffmpeg-ai

a python cli that generates youtube shorts and landscape videos end-to-end using mostly free ai services. give it a topic, get back a video with voiceover, burned captions, paced visuals, thumbnails, and either cinematic ken burns motion or faster storyboard cuts.

---

## screenshot — pipeline running

![pipeline screenshot](docs/Sffmpgaiss.png)

---

## screenshot — example output

![output screenshot](docs/ffmpeg2.png)

---

## what it does

1. generates a script from your topic via openrouter (free llm, auto-fallback through 6 models)
2. synthesizes voiceover with edge-tts — hook, each segment, and cta in parallel
3. expands the visual timeline so no segment holds one image forever
4. fetches ai images synced to script segments (7 providers, cascading fallback)
5. renders either cinematic ken burns clips or faster storyboard cuts
6. transcribes audio locally with faster-whisper to produce burned-in captions
7. optionally mixes background music with sidechain compression
8. final encode to spec (shorts 9:16 or landscape 16:9)

output includes a thumbnail jpeg and a machine-readable run report alongside the mp4/job cache.

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
# basic short
ffmpeg-ai generate "the history of the moon"

# landscape video (up to 10 min, storyboard render by default)
ffmpeg-ai generate "history of the roman empire" --mode landscape -d 300

# force cinematic ken burns + xfade, or a fast storyboard proof
ffmpeg-ai generate "lost unix workstations" --mode landscape --render-mode kenburns
ffmpeg-ai generate "lost unix workstations" --mode landscape --render-mode fast-preview

# style preset
ffmpeg-ai generate "deep sea creatures" --style dramatic

# caption style
ffmpeg-ai generate "stoic philosophy" --caption-style plain

# edit the script before rendering
ffmpeg-ai generate "mars colonization" --edit-script

# add background music (auto-ducked under narration)
ffmpeg-ai generate "ancient egypt" --music ~/music/ambient.mp3

# use your own images instead of ai generation
ffmpeg-ai generate "topic" --images-dir ~/my-images/

# batch generate from a topics file (one topic per line, # = comment)
ffmpeg-ai batch topics.txt -o ~/Videos/batch/

# resume a job (uses cached script + images)
ffmpeg-ai generate "the history of the moon"

# force fresh run, ignore all cache
ffmpeg-ai generate "the history of the moon" --fresh

# dry run — script only, no video rendered
ffmpeg-ai generate "any topic" --dry-run

# skip the hook text overlay (useful on Windows where fontconfig is missing)
ffmpeg-ai generate "topic" --no-hook

# force a specific font for overlays/captions (.ttf path)
ffmpeg-ai generate "topic" --font /path/to/MyFont-Bold.ttf

# launch the desktop control panel
ffmpeg-ai gui
```

### windows / hook overlay

on windows, ffmpeg has no fontconfig, so the hook text overlay can fail with
`Fontconfig error: Cannot load default config file` and previously aborted the
whole pipeline. that is now handled:

- the pipeline auto-detects common windows fonts (`C:\Windows\Fonts\*.ttf`).
- if drawtext still fails, the overlay is skipped with a warning and the
  pipeline continues to captions/export (the video is not lost).
- `--no-hook` skips the overlay entirely; `--font <path>` forces a specific
  `.ttf`. both flags also work on `batch`.

---

## output modes

| mode      | resolution    | aspect | max length | default render |
|-----------|---------------|--------|------------|----------------|
| shorts    | 1080 × 1920   | 9:16   | 58 seconds | kenburns       |
| landscape | 1920 × 1080   | 16:9   | 10 minutes | storyboard     |

both modes use h.264 + aac, burned-in captions, and paced visual prompts.

---

## render modes (`--render-mode`)

| render mode  | best for | behavior |
|--------------|----------|----------|
| kenburns     | shorts, cinematic promos | per-image motion clips plus xfade transitions |
| storyboard   | longform, essay, slide-card videos | quick still-card cuts without expensive xfade chains |
| fast-preview | proof renders | storyboard-style preview path for checking script, timing, and visuals before a slower final render |

if omitted, shorts use `kenburns`; landscape uses `storyboard` so 5–10 minute videos don't crawl through a giant xfade furnace by default.

---

## style presets (`--style`)

| preset       | tone                                              |
|--------------|---------------------------------------------------|
| educational  | authoritative, measured, surprising fact → implication |
| dramatic     | cinematic, intense, short punchy sentences        |
| listicle     | countdown format, numbered points, fast cuts      |
| documentary  | journalistic, reflective, context → story → insight |
| morris       | empirical, intimate, pharmacological precision — Hamilton Morris register |
| mythology    | epic oral-tradition storytelling around gods, heroes, and places |
| finance      | practical money explanations with concrete numbers and actions |
| horror       | slow-burn dread with restrained escalation |
| curiosity    | wonder-driven explanations of impossible-sounding facts |

---

## caption styles (`--caption-style`)

| style       | description                                      |
|-------------|--------------------------------------------------|
| karaoke     | word-level highlight, 3 words per line (default) |
| plain       | clean subtitles, 6 words per line                |
| bold-center | large centered text, 3 words per line            |

---

## image providers

tried in this order, falling back on failure. all paid keys are optional.

| provider       | env var              | notes                              |
|----------------|----------------------|------------------------------------|
| bfl            | `BFL_API_KEY`        | flux 1.1 pro (paid)                |
| fal            | `FAL_KEY`            | flux dev via fal.ai (paid)         |
| prodia         | `PRODIA_TOKEN`       | flux schnell, ultra-fast (paid)    |
| pollinations   | —                    | flux-realism / flux, free, no key  |
| huggingface    | `HF_TOKEN`           | flux schnell + sdxl fallback       |
| stable_horde   | `STABLE_HORDE_API_KEY` | community cluster, guest key built-in |
| together       | `TOGETHER_API_KEY`   | flux schnell free tier             |

override the order with `--providers bfl,fal,pollinations`.

---

## job cache

each job is cached at `~/.cache/ffmpeg-ai/jobs/<slug>/`:

- `script.json` — reused on re-run unless `--fresh`
- `images/frame_*.jpg` — reused if count matches
- `tts/` — cached by script+voice+rate hash; re-synthesized on any change
- `run_report.json` — machine-readable summary of the run: cache hits, render mode, visual pacing, provider attempts, caption/thumbnail outcome, placeholders, and artifact paths

re-running the same topic resumes from cached data automatically.

---

## project structure

```
src/ffmpeg_ai/
├── cli.py           # typer entrypoint + all commands
├── pipeline.py      # orchestrates the full generation pipeline
├── ai/
│   ├── openrouter.py    # llm client, model fallback logic
│   ├── images.py        # multi-provider image generation
│   └── tts.py           # edge-tts voiceover
├── video/
│   ├── composer.py      # all ffmpeg subprocess calls
│   ├── captions.py      # faster-whisper + ass/srt generation
│   └── shorts.py        # video spec constants (resolution, fps, codec args)
└── ui/
    ├── display.py        # animated ascii banner
    └── widgets.py        # rich live pipeline tracker
└── gui.py               # retro Tk desktop operator panel
```

---

## env vars

| var                   | required | purpose                          |
|-----------------------|----------|----------------------------------|
| `OPENROUTER_API_KEY`  | yes      | llm script generation (free tier)|
| `BFL_API_KEY`         | no       | black forest labs flux 1.1       |
| `FAL_KEY`             | no       | fal.ai flux dev                  |
| `PRODIA_TOKEN`        | no       | prodia flux schnell              |
| `HF_TOKEN`            | no       | huggingface inference            |
| `STABLE_HORDE_API_KEY`| no       | registered horde key (priority)  |
| `TOGETHER_API_KEY`    | no       | together ai flux schnell free    |
| `EDITOR`              | no       | editor for `--edit-script`       |

---

## dev

```bash
uv pip install -e ".[dev]"
ruff check src/
pytest
```

---

## license

mit
