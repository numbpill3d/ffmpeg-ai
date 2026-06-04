"""Channel profile loading, saving, validation, and preset definitions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CHANNELS_DIR = Path.home() / ".config" / "ffmpeg-ai" / "channels"


@dataclass
class ChannelConfig:
    name: str
    display_name: str
    niche: str
    audience: str
    style: str
    voice: str
    sources: list[str]
    shorts_per_day: int = 1
    landscape_per_week: int = 1
    shorts_duration: int = 45
    landscape_duration: int = 300
    upload: bool = False
    privacy: str = "public"
    publish_hour: int = 12        # hour (0–23 local) to schedule uploads
    category_id: str = "28"
    brand_name: str = ""          # shown on thumbnail bottom; defaults to display_name
    music_style: Optional[str] = None   # ambient/upbeat/dramatic/cinematic/None
    accent_color: str = "#00d4ff"       # hex color for thumbnail accent bar
    youtube_secrets: Optional[str] = None
    youtube_token: Optional[str] = None

    # ── Persistence ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, name: str) -> "ChannelConfig":
        path = CHANNELS_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"channel '{name}' not found — run: ffmpeg-ai channel init-presets"
            )
        data = json.loads(path.read_text())
        # Forward-compat: ignore unknown keys so old configs survive new fields
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
        path = CHANNELS_DIR / f"{self.name}.json"
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def list_all(cls) -> list[str]:
        if not CHANNELS_DIR.exists():
            return []
        return sorted(p.stem for p in CHANNELS_DIR.glob("*.json"))

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return a list of error strings; empty means valid."""
        from ..ai.openrouter import STYLE_PRESETS
        from ..ai.tts import VOICES
        errors: list[str] = []
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            errors.append("name must be alphanumeric (hyphens/underscores allowed)")
        if self.style and self.style not in STYLE_PRESETS:
            errors.append(f"unknown style '{self.style}' — choose from: {', '.join(STYLE_PRESETS)}")
        if self.voice and self.voice not in VOICES:
            errors.append(f"unknown voice '{self.voice}' — choose from: {', '.join(VOICES)}")
        if not 0 <= self.publish_hour <= 23:
            errors.append(f"publish_hour must be 0–23, got {self.publish_hour}")
        if self.privacy not in ("public", "unlisted", "private"):
            errors.append(f"privacy must be public/unlisted/private, got '{self.privacy}'")
        if self.shorts_duration < 10 or self.shorts_duration > 58:
            errors.append(f"shorts_duration must be 10–58s, got {self.shorts_duration}")
        if self.landscape_duration < 60 or self.landscape_duration > 600:
            errors.append(f"landscape_duration must be 60–600s, got {self.landscape_duration}")
        if not self.sources:
            errors.append("at least one source is required")
        return errors

    # ── Credential paths ──────────────────────────────────────────────────────

    @property
    def secrets_path(self) -> Path:
        if self.youtube_secrets:
            return Path(self.youtube_secrets).expanduser()
        return CHANNELS_DIR / self.name / "client_secrets.json"

    @property
    def token_path(self) -> Path:
        if self.youtube_token:
            return Path(self.youtube_token).expanduser()
        return CHANNELS_DIR / self.name / "token.json"

    @property
    def run_log_path(self) -> Path:
        return CHANNELS_DIR / self.name / "run_history.jsonl"

    @property
    def is_youtube_configured(self) -> bool:
        return self.token_path.exists()


# ── Built-in presets ──────────────────────────────────────────────────────────

