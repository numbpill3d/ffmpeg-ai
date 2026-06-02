"""YouTube Data API v3 — OAuth2 setup and video upload."""
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
       ~/.config/ffmpeg-ai/client_secrets.json
  4. Run:  ffmpeg-ai youtube-setup
"""


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
    sp = secrets_path or SECRETS_PATH
    tp = token_path or TOKEN_PATH
    return tp.exists() or sp.exists()


def setup_oauth(
    secrets_path: Optional[Path] = None,
    token_path: Optional[Path] = None,
) -> None:
    """Run interactive OAuth flow and save credentials. Call once."""
    sp = secrets_path or SECRETS_PATH
    tp = token_path or TOKEN_PATH
    Credentials, InstalledAppFlow, Request, _, _ = _import_google()
    if not sp.exists():
        raise RuntimeError(_SETUP_HINT)
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
                raise RuntimeError(_SETUP_HINT)
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
) -> str:
    """Upload video to YouTube. Returns watch URL. category 28 = Science & Technology."""
    _, _, _, build, MediaFileUpload = _import_google()
    creds   = _get_credentials(secrets_path=secrets_path, token_path=token_path)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        [t.lstrip("#") for t in tags][:500],
            "categoryId":  category_id,
        },
        "status": {
            "privacyStatus":          privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media   = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]

    if thumbnail_path and thumbnail_path.exists():
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
        ).execute()

    return f"https://youtu.be/{video_id}"
