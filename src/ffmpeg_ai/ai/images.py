"""Image acquisition: AI generation (multiple providers) and user-supplied images."""
import asyncio
import base64
import json
import os
import random
import urllib.parse
from pathlib import Path
from typing import Callable, Optional
import httpx

# Serialise all outbound Pollinations HTTP calls.  Their free tier rate-limits
# per IP, and concurrent asyncio coroutines hit the same bucket simultaneously.
# Holding the lock only during the actual request-response round-trip; backoff
# sleeps happen outside it so other coroutines aren't starved during a 429.
# Lazily initialised per event loop — batch mode calls asyncio.run() multiple
# times, each creating a new loop; a module-level Lock would be bound to the
# first loop and raise RuntimeError for all subsequent topics.

def _get_pollinations_lock() -> asyncio.Lock:
    """Get or create a lock bound to the current event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    # Locks are bound to their creating loop; we need a fresh one per loop
    lock_attr = f"_pollinations_lock_{id(loop) if loop else 'none'}"
    if not hasattr(_get_pollinations_lock, lock_attr):
        setattr(_get_pollinations_lock, lock_attr, asyncio.Lock())
    return getattr(_get_pollinations_lock, lock_attr)

# Cinematic style suffixes — portrait (9:16) and landscape (16:9) variants
_CINEMATIC_PORTRAIT = [
    "cinematic vertical photography, dramatic lighting, hyper-realistic, ultra detailed, 4K",
    "vertical cinematic shot, professional color grading, rich vivid colors, sharp focus, 8K",
    "dramatic vertical composition, golden hour rim lighting, atmospheric depth, photorealistic",
    "vertical portrait frame, high contrast dramatic lighting, rich color palette, ultra HD",
    "cinematic vertical shot, moody atmosphere, detailed texture, professional photography",
    "vertical frame, neon-accented lighting, deep shadows, cyberpunk realism, hyper detailed",
    "vertical composition, cinematic bokeh, golden warm tones, shallow depth of field, film grain",
]

_CINEMATIC_LANDSCAPE = [
    "cinematic wide shot, dramatic lighting, hyper-realistic, ultra detailed, 4K, 16:9",
    "landscape cinematic photography, professional color grading, vivid colors, sharp focus, 8K",
    "dramatic wide composition, golden hour rim lighting, atmospheric depth, photorealistic",
    "cinematic establishing shot, high contrast dramatic lighting, rich color palette, ultra HD",
    "documentary wide angle shot, moody atmosphere, detailed texture, professional cinematography",
    "widescreen frame, neon-accented lighting, deep shadows, cinematic realism, hyper detailed",
    "landscape composition, soft cinematic bokeh, warm tones, shallow depth of field, anamorphic",
]

# Defaults for shorts (9:16)
IMG_WIDTH = 1080
IMG_HEIGHT = 1920

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Default folder for user-supplied images
USER_IMAGES_DIR = Path(__file__).parents[3] / "assets" / "user_images"


def _enrich_prompt(prompt: str, width: int, height: int) -> str:
    """Append cinematic style modifiers appropriate for the target aspect ratio."""
    styles = _CINEMATIC_LANDSCAPE if width > height else _CINEMATIC_PORTRAIT
    return f"{prompt}, {random.choice(styles)}"


def _clamp_dims(width: int, height: int, max_side: int, multiple: int = 32) -> tuple[int, int]:
    """Scale dims to fit max_side while preserving aspect ratio, rounded to multiple."""
    scale = min(1.0, max_side / max(width, height))
    w = max(multiple, round(width * scale / multiple) * multiple)
    h = max(multiple, round(height * scale / multiple) * multiple)
    return w, h


# ── User images ──────────────────────────────────────────────────────────────

def load_user_images(images_dir: Path, count: int) -> list[Path]:
    """Return exactly `count` image paths from a directory, cycling if needed."""
    found = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
    if not found:
        raise FileNotFoundError(f"No images found in {images_dir}")
    return [found[i % len(found)] for i in range(count)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_placeholder(prompt: str, output_path: Path, width: int, height: int) -> Path:
    """Dark gradient placeholder via Pillow — last resort when all providers fail."""
    from PIL import Image, ImageDraw, ImageFont
    import hashlib

    h = int(hashlib.md5(prompt.encode()).hexdigest()[:6], 16)
    r, g, b = (h >> 16) & 0x7F, (h >> 8) & 0x7F, h & 0x7F

    img = Image.new("RGB", (width, height), (r, g, b))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        a = int(80 * (1 - y / height))
        draw.line([(0, y), (width, y)], fill=(r + a, g + a, b + a))

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
    y_start = (height - total_h) // 2
    for i, txt in enumerate(lines):
        bbox = draw.textbbox((0, 0), txt, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y_start + i * 60), txt, fill=(220, 220, 220), font=font)

    img.save(str(output_path), "JPEG", quality=85)
    return output_path


# ── Provider: Pollinations.ai (no auth) ──────────────────────────────────────

_POLLINATIONS_MODELS = ["flux-realism", "flux"]


async def _try_pollinations(
    prompt: str, output_path: Path, seed: int, width: int, height: int
) -> Path | None:
    """Returns path on success, None on failure."""
    encoded = urllib.parse.quote(prompt, safe="")
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        for model in _POLLINATIONS_MODELS:
            url = (
                f"https://image.pollinations.ai/prompt/{encoded}"
                f"?width={width}&height={height}&seed={seed}&nologo=true&model={model}"
            )
            for attempt in range(4):
                try:
                    async with _get_pollinations_lock():
                        resp = await client.get(url)
                    if resp.status_code == 429:
                        await asyncio.sleep(10 * (attempt + 1) + random.uniform(0, 30))
                        continue
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "")
                    if not ct.startswith("image/") or len(resp.content) < 1024:
                        break
                    output_path.write_bytes(resp.content)
                    return output_path
                except (httpx.TimeoutException, httpx.NetworkError):
                    await asyncio.sleep(5 * (attempt + 1))
                except httpx.HTTPStatusError:
                    if attempt < 3:
                        await asyncio.sleep(5 * (attempt + 1))
    return None


# ── Provider: HuggingFace Inference API (free with HF_TOKEN) ─────────────────

_HF_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "runwayml/stable-diffusion-v1-5",
]


async def _try_huggingface(
    prompt: str, output_path: Path, width: int, height: int
) -> Path | None:
    """Returns path on success, None if no HF_TOKEN or all models fail."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "inputs": prompt,
        "parameters": {"width": width, "height": height},
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        for model in _HF_MODELS:
            url = f"https://router.huggingface.co/hf-inference/models/{model}"
            for attempt in range(2):
                try:
                    resp = await client.post(url, json=body, headers=headers)
                    if resp.status_code == 503:
                        try:
                            wait = json.loads(resp.content).get("estimated_time", 20)
                        except Exception:
                            wait = 20
                        await asyncio.sleep(min(wait, 30))
                        continue
                    if resp.status_code != 200 or len(resp.content) < 1024:
                        break
                    output_path.write_bytes(resp.content)
                    return output_path
                except (httpx.TimeoutException, httpx.NetworkError):
                    break
    return None


