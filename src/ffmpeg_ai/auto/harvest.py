"""Scrape trending niche topics and reframe them as Short-ready titles."""
import asyncio
import datetime
import json
import re
from pathlib import Path

import httpx

from ..ai.openrouter import FREE_MODELS, get_client

NICHE_SUBS = ["esp32", "embedded", "netsec", "linux", "LocalLLaMA", "cybersecurity", "Python"]
NICHE_HN_TERMS = ["esp32", "embedded linux", "ai tools hacking", "python automation", "security"]

SEEN_LOG = Path.home() / ".config" / "ffmpeg-ai" / "seen_topics.txt"


def _seen_log(channel: str | None = None) -> Path:
    if channel:
        return Path.home() / ".config" / "ffmpeg-ai" / "channels" / channel / "seen_topics.txt"
    return SEEN_LOG


def load_seen(channel: str | None = None) -> set[str]:
    p = _seen_log(channel)
    if not p.exists():
        return set()
    return {ln.strip().lower() for ln in p.read_text().splitlines() if ln.strip()}


def save_seen(topics: list[str], channel: str | None = None) -> None:
    p = _seen_log(channel)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
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


async def _hn(terms: list[str], client: httpx.AsyncClient) -> list[dict]:
    out = []
    for term in terms:
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


async def _wikipedia_random(client: httpx.AsyncClient, count: int = 8) -> list[dict]:
    results = []
    tasks = [
        client.get(
            "https://en.wikipedia.org/api/rest_v1/page/random/summary",
            headers={"User-Agent": "ffmpeg-ai/1.0 topic-harvester"},
            timeout=10,
        )
        for _ in range(count)
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    for r in responses:
        try:
            if not isinstance(r, Exception) and r.status_code == 200:
                data = r.json()
                if data.get("type") == "standard" and len(data.get("extract", "")) > 100:
                    results.append({
                        "title": data["title"],
                        "score": 80,
                        "src": "wiki:random",
                    })
        except Exception:
            pass
    return results


async def _wikipedia_featured(client: httpx.AsyncClient) -> list[dict]:
    today = datetime.date.today()
    try:
        r = await client.get(
            f"https://en.wikipedia.org/api/rest_v1/feed/featured/"
            f"{today.year}/{today.month:02d}/{today.day:02d}",
            headers={"User-Agent": "ffmpeg-ai/1.0 topic-harvester"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            results = []
            if "tfa" in data:
                results.append({
                    "title": data["tfa"]["title"],
                    "score": 120,
                    "src": "wiki:featured",
                })
            for article in data.get("mostread", {}).get("articles", [])[:5]:
                results.append({
                    "title": article["title"].replace("_", " "),
                    "score": article.get("views", 50),
                    "src": "wiki:mostread",
                })
            return results
    except Exception:
        pass
    return []


async def _wikipedia_category(category: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmlimit": 15,
                "cmtype": "page",
                "format": "json",
            },
            headers={"User-Agent": "ffmpeg-ai/1.0 topic-harvester"},
            timeout=10,
        )
        if r.status_code == 200:
            members = r.json().get("query", {}).get("categorymembers", [])
            return [
                {"title": m["title"], "score": 70, "src": f"wiki:cat:{category}"}
                for m in members
            ]
    except Exception:
        pass
    return []


async def _reframe(
    raw: list[dict],
    count: int,
    niche: str = "technology, ESP32/embedded, AI tools, security, Linux",
    audience: str = "hackers, makers, self-taught coders",
) -> list[str]:
    client = get_client()
    listing = "\n".join(f"- [{p['src']} {p['score']}pts] {p['title']}" for p in raw[:30])
    resp = await client.chat.completions.create(
        model=FREE_MODELS[0],
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a YouTube strategist for a creator in the {niche} niche. "
                    f"Audience: {audience}. "
                    "Output strict JSON only — no markdown, no prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Content ideas from this creator's niche this week:\n\n{listing}\n\n"
                    f"Pick the {count} most promising for YouTube videos. "
                    "For each, rewrite as a compelling curiosity-gap title: "
                    "5–9 words, second person, present tense. No clickbait. "
                    "Favour topics with clear how-to or surprising-fact angles.\n\n"
                    f'Return JSON: {{"topics": ["title 1", "title 2", ...]}}'
                ),
            },
        ],
        max_tokens=500,
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
            _hn(NICHE_HN_TERMS, client),
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


async def harvest_for_channel(
    sources: list[str],
    niche: str,
    audience: str,
    count: int = 3,
    channel_name: str | None = None,
    skip_seen: bool = True,
) -> list[str]:
    """Harvest topics for a channel using its configured sources.

    Source string formats:
      reddit:<subreddit>
      hn:<search term>
      wiki:random
      wiki:featured
      wiki:category:<Category Name>
    """
    seen = load_seen(channel_name) if skip_seen else set()

    reddit_subs = [s[len("reddit:"):] for s in sources if s.startswith("reddit:")]
    hn_terms    = [s[len("hn:"):] for s in sources if s.startswith("hn:")]
    wiki_cats   = [s[len("wiki:category:"):] for s in sources if s.startswith("wiki:category:")]
    want_random  = any(s == "wiki:random" for s in sources)
    want_featured = any(s == "wiki:featured" for s in sources)

    async with httpx.AsyncClient() as client:
        tasks = []
        if reddit_subs:
            tasks += [_reddit(sub, client) for sub in reddit_subs]
        if hn_terms:
            tasks.append(_hn(hn_terms, client))
        if want_random:
            tasks.append(_wikipedia_random(client))
        if want_featured:
            tasks.append(_wikipedia_featured(client))
        for cat in wiki_cats:
            tasks.append(_wikipedia_category(cat, client))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    posts: list[dict] = []
    for r in results:
        if isinstance(r, list):
            posts.extend(r)

    posts = [p for p in posts if p["title"].lower() not in seen]
    posts.sort(key=lambda p: -p["score"])

    if not posts:
        return []

    topics = await _reframe(posts, count, niche=niche, audience=audience)
    return topics[:count]
