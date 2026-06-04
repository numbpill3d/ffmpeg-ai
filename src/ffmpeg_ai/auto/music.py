"""Royalty-free background music fetcher — zero cost, no required API key.

Primary source: ccMixter (CC-licensed, no auth).
Enhanced source: Freesound.org (free account, set FREESOUND_API_KEY).
All tracks cached locally so each style is only downloaded once.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
from pathlib import Path
from typing import Optional

import httpx

_CACHE_DIR = Path.home() / ".cache" / "ffmpeg-ai" / "music"
_HEADERS    = {"User-Agent": "ffmpeg-ai/1.0 music-fetcher"}

# ccMixter tag mapping per video style
_CCMIXTER_TAGS: dict[str, list[str]] = {
    "ambient":      ["ambient", "chill", "atmospheric"],
    "upbeat":       ["upbeat", "positive", "energetic"],
    "dramatic":     ["dramatic", "dark", "intense"],
    "cinematic":    ["cinematic", "orchestral", "epic"],
    "documentary":  ["documentary", "ambient", "acoustic"],
    "educational":  ["chill", "background", "positive"],
    "listicle":     ["upbeat", "funky", "energetic"],
    "mythology":    ["orchestral", "epic", "ambient"],
    "horror":       ["dark", "intense", "atmospheric"],
    "finance":      ["corporate", "positive", "upbeat"],
}

# Freesound tag mapping (used when FREESOUND_API_KEY is set)
_FREESOUND_TAGS: dict[str, str] = {
    "ambient":      "ambient background music",
    "upbeat":       "upbeat background music",
    "dramatic":     "dramatic cinematic music",
    "cinematic":    "cinematic orchestral music",
    "documentary":  "documentary ambient music",
    "educational":  "positive background music",
    "listicle":     "energetic upbeat music",
    "mythology":    "epic orchestral music",
    "horror":       "dark atmospheric music",
    "finance":      "corporate background music",
}


def _style_cache_dir(style: str) -> Path:
    return _CACHE_DIR / style


def _cached_tracks(style: str) -> list[Path]:
    d = _style_cache_dir(style)
    if not d.exists():
        return []
    return sorted(d.glob("*.mp3"))


# ── ccMixter (no auth required) ──────────────────────────────────────────────

async def _fetch_ccmixter(
    style: str,
    client: httpx.AsyncClient,
    limit: int = 8,
) -> list[dict]:
    tags = _CCMIXTER_TAGS.get(style, ["ambient"])
    results: list[dict] = []
    for tag in tags[:2]:
        try:
            r = await client.get(
                "http://ccmixter.org/api/query",
                params={
                    "tags": tag,
                    "type": "track",
                    "format": "json",
                    "limit": limit,
                    "lic": "by",        # CC-Attribution — free for commercial use
                },
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                for track in r.json():
                    # files is a list of {file_nicname, download_url, ...}
                    mp3_url = next(
                        (
                            f["download_url"]
                            for f in track.get("files", [])
                            if f.get("file_nicname", "").lower() == "mp3"
                            and f.get("download_url")
                        ),
                        None,
                    )
                    if mp3_url:
                        results.append({
                            "url":    mp3_url,
                            "title":  track.get("upload_name", ""),
                            "source": "ccmixter",
                        })
        except Exception:
            pass
    return results


# ── Freesound (free API key via FREESOUND_API_KEY env var) ───────────────────

async def _fetch_freesound(
    style: str,
    client: httpx.AsyncClient,
    limit: int = 6,
) -> list[dict]:
    key = os.environ.get("FREESOUND_API_KEY", "")
    if not key:
        return []
    query = _FREESOUND_TAGS.get(style, "ambient background music")
    try:
        r = await client.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query":  query,
                "filter": "type:mp3 duration:[60 TO 300]",
                "sort":   "downloads_desc",
                "fields": "id,name,previews,license",
                "page_size": limit,
                "token": key,
            },
            headers=_HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            results = []
            for sound in r.json().get("results", []):
                url = sound.get("previews", {}).get("preview-hq-mp3")
                if url:
                    results.append({
                        "url":    url,
                        "title":  sound.get("name", ""),
                        "source": "freesound",
                    })
            return results
    except Exception:
        pass
    return []


# ── Download + cache ──────────────────────────────────────────────────────────

async def _download(url: str, dest: Path, client: httpx.AsyncClient) -> bool:
    try:
        async with client.stream("GET", url, headers=_HEADERS, timeout=60) as r:
            if r.status_code != 200:
                return False
            ct = r.headers.get("content-type", "")
            if "audio" not in ct and "octet" not in ct and "mpeg" not in ct:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes(8192):
                    f.write(chunk)
        return dest.stat().st_size > 10_000   # sanity: > 10 KB
    except Exception:
        dest.unlink(missing_ok=True)
        return False


async def _ensure_cached(style: str, min_tracks: int = 3) -> list[Path]:
    """Download tracks for a style until we have at least min_tracks cached."""
    cached = _cached_tracks(style)
    if len(cached) >= min_tracks:
        return cached

    async with httpx.AsyncClient(follow_redirects=True) as client:
        candidates = await asyncio.gather(
            _fetch_ccmixter(style, client),
            _fetch_freesound(style, client),
        )
        tracks: list[dict] = []
        for batch in candidates:
            tracks.extend(batch)

    if not tracks:
        return cached

    needed = min_tracks - len(cached)
    random.shuffle(tracks)
    cache_dir = _style_cache_dir(style)
    cache_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for track in tracks[:needed * 2]:
            url = track["url"]
            slug = hashlib.md5(url.encode()).hexdigest()[:12]
            dest = cache_dir / f"{slug}.mp3"
            if dest.exists():
                continue
            ok = await _download(url, dest, client)
            if ok:
                cached.append(dest)
            if len(cached) >= min_tracks:
                break

    return cached


# ── yt-dlp download (works when ccMixter/freesound are unreachable) ──────────

def download_from_url(url: str, style: str) -> Optional[Path]:
    """Download audio from any URL (YouTube, SoundCloud, etc.) via yt-dlp.

    Saves to the style's cache dir as MP3. Returns path on success, None on failure.
    """
    import subprocess
    cache_dir = _style_cache_dir(style)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",         # 128kbps — enough for background
        "--no-playlist",
        "--output", str(cache_dir / "%(id)s.%(ext)s"),
        "--quiet",
        "--no-warnings",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120)
        tracks = sorted(cache_dir.glob("*.mp3"))
        return tracks[-1] if tracks else None
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_music(
    style: str = "ambient",
    prefer_fresh: bool = False,
) -> Optional[Path]:
    """Return a path to a cached royalty-free track matching the style.

    Downloads and caches on first call per style. Returns None if all
    sources fail (pipeline continues without music).
    """
    # Normalise to a known style or fall back to ambient
    resolved = style if style in _CCMIXTER_TAGS else "ambient"
    tracks = await _ensure_cached(resolved)
    if not tracks:
        return None
    if prefer_fresh:
        return random.choice(tracks)
    # Rotate through cached tracks deterministically based on date
    import datetime
    idx = datetime.date.today().toordinal() % len(tracks)
    return tracks[idx]


def list_cached() -> dict[str, list[str]]:
    """Return {style: [filename, ...]} for all cached tracks."""
    result: dict[str, list[str]] = {}
    if not _CACHE_DIR.exists():
        return result
    for style_dir in sorted(_CACHE_DIR.iterdir()):
        if style_dir.is_dir():
            files = sorted(p.name for p in style_dir.glob("*.mp3"))
            if files:
                result[style_dir.name] = files
    return result


def clear_cache(style: Optional[str] = None) -> int:
    """Delete cached tracks. Returns number of files removed."""
    import shutil
    if style:
        target = _style_cache_dir(style)
        if target.exists():
            count = len(list(target.glob("*.mp3")))
            shutil.rmtree(target)
            return count
        return 0
    count = sum(1 for _ in _CACHE_DIR.rglob("*.mp3")) if _CACHE_DIR.exists() else 0
    if _CACHE_DIR.exists():
        shutil.rmtree(_CACHE_DIR)
    return count