# ── Provider: Black Forest Labs (Flux API) ───────────────────────────────────

async def _try_bfl(
    prompt: str, output_path: Path, seed: int, width: int, height: int
) -> Path | None:
    """Returns path on success, None if no BFL_API_KEY or error.
    BFL max dimension is 1440; dims are snapped to multiples of 32.
    """
    key = os.environ.get("BFL_API_KEY", "")
    if not key:
        return None

    w, h = _clamp_dims(width, height, max_side=1440, multiple=32)
    headers = {"x-key": key, "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "width": w,
        "height": h,
        "seed": seed,
        "prompt_upsampling": False,
        "safety_tolerance": 3,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.bfl.ai/v1/flux-pro-1.1",
                json=payload, headers=headers,
            )
            if resp.status_code != 200:
                return None
            task_id = resp.json().get("id")
            if not task_id:
                return None

            for _ in range(30):
                await asyncio.sleep(2)
                res_resp = await client.get(
                    f"https://api.bfl.ai/v1/get_result?id={task_id}",
                    headers=headers,
                )
                if res_resp.status_code != 200:
                    continue
                data = res_resp.json()
                status = data.get("status")
                if status == "Ready":
                    img_url = data.get("result", {}).get("sample")
                    if not img_url:
                        return None
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

async def _try_fal(
    prompt: str, output_path: Path, seed: int, width: int, height: int
) -> Path | None:
    """Returns path on success, None if no FAL_KEY or error."""
    key = os.environ.get("FAL_KEY", "")
    if not key:
        return None

    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    payload = {
        "input": {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "seed": seed,
        }
    }

    try:
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
            img_resp = await client.get(img_url, timeout=60.0)
            img_resp.raise_for_status()
            output_path.write_bytes(img_resp.content)
            return output_path
    except Exception:
        return None


