"""YouTube Data API v3 — OAuth2 setup, upload, and scheduled publishing."""
from __future__ import annotations

import datetime
import time
from pathlib import Path
from typing import Optional

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CONFIG_DIR   = Path.home() / ".config" / "ffmpeg-ai"
TOKEN_PATH   = CONFIG_DIR / "youtube_token.json"
SECRETS_PATH = CONFIG_DIR / "client_secrets.json"

_SETUP_HINT = """
YouTube client secrets not found.

Setup (one time):
  1. console.cloud.google.com → APIs & Services → Enable "YouTube Data API v3"
  2. Credentials → Create → OAuth 2.0 Client ID → Desktop app
  3. Download JSON → save to:
       {secrets_path}
  4. Run:  ffmpeg-ai youtube-setup   (or: ffmpeg-ai channel setup-yt <name>)
"""

# Quota cost per upload is 1600 units; daily free quota is 10,000 units (~6 uploads/day).
# Resumable uploads occasionally fail transiently — retry up to this many times.
_UPLOAD_RETRIES = 3
_RETRY_BACKOFF  = (5, 15, 45)   # seconds between attempts


def _import_google():
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        return Credentials, InstalledAppFlow, Request, build, MediaFileUpload
    except ImportError:
        raise RuntimeError(
            "Google API packages not installed.\n"
            "Run:  pip install google-auth google-auth-oauthlib google-api-python-client"
        )


def is_configured(
    secrets_path: Optional[Path] = None,
    token_path: Optional[Path] = None,
) -> bool:
    """True only if a valid token exists (secrets alone is not enough)."""
    tp = token_path or TOKEN_PATH
    return tp.exists()


def setup_oauth(
    secrets_path: Optional[Path] = None,
    token_path: Optional[Path] = None,
) -> None:
    """Run interactive OAuth2 flow and save credentials. Call once per channel."""
    sp = secrets_path or SECRETS_PATH
    tp = token_path or TOKEN_PATH
    Credentials, InstalledAppFlow, Request, _, _ = _import_google()
    if not sp.exists():
        raise RuntimeError(_SETUP_HINT.format(secrets_path=sp))
    flow = InstalledAppFlow.from_client_secrets_file(str(sp), SCOPES)
    creds = flow.run_local_server(port=0)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(creds.to_json())
    print(f"credentials saved → {tp}")


def _get_credentials(
    secrets_path: Optional[Path] = None,
    token_path: Optional[Path] = None,
):
    sp = secrets_path or SECRETS_PATH
    tp = token_path or TOKEN_PATH
    Credentials, InstalledAppFlow, Request, _, _ = _import_google()
    creds = None
    if tp.exists():
        creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tp.write_text(creds.to_json())
        else:
            if not sp.exists():
                raise RuntimeError(_SETUP_HINT.format(secrets_path=sp))
            flow = InstalledAppFlow.from_client_secrets_file(str(sp), SCOPES)
            creds = flow.run_local_server(port=0)
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(creds.to_json())
    return creds


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: Optional[Path] = None,
    privacy: str = "public",
    category_id: str = "28",
    secrets_path: Optional[Path] = None,
    token_path: Optional[Path] = None,
    publish_at: Optional[datetime.datetime] = None,
) -> str:
    """Upload a video to YouTube and return its watch URL.

    publish_at:  if set, video is uploaded as private and scheduled to go
                 public at this UTC datetime. Requires privacy="private".
    category_id: 27=Education, 28=Science & Technology
    """
    _, _, _, build, MediaFileUpload = _import_google()
    creds   = _get_credentials(secrets_path=secrets_path, token_path=token_path)
    youtube = build("youtube", "v3", credentials=creds)

    effective_privacy = "private" if publish_at else privacy
    status_body: dict = {
        "privacyStatus":          effective_privacy,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        # YouTube requires RFC 3339 with explicit UTC suffix
        status_body["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        [t.lstrip("#") for t in tags][:500],
            "categoryId":  category_id,
        },
        "status": status_body,
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)

    last_err: Exception | None = None
    for attempt in range(_UPLOAD_RETRIES):
        try:
            request  = youtube.videos().insert(
                part=",".join(body.keys()), body=body, media_body=media
            )
            response = None
            while response is None:
                _, response = request.next_chunk()
            video_id = response["id"]
            break
        except Exception as e:
            last_err = e
            if attempt < _UPLOAD_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF[attempt])
            else:
                raise RuntimeError(
                    f"upload failed after {_UPLOAD_RETRIES} attempts: {last_err}"
                ) from last_err

    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
            ).execute()
        except Exception:
            pass  # thumbnail failure is non-fatal

    return f"https://youtu.be/{video_id}"


def next_publish_time(publish_hour: int) -> datetime.datetime:
    """Return the next UTC datetime for publish_hour (local time → UTC)."""
    now_local = datetime.datetime.now()
    target = now_local.replace(hour=publish_hour, minute=0, second=0, microsecond=0)
    if target <= now_local:
        target += datetime.timedelta(days=1)
    # Convert local → UTC (best-effort without tz database)
    utc_offset = datetime.datetime.utcnow() - now_local
    return target + utc_offset
