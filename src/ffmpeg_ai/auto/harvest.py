"""Topic harvesting from Reddit, HN, Wikipedia, and RSS feeds."""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from ..ai.openrouter import FREE_MODELS, get_client

# ── Legacy defaults (used by the original `auto` CLI command) ─────────────────

_LEGACY_SUBS = [
    "esp32", "embedded", "netsec", "linux", "LocalLLaMA", "cybersecurity", "Python",
]
_LEGACY_HN_TERMS = [
    "esp32", "embedded linux", "ai tools hacking", "python automation", "security",
]

_HEADERS = {"User-Agent": "ffmpeg-ai/1.0 topic-harvester (https://github.com/numbpill3d/ffmpeg-ai)"}


# ── Seen-topic deduplication ──────────────────────────────────────────────────

def _seen_log(channel: str | None = None) -> Path:
    base = Path.home() / ".config" / "ffmpeg-ai"
    if channel:
        return base / "channels" / channel / "seen_topics.txt"
    return base / "seen_topics.txt"


def load_seen(channel: str | None = None) -> set[str]:
    p = _seen_log(channel)
    if not p.exists():
        return set()
    return {ln.strip().lower() for ln in p.read_text().splitlines() if ln.strip()}


def save_seen(topics: list[str], channel_name: str | None = None) -> None:
    p = _seen_log(channel_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for t in topics:
            f.write(t.lower() + "\n")


# ── Source fetchers ───────────────────────────────────────────────────────────

async def _reddit(sub: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(
            f"https://www.reddit.com/r/{sub}/top.json",
            params={"limit": 15, "t": "week"},
            headers=_HEADERS,
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
    out: list[dict] = []
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
                    out.append({
                        "title": h["title"],
                        "score": h.get("points", 0),
                        "src": f"HN:{term}",
                    })
        except Exception:
            pass
    return out


async def _rss(url: str, label: str, client: httpx.AsyncClient, limit: int = 12) -> list[dict]:
    """Fetch any RSS 2.0 or Atom feed and return title entries."""
    try:
        r = await client.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        items: list[dict] = []
        # RSS 2.0
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            if title and len(title) > 8:
                items.append({"title": title, "score": 55, "src": label})
        # Atom
        if not items:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//a:entry", ns)[:limit]:
                title_el = entry.find("a:title", ns)
                title = (title_el.text or "").strip() if title_el is not None else ""
                if title and len(title) > 8:
                    items.append({"title": title, "score": 55, "src": label})
        return items
    except Exception:
        return []


async def _wikipedia_random(client: httpx.AsyncClient, count: int = 8) -> list[dict]:
    tasks = [
        client.get(
            "https://en.wikipedia.org/api/rest_v1/page/random/summary",
            headers=_HEADERS,
            timeout=12,
        )
        for _ in range(count)
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[dict] = []
    for r in responses:
        try:
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            data = r.json()
            # Skip disambiguation pages and stubs (< 200 chars extract)
            if data.get("type") != "standard":
                continue
            if len(data.get("extract", "")) < 200:
                continue
            results.append({"title": data["title"], "score": 80, "src": "wiki:random"})
        except Exception:
            pass
    return results


async def _wikipedia_featured(client: httpx.AsyncClient) -> list[dict]:
    today = datetime.date.today()
    try:
        r = await client.get(
            f"https://en.wikipedia.org/api/rest_v1/feed/featured/"
            f"{today.year}/{today.month:02d}/{today.day:02d}",
            headers=_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        results: list[dict] = []
        if "tfa" in data:
            results.append({
                "title": data["tfa"]["title"],
                "score": 130,
                "src": "wiki:featured",
            })
        for article in data.get("mostread", {}).get("articles", [])[:6]:
            title = article.get("normalizedtitle") or article.get("title", "")
            title = title.replace("_", " ")
            # Skip meta-articles
            if any(x in title for x in ("Main Page", "Special:", "Wikipedia:")):
                continue
            results.append({
                "title": title,
                "score": min(article.get("views", 50), 120),
                "src": "wiki:mostread",
            })
        return results
    except Exception:
        return []


async def _wikipedia_on_this_day(client: httpx.AsyncClient) -> list[dict]:
    """Return notable 'on this day in history' events."""
    today = datetime.date.today()
    try:
        r = await client.get(
            f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/"
            f"{today.month:02d}/{today.day:02d}",
            headers=_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            return []
        events = r.json().get("events", [])
        results: list[dict] = []
        for ev in sorted(events, key=lambda e: -len(e.get("pages", [])))[:8]:
            text = ev.get("text", "").strip()
            year = ev.get("year")
            if text and year:
                results.append({
                    "title": f"{year}: {text[:120]}",
                    "score": 90,
                    "src": "wiki:onthisday",
                })
        return results
    except Exception:
        return []


async def _wikipedia_category(category: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmlimit": 20,
                "cmtype": "page",
                "format": "json",
            },
            headers=_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            return []
        members = r.json().get("query", {}).get("categorymembers", [])
        return [
            {"title": m["title"], "score": 65, "src": f"wiki:cat:{category}"}
            for m in members
            if not any(x in m["title"] for x in ("Category:", "Template:", "Wikipedia:"))
        ]
    except Exception:
        return []


# ── LLM reframing ─────────────────────────────────────────────────────────────

async def _reframe(
    raw: list[dict],
    count: int,
    niche: str = "technology, ESP32, AI tools, Linux, security",
    audience: str = "developers and makers",
) -> list[str]:
    """Ask LLM to select and rewrite raw titles as compelling video topic strings."""
    if not raw:
        return []
    client = get_client()
    # Deduplicate by lowercased title before sending to LLM
    seen_titles: set[str] = set()
    unique: list[dict] = []
    for p in raw:
        key = p["title"].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(p)
    unique.sort(key=lambda p: -p["score"])
    listing = "\n".join(
        f"- [{p['src']} +{p['score']}] {p['title']}"
        for p in unique[:35]
    )
    resp = await client.chat.completions.create(
        model=FREE_MODELS[0],
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a YouTube strategist specialising in the {niche} niche. "
                    f"Target audience: {audience}. "
                    "Your job is to select topics that will drive views and retention, "
                    "then reframe them as irresistible video titles. "
                    "Output strict JSON only — no markdown, no prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Recent content from this niche:\n\n{listing}\n\n"
                    f"Select the {count} most compelling topics and rewrite each as a "
                    "punchy, curiosity-gap YouTube title (5–9 words, active voice, "
                    "present or imperative tense). Prefer topics with a clear how-to, "
                    "surprising-fact, or story angle. Avoid pure news headlines — "
                    "frame each as an evergreen video premise.\n\n"
                    f'Return JSON: {{"topics": ["title 1", "title 2", ...]}}'
                ),
            },
        ],
        max_tokens=512,
        temperature=0.75,
        timeout=35,
    )
    content = (resp.choices[0].message.content or "").strip()
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
    content = re.sub(r"\n?```$", "", content.strip())
    try:
        return json.loads(content).get("topics", [])[:count]
    except Exception:
        return []


# ── Source dispatcher ─────────────────────────────────────────────────────────

async def _fetch_sources(
    sources: list[str],
    client: httpx.AsyncClient,
    hn_terms: list[str],
) -> list[dict]:
    """Dispatch all source strings to their fetchers and gather results."""
    reddit_subs = [s[len("reddit:"):] for s in sources if s.startswith("reddit:")]
    rss_sources = [s[len("rss:"):] for s in sources if s.startswith("rss:")]
    wiki_cats = [s[len("wiki:category:"):] for s in sources if s.startswith("wiki:category:")]
    want_random   = "wiki:random" in sources
    want_featured = "wiki:featured" in sources
    want_otd      = "wiki:onthisday" in sources

    coros = []
    if reddit_subs:
        coros += [_reddit(sub, client) for sub in reddit_subs]
    if hn_terms:
        coros.append(_hn(hn_terms, client))
    for url in rss_sources:
        label = "rss:" + url.split("/")[2]  # use domain as label
        coros.append(_rss(url, label, client))
    if want_random:
        coros.append(_wikipedia_random(client))
    if want_featured:
        coros.append(_wikipedia_featured(client))
    if want_otd:
        coros.append(_wikipedia_on_this_day(client))
    for cat in wiki_cats:
        coros.append(_wikipedia_category(cat, client))

    results = await asyncio.gather(*coros, return_exceptions=True)
    posts: list[dict] = []
    for r in results:
        if isinstance(r, list):
            posts.extend(r)
    return posts


# ── Public API ────────────────────────────────────────────────────────────────

async def harvest(count: int = 3, skip_seen: bool = True) -> list[str]:
    """Legacy single-channel harvest for the `auto` CLI command."""
    seen = load_seen() if skip_seen else set()
    async with httpx.AsyncClient() as client:
        posts = await _fetch_sources(
            sources=[f"reddit:{s}" for s in _LEGACY_SUBS],
            client=client,
            hn_terms=_LEGACY_HN_TERMS,
        )
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
    """Harvest topics for a channel using its configured source list.

    Source string formats:
      reddit:<subreddit>
      hn:<search term>
      rss:<full url>
      wiki:random
      wiki:featured
      wiki:onthisday
      wiki:category:<Category Name>
    """
    seen = load_seen(channel_name) if skip_seen else set()
    hn_terms = [s[len("hn:"):] for s in sources if s.startswith("hn:")]

    async with httpx.AsyncClient() as client:
        posts = await _fetch_sources(sources, client, hn_terms)

    posts = [p for p in posts if p["title"].lower() not in seen]
    posts.sort(key=lambda p: -p["score"])
    if not posts:
        return []
    topics = await _reframe(posts, count, niche=niche, audience=audience)
    return topics[:count]