# ── Provider: Prodia ─────────────────────────────────────────────────────────

async def _try_prodia(
    prompt: str, output_path: Path, seed: int, width: int, height: int
) -> Path | None:
    """Returns path on success, None if no PRODIA_TOKEN or error."""
    token = os.environ.get("PRODIA_TOKEN", "")
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "type": "inference.flux.schnell.txt2img.v1",
        "config": {
            "prompt": prompt,
            "width": width,
            "height": height,
            "seed": seed,
            "steps": 4,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://inference.prodia.com/v2/job",
                json=payload, headers=headers,
            )
            if resp.status_code != 200:
                return None
            job_id = resp.json().get("job")
            if not job_id:
                return None

            for _ in range(20):
                await asyncio.sleep(1.5)
                res_resp = await client.get(
                    f"https://inference.prodia.com/v2/job/{job_id}",
                    headers=headers,
                )
                if res_resp.status_code != 200:
                    continue
                data = res_resp.json()
                status = data.get("status")
                if status == "succeeded":
                    img_resp = await client.get(
                        f"https://inference.prodia.com/v2/job/{job_id}",
                        headers={**headers, "Accept": "image/jpeg"},
                        timeout=60.0,
                    )
                    img_resp.raise_for_status()
                    output_path.write_bytes(img_resp.content)
                    return output_path
                elif status == "failed":
                    return None
    except Exception:
        return None
    return None


# ── Provider: Stable Horde (free community cluster, no key needed) ────────────

# SDXL dimension buckets — pick closest 16:9 or 9:16 based on orientation
_HORDE_LANDSCAPE = (1344, 768)
_HORDE_PORTRAIT  = (768, 1344)


async def _try_stable_horde(
    prompt: str, output_path: Path, seed: int, width: int, height: int
) -> Path | None:
    """Community GPU cluster — guest key built-in, register at aihorde.net for priority."""
    key = os.environ.get("STABLE_HORDE_API_KEY", "0000000000")
    w, h = _HORDE_LANDSCAPE if width > height else _HORDE_PORTRAIT
    headers = {"apikey": key, "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "params": {
            "width": w,
            "height": h,
            "steps": 25,
            "sampler_name": "k_euler_a",
            "n": 1,
            "seed": str(seed),
        },
        "models": ["AlbedoBase XL (SDXL)"],
        "r2": False,
        "shared": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://stablehorde.net/api/v2/generate/async",
                json=payload, headers=headers,
            )
            if resp.status_code not in (200, 202):
                return None
            job_id = resp.json().get("id")
            if not job_id:
                return None

            for _ in range(60):
                await asyncio.sleep(5)
                check = await client.get(
                    f"https://stablehorde.net/api/v2/generate/check/{job_id}",
                    headers=headers,
                )
                if check.status_code != 200:
                    continue
                data = check.json()
                if data.get("faulted"):
                    return None
                # Abort if no workers can serve this request
                if not data.get("is_possible", True):
                    return None
                # Abort if queue wait is > 3 min (guest key will never win priority)
                if not data.get("done") and data.get("wait_time", 0) > 180:
                    return None
                if not data.get("done"):
                    continue
                status = await client.get(
                    f"https://stablehorde.net/api/v2/generate/status/{job_id}",
                    headers=headers, timeout=60.0,
                )
                if status.status_code != 200:
                    return None
                gens = status.json().get("generations", [])
                if not gens:
                    return None
                img_b64 = gens[0].get("img", "")
                if not img_b64 or len(img_b64) < 100:
                    return None
                output_path.write_bytes(base64.b64decode(img_b64))
                return output_path
    except Exception:
        return None
    return None


# ── Provider: Together AI (free FLUX.1-schnell tier) ─────────────────────────

