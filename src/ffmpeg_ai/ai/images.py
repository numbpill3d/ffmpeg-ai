"""Image acquisition: AI generation (multiple providers) and user-supplied images."""
import asyncio
import os
import random
import unicodedata
import urllib.parse
from pathlib import Path
import httpx

# Cinematic style suffixes appended to AI image prompts
_CINEMATIC_STYLES = [
    "cinematic vertical photography, dramatic lighting, hyper-realistic, ultra detailed, 4K",
    "vertical cinematic shot, professional color grading, rich vivid colors, sharp focus, 8K",
    "dramatic vertical composition, golden hour rim lighting, atmospheric depth, photorealistic",
    "vertical portrait frame, high contrast dramatic lighting, rich color palette, ultra HD",
    "cinematic wide angle vertical shot, moody atmosphere, detailed texture, professional photography",
    "vertical frame, neon-accented dramatic lighting, deep shadows, cyberpunk realism, hyper detailed",
    "vertical composition, soft cinematic bokeh, golden warm tones, shallow depth of field, film grain",
]


def _enrich_prompt(prompt: str) -> str:
    """Append cinematic style modifiers to an image generation prompt."""
    return f"{prompt}, {random.choice(_CINEMATIC_STYLES)}"

# 9:16 vertical for Shorts
IMG_WIDTH = 1080
IMG_HEIGHT = 1920

# Default folder for user-supplied images
USER_IMAGES_DIR = Path(__file__).parents[3] / "assets" / "user_images"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ── User images ──────────────────────────────────────────────────────────────

def load_user_images(images_dir: Path, count: int) -> list[Path]:
    """Return exactly `count` image paths from a directory, cycling if needed."""
    found = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
    if not found:
        raise FileNotFoundError(f"No images found in {images_dir}")
    return [found[i % len(found)] for i in range(count)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize(prompt: str) -> str:
    normalized = unicodedata.normalize("NFKD", prompt)
    return "".join(c if ord(c) < 128 else "-" for c in normalized)


def _make_placeholder(prompt: str, output_path: Path) -> Path:
    """Dark gradient placeholder via Pillow — last resort when all providers fail."""
    from PIL import Image, ImageDraw, ImageFont
    import hashlib

    h = int(hashlib.md5(prompt.encode()).hexdigest()[:6], 16)
    r, g, b = (h >> 16) & 0x7F, (h >> 8) & 0x7F, h & 0x7F

    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), (r, g, b))
    draw = ImageDraw.Draw(img)
    for y in range(IMG_HEIGHT):
        a = int(80 * (1 - y / IMG_HEIGHT))
        draw.line([(0, y), (IMG_WIDTH, y)], fill=(r + a, g + a, b + a))

    words = prompt.split()
    lines, line = [], []
    for word in words:
        if len(" ".join(line + [word])) > 28:
            lines.append(" ".join(line))
            line = [word]
        else:
            line.append(word)
    if line:
        lines.append(" ".join(line))

    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 48)
    except Exception:
        font = ImageFont.load_default()

    total_h = len(lines) * 60
    y_start = (IMG_HEIGHT - total_h) // 2
    for i, txt in enumerate(lines):
        bbox = draw.textbbox((0, 0), txt, font=font)
        x = (IMG_WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x, y_start + i * 60), txt, fill=(220, 220, 220), font=font)

    img.save(str(output_path), "JPEG", quality=85)
    return output_path


# ── Provider: Pollinations.ai (no auth) ──────────────────────────────────────

_POLLINATIONS_MODELS = ["flux-realism", "flux"]


async def _try_pollinations(prompt: str, output_path: Path, seed: int) -> Path | None:
    """Returns path on success, None on failure (don't raise).
    Tries flux-realism first (better quality), falls back to flux.
    """
    encoded = urllib.parse.quote(_sanitize(prompt))
    for model in _POLLINATIONS_MODELS:
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={IMG_WIDTH}&height={IMG_HEIGHT}&seed={seed}&nologo=true&model={model}"
        )
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if len(resp.content) < 1024:
                        break  # bad response, try next model
                    output_path.write_bytes(resp.content)
                    return output_path
            except (httpx.TimeoutException, httpx.NetworkError):
                await asyncio.sleep(3 * (attempt + 1))
            except httpx.HTTPStatusError:
                if attempt < 1:
                    await asyncio.sleep(3 * (attempt + 1))
    return None


# ── Provider: HuggingFace Inference API (free with HF_TOKEN) ─────────────────

# Models tried in order — all support text-to-image
_HF_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "runwayml/stable-diffusion-v1-5",
]

async def _try_huggingface(prompt: str, output_path: Path) -> Path | None:
    """Returns path on success, None if no HF_TOKEN or all models fail."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "inputs": prompt,
        "parameters": {"width": IMG_WIDTH, "height": IMG_HEIGHT},
    }

    for model in _HF_MODELS:
        url = f"https://api-inference.huggingface.co/models/{model}"
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 503:
                    # Model loading — wait the suggested time then retry once
                    import json
                    try:
                        wait = json.loads(resp.content).get("estimated_time", 20)
                    except Exception:
                        wait = 20
                    await asyncio.sleep(min(wait, 30))
                    continue
                if resp.status_code != 200 or len(resp.content) < 1024:
                    break  # try next model
                output_path.write_bytes(resp.content)
                return output_path
            except (httpx.TimeoutException, httpx.NetworkError):
                break  # try next model
    return None


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_image(
    prompt: str,
    output_path: Path,
    seed: int = 42,
    providers: list[str] | None = None,
) -> Path:
    """Generate one image, trying providers in order, placeholder as last resort.

    providers: list of provider names to try, in order. Defaults to all available.
    Available: "pollinations", "huggingface"
    """
    if providers is None:
        providers = ["pollinations", "huggingface"]

    enriched = _enrich_prompt(prompt)
    for provider in providers:
        result = None
        if provider == "pollinations":
            result = await _try_pollinations(enriched, output_path, seed)
        elif provider == "huggingface":
            result = await _try_huggingface(enriched, output_path)
        if result is not None:
            return result

    return _make_placeholder(prompt, output_path)


async def generate_images(
    prompts: list[str],
    out_dir: Path,
    progress=None,
    task_id=None,
    providers: list[str] | None = None,
    max_concurrent: int = 3,
) -> list[Path]:
    """Generate images for all prompts in parallel (up to max_concurrent at once)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max_concurrent)

    async def _gen(i: int, prompt: str) -> Path:
        async with sem:
            result = await generate_image(
                prompt, out_dir / f"frame_{i:03d}.jpg", seed=i * 7, providers=providers
            )
            if progress is not None and task_id is not None:
                progress.advance(task_id)
            return result

    tasks = [_gen(i, prompt) for i, prompt in enumerate(prompts)]
    return list(await asyncio.gather(*tasks))