PRESETS: list[dict] = [
    # ── The three primary channels ────────────────────────────────────────────
    {
        "name": "disclosure",
        "display_name": "The Disclosure Files",
        "niche": (
            "UAP and UFO phenomena, government disclosure, non-human intelligence (NHI), "
            "transdimensional entities, classified programs, whistleblower testimonies, "
            "ancient astronaut theory, Skinwalker Ranch, AARO reports, interdimensional beings, "
            "reptilian hypothesis, deep state secrecy, declassified documents"
        ),
        "audience": (
            "UFO enthusiasts, disclosure advocates, conspiracy researchers, "
            "paranormal investigators, open-minded skeptics"
        ),
        "style": "dramatic",
        "voice": "en-documentary",
        "sources": [
            "reddit:UFOs",
            "reddit:NHI",
            "reddit:HighStrangeness",
            "reddit:conspiracy",
            "reddit:aliens",
            "reddit:UFOB",
            "reddit:Paranormal",
            "wiki:category:Unidentified flying objects",
            "wiki:category:Extraterrestrial life",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 55,
        "landscape_duration": 480,
        "upload": False,
        "privacy": "public",
        "publish_hour": 20,
        "category_id": "27",
        "brand_name": "Disclosure Files",
        "music_style": "dramatic",
        "accent_color": "#8b00ff",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "zerocell",
        "display_name": "Zero Cell",
        "niche": (
            "hacking, cybersecurity, reverse engineering, malware analysis, "
            "exploit development, CVEs, red teaming, CTF write-ups, "
            "offensive security, bug bounty, APT groups, OSINT, "
            "binary exploitation, social engineering, threat intelligence"
        ),
        "audience": (
            "security researchers, ethical hackers, CTF players, "
            "malware analysts, penetration testers, infosec professionals"
        ),
        "style": "educational",
        "voice": "en-male",
        "sources": [
            "reddit:netsec",
            "reddit:ReverseEngineering",
            "reddit:hacking",
            "reddit:cybersecurity",
            "reddit:Malware",
            "reddit:bugbounty",
            "hn:security vulnerability",
            "hn:reverse engineering",
            "hn:exploit",
            "rss:https://krebsonsecurity.com/feed/",
            "rss:https://www.schneier.com/blog/atom.xml",
            "rss:https://isc.sans.edu/rssfeed_full.xml",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 50,
        "landscape_duration": 420,
        "upload": False,
        "privacy": "public",
        "publish_hour": 13,
        "category_id": "28",
        "brand_name": "Zero Cell",
        "music_style": "ambient",
        "accent_color": "#00ff41",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "labdrop",
        "display_name": "Lab Drop",
        "niche": (
            "brand new peer-reviewed scientific discoveries, freshly published studies, "
            "breakthroughs in biology, physics, medicine, neuroscience, materials science, "
            "archaeology, climate science, and space — explained in plain everyday language "
            "with zero jargon; always the most recently published research"
        ),
        "audience": (
            "curious non-scientists, lifelong learners, students, "
            "people who love science but have no formal background"
        ),
        "style": "curiosity",
        "voice": "en-female",
        "sources": [
            "reddit:science",
            "reddit:EverythingScience",
            "reddit:biology",
            "reddit:physics",
            "reddit:medicine",
            "reddit:neuroscience",
            "reddit:space",
            "hn:new study",
            "hn:research published",
            "rss:https://www.sciencedaily.com/rss/all.xml",
            "rss:https://www.newscientist.com/feed/home/",
            "rss:https://phys.org/rss-feed/",
            "rss:https://www.nih.gov/rss/news.xml",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 360,
        "upload": False,
        "privacy": "public",
        "publish_hour": 11,
        "category_id": "28",
        "brand_name": "Lab Drop",
        "music_style": "upbeat",
        "accent_color": "#00cfff",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    # ── Legacy presets (kept, not default-run) ────────────────────────────────
    {
        "name": "tech",
        "display_name": "Tech Facts Daily",
        "niche": "technology, AI, programming, developer tools, software engineering",
        "audience": "software developers, makers, self-taught coders, tech enthusiasts",
        "style": "educational",
        "voice": "en-female",
        "sources": [
            "reddit:technology",
            "reddit:programming",
            "reddit:MachineLearning",
            "reddit:artificial",
            "hn:AI tools",
            "hn:programming",
            "rss:https://feeds.arstechnica.com/arstechnica/index",
            "rss:https://lobste.rs/rss",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 300,
        "upload": False,
        "privacy": "public",
        "publish_hour": 12,
        "category_id": "28",
        "brand_name": "Tech Facts",
        "music_style": "educational",
        "accent_color": "#00d4ff",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "history",
        "display_name": "History Uncovered",
        "niche": "world history, ancient civilizations, historical events, forgotten figures",
        "audience": "history enthusiasts, curious learners, students",
        "style": "documentary",
        "voice": "en-documentary",
        "sources": [
            "wiki:random",
            "wiki:featured",
            "wiki:onthisday",
            "wiki:category:Ancient history",
            "wiki:category:Wars involving the United States",
            "reddit:history",
            "reddit:AskHistorians",
            "rss:https://www.smithsonianmag.com/rss/latest_articles/",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 50,
        "landscape_duration": 480,
        "upload": False,
        "privacy": "public",
        "publish_hour": 10,
        "category_id": "27",
        "brand_name": "History Uncovered",
        "music_style": "documentary",
        "accent_color": "#c8a96e",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "science",
        "display_name": "Mind Blown Science",
        "niche": "science, space, physics, biology, nature, discoveries, research",
        "audience": "science fans, curious people, students, nature lovers",
        "style": "dramatic",
        "voice": "en-male",
        "sources": [
            "wiki:random",
            "wiki:featured",
            "wiki:category:Physics",
            "wiki:category:Biology",
            "wiki:category:Astronomy",
            "reddit:science",
            "reddit:space",
            "rss:https://www.sciencedaily.com/rss/all.xml",
            "rss:https://www.nasa.gov/rss/dyn/breaking_news.rss",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 360,
        "upload": False,
        "privacy": "public",
        "publish_hour": 14,
        "category_id": "28",
        "brand_name": "Mind Blown",
        "music_style": "cinematic",
        "accent_color": "#7b68ee",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "mythology",
        "display_name": "Myths and Legends",
        "niche": "mythology, folklore, ancient gods, legends, cultural stories worldwide",
        "audience": "mythology fans, fantasy readers, history buffs, storytelling enthusiasts",
        "style": "documentary",
        "voice": "en-storyteller",
        "sources": [
            "wiki:category:Greek mythology",
            "wiki:category:Norse mythology",
            "wiki:category:Egyptian mythology",
            "wiki:random",
            "reddit:mythology",
            "reddit:folklore",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 50,
        "landscape_duration": 420,
        "upload": False,
        "privacy": "public",
        "publish_hour": 11,
        "category_id": "27",
        "brand_name": "Myths & Legends",
        "music_style": "cinematic",
        "accent_color": "#ff6b35",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "mindset",
        "display_name": "Stoic Mind",
        "niche": "stoicism, philosophy, mindset, self-improvement, ancient wisdom",
        "audience": "self-improvement seekers, philosophy students, professionals",
        "style": "educational",
        "voice": "en-documentary",
        "sources": [
            "wiki:category:Stoicism",
            "wiki:category:Ancient Greek philosophy",
            "wiki:random",
            "reddit:Stoicism",
            "reddit:philosophy",
            "reddit:selfimprovement",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 300,
        "upload": False,
        "privacy": "public",
        "publish_hour": 7,
        "category_id": "27",
        "brand_name": "Stoic Mind",
        "music_style": "ambient",
        "accent_color": "#52b788",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "finance",
        "display_name": "Money Decoded",
        "niche": "personal finance, investing, wealth building, economics, money psychology",
        "audience": "young adults, aspiring investors, professionals managing money",
        "style": "educational",
        "voice": "en-energetic",
        "sources": [
            "reddit:personalfinance",
            "reddit:investing",
            "reddit:financialindependence",
            "hn:finance",
            "hn:investing",
            "rss:https://feeds.feedburner.com/PennyHoarder",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 300,
        "upload": False,
        "privacy": "public",
        "publish_hour": 9,
        "category_id": "27",
        "brand_name": "Money Decoded",
        "music_style": "upbeat",
        "accent_color": "#00c853",
        "youtube_secrets": None,
        "youtube_token": None,
    },
]