async def _try_together(
    prompt: str, output_path: Path, seed: int, width: int, height: int
) -> Path | None:
    """Returns path on success, None if no TOGETHER_API_KEY or error."""
    key = os.environ.get("TOGETHER_API_KEY", "")
    if not key:
        return None

    # Together supports landscape: swap to 1792x1024 for 16:9
    tw, th = (1792, 1024) if width > height else (1024, 1792)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "black-forest-labs/FLUX.1-schnell-Free",
        "prompt": prompt,
        "width": tw,
        "height": th,
        "steps": 4,
        "n": 1,
        "seed": seed,
        "response_format": "b64_json",
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://api.together.xyz/v1/images/generations",
                json=payload, headers=headers,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            images = data.get("data", [])
            if not images:
                return None
            b64 = images[0].get("b64_json", "")
            if not b64 or len(b64) < 100:
                return None
            output_path.write_bytes(base64.b64decode(b64))
            return output_path
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

_ALL_PROVIDERS = [
    "bfl", "fal", "prodia", "pollinations", "huggingface", "stable_horde", "together",
]


async def generate_image(
    prompt: str,
    output_path: Path,
    seed: int = 42,
    providers: list[str] | None = None,
    width: int = IMG_WIDTH,
    height: int = IMG_HEIGHT,
    on_attempt: Optional[Callable[[str, bool], None]] = None,
) -> tuple[Path, bool]:
    """Generate one image, trying providers in order, placeholder as last resort.

    Returns (path, is_placeholder). is_placeholder=True means all providers failed.
    """
    if providers is None:
        providers = _ALL_PROVIDERS

    enriched = _enrich_prompt(prompt, width, height)
    for provider in providers:
        result = None
        if provider == "bfl":
            result = await _try_bfl(enriched, output_path, seed, width, height)
        elif provider == "fal":
            result = await _try_fal(enriched, output_path, seed, width, height)
        elif provider == "prodia":
            result = await _try_prodia(enriched, output_path, seed, width, height)
        elif provider == "pollinations":
            result = await _try_pollinations(enriched, output_path, seed, width, height)
        elif provider == "huggingface":
            result = await _try_huggingface(enriched, output_path, width, height)
        elif provider == "stable_horde":
            result = await _try_stable_horde(enriched, output_path, seed, width, height)
        elif provider == "together":
            result = await _try_together(enriched, output_path, seed, width, height)
        if result is not None:
            if on_attempt is not None:
                on_attempt(provider, True)
            return result, False
        if on_attempt is not None:
            on_attempt(provider, False)

    # Last-chance retry: stripped prompt + downscaled dims via pollinations.
    # The main loop already tried full-size; large dims (1920x1080) trigger rate limits.
    # ffmpeg upscales the image in the Ken Burns filter chain so resolution loss is acceptable.
    bare = prompt[:100]
    for scale_denom in (2, 3):
        rw = max(64, round(width / scale_denom / 32) * 32)
        rh = max(64, round(height / scale_denom / 32) * 32)
        result = await _try_pollinations(bare, output_path, seed + 9973 + scale_denom, rw, rh)
        if result is not None:
            if on_attempt is not None:
                on_attempt(f"pollinations:retry-{scale_denom}", True)
            return result, False
        if on_attempt is not None:
            on_attempt(f"pollinations:retry-{scale_denom}", False)

    return _make_placeholder(prompt, output_path, width, height), True


async def generate_images(
    prompts: list[str],
    out_dir: Path,
    providers: list[str] | None = None,
    max_concurrent: int = 4,
    on_image_done: Optional[Callable[[int, bool], None]] = None,
    on_attempt: Optional[Callable[[int, str, bool], None]] = None,
    width: int = IMG_WIDTH,
    height: int = IMG_HEIGHT,
) -> tuple[list[Path], int]:
    """Generate images for all prompts in parallel (up to max_concurrent at once).

    Returns (paths, placeholder_count).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max_concurrent)

    async def _gen(i: int, prompt: str) -> tuple[Path, bool]:
        def _attempt(provider: str, ok: bool) -> None:
            if on_attempt is not None:
                on_attempt(i, provider, ok)

        async with sem:
            path, is_placeholder = await generate_image(
                prompt, out_dir / f"frame_{i:03d}.jpg",
                seed=i * 7, providers=providers, width=width, height=height,
                on_attempt=_attempt if on_attempt is not None else None,
            )
            if on_image_done is not None:
                on_image_done(i, is_placeholder)
            return path, is_placeholder

    tasks = [_gen(i, prompt) for i, prompt in enumerate(prompts)]
    results = await asyncio.gather(*tasks)
    paths = [path for path, _ in results]
    placeholder_count = sum(1 for _, is_pl in results if is_pl)
    return paths, placeholder_count
