"""Scrape trending niche topics and reframe them as Short-ready titles."""
import asyncio
import json
import re
from pathlib import Path

import httpx

from ..ai.openrouter import FREE_MODELS, get_client

NICHE_SUBS = ["esp32", "embedded", "netsec", "linux", "LocalLLaMA", "cybersecurity", "Python"]
NICHE_HN_TERMS = ["esp32", "embedded linux", "ai tools hacking", "python automation", "security"]

SEEN_LOG = Path.home() / ".config" / "ffmpeg-ai" / "seen_topics.txt"


def load_seen() -> set[str]:
    if not SEEN_LOG.exists():
        return set()
    return {ln.strip().lower() for ln in SEEN_LOG.read_text().splitlines() if ln.strip()}


def save_seen(topics: list[str]) -> None:
    SEEN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SEEN_LOG.open("a") as f:
        for t in topics:
            f.write(t.lower() + "\n")


async def _reddit(sub: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(
            f"https://www.reddit.com/r/{sub}/top.json",
            params={"limit": 15, "t": "week"},
            headers={"User-Agent": "ffmpeg-ai/1.0 topic-harvester"},
            timeout=10,
        )
        if r.status_code == 200:
            return [
                {"title": p["data"]["title"], "score": p["data"]["score"], "src": f"r/{sub}"}
                for p in r.json()["data"]["children"]
                if not p["data"].get("stickied") and p["data"]["score"] > 20
            ]
    except Exception:
        pass
    return []


async def _hn(client: httpx.AsyncClient) -> list[dict]:
    out = []
    for term in NICHE_HN_TERMS:
        try:
            r = await client.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": term, "tags": "story", "hitsPerPage": 6,
                        "numericFilters": "points>40"},
                timeout=10,
            )
            if r.status_code == 200:
                for h in r.json().get("hits", []):
                    out.append({"title": h["title"], "score": h.get("points", 0),
                                "src": f"HN:{term}"})
        except Exception:
            pass
    return out


async def _reframe(raw: list[dict], count: int) -> list[str]:
    """Ask LLM to pick and rewrite `count` topics as viral Short titles."""
    client = get_client()
    listing = "\n".join(f"- [{p['src']} {p['score']}pts] {p['title']}" for p in raw[:25])
    resp = await client.chat.completions.create(
        model=FREE_MODELS[0],
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a YouTube Shorts strategist for a tech creator. "
                    "Niche: ESP32/embedded, AI tools, security/hacking, Linux, Python. "
                    "Audience: hackers, makers, self-taught coders. "
                    "Output strict JSON only — no markdown, no prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Trending posts from the creator's communities this week:\n\n{listing}\n\n"
                    f"Pick the {count} most promising for YouTube Shorts. "
                    "For each, rewrite as a compelling curiosity-gap title: "
                    "5–9 words, second person, present tense. No clickbait. "
                    "Favour topics with clear how-to or surprising-fact angles.\n\n"
                    f'Return JSON: {{"topics": ["title 1", "title 2", ...]}}'
                ),
            },
        ],
        max_tokens=400,
        temperature=0.7,
        timeout=30,
    )
    content = (resp.choices[0].message.content or "").strip()
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
    content = re.sub(r"\n?```$", "", content.strip())
    return json.loads(content).get("topics", [])


async def harvest(count: int = 3, skip_seen: bool = True) -> list[str]:
    """Return `count` Short-ready topic strings, deduped against seen log."""
    seen = load_seen() if skip_seen else set()

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_reddit(sub, client) for sub in NICHE_SUBS],
            _hn(client),
            return_exceptions=True,
        )

    posts: list[dict] = []
    for r in results:
        if isinstance(r, list):
            posts.extend(r)

    posts = [p for p in posts if p["title"].lower() not in seen]
    posts.sort(key=lambda p: -p["score"])

    if not posts:
        return []

    topics = await _reframe(posts, count)
    return topics[:count]
