"""Image acquisition: AI generation (multiple providers) and user-supplied images."""
import asyncio
import os
import random
import urllib.parse
from pathlib import Path
from typing import Callable, Optional
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
    encoded = urllib.parse.quote(prompt, safe="")
    for model in _POLLINATIONS_MODELS:
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={IMG_WIDTH}&height={IMG_HEIGHT}&seed={seed}&nologo=true&model={model}"
        )
        for attempt in range(4):  # Increased attempts
            try:
                async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code == 429:
                        # Heavy backoff for rate limits
                        await asyncio.sleep(10 * (attempt + 1) + random.uniform(1, 5))
                        continue
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "")
                    if not ct.startswith("image/") or len(resp.content) < 1024:
                        break  # not an image or too small — try next model
                    output_path.write_bytes(resp.content)
                    return output_path
            except (httpx.TimeoutException, httpx.NetworkError):
                await asyncio.sleep(5 * (attempt + 1))
            except httpx.HTTPStatusError:
                if attempt < 3:
                    await asyncio.sleep(5 * (attempt + 1))
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


# ── Provider: Black Forest Labs (Flux API) ───────────────────────────────────

async def _try_bfl(prompt: str, output_path: Path, seed: int) -> Path | None:
    """Returns path on success, None if no BFL_API_KEY or error.
    Uses FLUX 1.1 [pro] with asynchronous polling.
    """
    key = os.environ.get("BFL_API_KEY", "")
    if not key:
        return None

    headers = {"x-key": key, "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "width": IMG_WIDTH,
        "height": IMG_HEIGHT,
        "seed": seed,
        "prompt_upsampling": False,
        "safety_tolerance": 3,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Submit task
            resp = await client.post("https://api.bfl.ai/v1/flux-pro-1.1", json=payload, headers=headers)
            if resp.status_code != 200:
                return None
            task_id = resp.json().get("id")
            if not task_id:
                return None

            # 2. Poll for result
            for _ in range(30):  # Poll for up to 60s
                await asyncio.sleep(2)
                res_resp = await client.get(f"https://api.bfl.ai/v1/get_result?id={task_id}", headers=headers)
                if res_resp.status_code != 200:
                    continue
                
                data = res_resp.json()
                status = data.get("status")
                if status == "Ready":
                    img_url = data.get("result", {}).get("sample")
                    if not img_url:
                        return None
                    
                    # 3. Download final image
                    img_resp = await client.get(img_url, timeout=60.0)
                    img_resp.raise_for_status()
                    output_path.write_bytes(img_resp.content)
                    return output_path
                elif status in ("Error", "Task not found"):
                    return None
    except Exception:
        return None
    return None


# ── Provider: Fal.ai (Flux) ──────────────────────────────────────────────────

async def _try_fal(prompt: str, output_path: Path, seed: int) -> Path | None:
    """Returns path on success, None if no FAL_KEY or error.
    Uses FLUX.1 [dev] via fal.ai with sync mode.
    """
    key = os.environ.get("FAL_KEY", "")
    if not key:
        return None

    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    payload = {
        "input": {
            "prompt": prompt,
            "image_size": {"width": IMG_WIDTH, "height": IMG_HEIGHT},
            "seed": seed,
        }
    }

    try:
        # Use sync endpoint for immediate response
        url = "https://fal.run/fal-ai/flux/dev?sync_mode=true"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            images = data.get("images", [])
            if not images:
                return None
            
            img_url = images[0].get("url")
            if not img_url:
                return None
            
            # Download final image
            img_resp = await client.get(img_url, timeout=60.0)
            img_resp.raise_for_status()
            output_path.write_bytes(img_resp.content)
            return output_path
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_image(
    prompt: str,
    output_path: Path,
    seed: int = 42,
    providers: list[str] | None = None,
) -> tuple[Path, bool]:
    """Generate one image, trying providers in order, placeholder as last resort.

    Returns (path, is_placeholder). is_placeholder=True means all providers failed.
    providers: list of provider names to try, in order. Defaults to all available.
    Available: "bfl", "fal", "pollinations", "huggingface"
    """
    if providers is None:
        providers = ["bfl", "fal", "pollinations", "huggingface"]

    enriched = _enrich_prompt(prompt)
    for provider in providers:
        result = None
        if provider == "bfl":
            result = await _try_bfl(enriched, output_path, seed)
        elif provider == "fal":
            result = await _try_fal(enriched, output_path, seed)
        elif provider == "pollinations":
            result = await _try_pollinations(enriched, output_path, seed)
        elif provider == "huggingface":
            result = await _try_huggingface(enriched, output_path)
        if result is not None:
            return result, False

    return _make_placeholder(prompt, output_path), True


async def generate_images(
    prompts: list[str],
    out_dir: Path,
    providers: list[str] | None = None,
    max_concurrent: int = 1,
    on_image_done: Optional[Callable[[int, bool], None]] = None,
) -> tuple[list[Path], int]:
    """Generate images for all prompts in parallel (up to max_concurrent at once).

    Returns (paths, placeholder_count). placeholder_count > 0 means some providers failed.
    on_image_done(index, is_placeholder) is called as each image completes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max_concurrent)

    async def _gen(i: int, prompt: str) -> tuple[Path, bool]:
        async with sem:
            path, is_placeholder = await generate_image(
                prompt, out_dir / f"frame_{i:03d}.jpg", seed=i * 7, providers=providers
            )
            if on_image_done is not None:
                on_image_done(i, is_placeholder)
            return path, is_placeholder

    tasks = [_gen(i, prompt) for i, prompt in enumerate(prompts)]
    results = await asyncio.gather(*tasks)
    paths = [path for path, _ in results]
    placeholder_count = sum(1 for _, is_pl in results if is_pl)
    return paths, placeholder_count
