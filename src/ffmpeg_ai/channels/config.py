"""Channel profile loading, saving, and preset definitions."""
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
    category_id: str = "28"
    youtube_secrets: Optional[str] = None
    youtube_token: Optional[str] = None

    @classmethod
    def load(cls, name: str) -> "ChannelConfig":
        path = CHANNELS_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"channel '{name}' not found — run: ffmpeg-ai channel init-presets"
            )
        data = json.loads(path.read_text())
        return cls(**data)

    def save(self) -> None:
        CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
        path = CHANNELS_DIR / f"{self.name}.json"
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def list_all(cls) -> list[str]:
        if not CHANNELS_DIR.exists():
            return []
        return sorted(p.stem for p in CHANNELS_DIR.glob("*.json"))

    @property
    def secrets_path(self) -> Optional[Path]:
        if self.youtube_secrets:
            return Path(self.youtube_secrets).expanduser()
        return CHANNELS_DIR / self.name / "client_secrets.json"

    @property
    def token_path(self) -> Optional[Path]:
        if self.youtube_token:
            return Path(self.youtube_token).expanduser()
        return CHANNELS_DIR / self.name / "token.json"


# Built-in channel presets — install via: ffmpeg-ai channel init-presets
PRESETS: list[dict] = [
    {
        "name": "tech",
        "display_name": "Tech Facts Daily",
        "niche": "technology, AI, programming, software engineering, developer tools",
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
            "hn:developer tools",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 300,
        "upload": False,
        "privacy": "public",
        "category_id": "28",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "history",
        "display_name": "History Uncovered",
        "niche": "world history, ancient civilizations, historical events, forgotten figures",
        "audience": "history enthusiasts, students, curious learners",
        "style": "documentary",
        "voice": "en-male",
        "sources": [
            "wiki:random",
            "wiki:featured",
            "wiki:category:Ancient history",
            "wiki:category:Wars",
            "reddit:history",
            "reddit:AskHistorians",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 50,
        "landscape_duration": 480,
        "upload": False,
        "privacy": "public",
        "category_id": "27",
        "youtube_secrets": None,
        "youtube_token": None,
    },
    {
        "name": "science",
        "display_name": "Mind Blown Science",
        "niche": "science, space, physics, biology, nature, discoveries",
        "audience": "science fans, curious people, students",
        "style": "dramatic",
        "voice": "en-female",
        "sources": [
            "wiki:random",
            "wiki:featured",
            "wiki:category:Physics",
            "wiki:category:Biology",
            "reddit:science",
            "reddit:space",
            "reddit:biology",
            "hn:space",
            "hn:biology",
        ],
        "shorts_per_day": 1,
        "landscape_per_week": 1,
        "shorts_duration": 45,
        "landscape_duration": 360,
        "upload": False,
        "privacy": "public",
        "category_id": "28",
        "youtube_secrets": None,
        "youtube_token": None,
    },
]
