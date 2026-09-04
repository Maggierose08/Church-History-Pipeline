import logging

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import config
from retry_utils import retry_with_backoff

logger = logging.getLogger("video_pipeline")

YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube"]


def _get_client():
    creds = Credentials(
        token=None, refresh_token=config.youtube_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.youtube_client_id, client_secret=config.youtube_client_secret,
        scopes=YOUTUBE_SCOPE,
    )
    creds.refresh(google.auth.transport.requests.Request())
    return build("youtube", "v3", credentials=creds)


@retry_with_backoff(max_retries=config.max_retries, base_delay=config.retry_base_delay)
def get_video_stats(video_id: str) -> dict | None:
    youtube = _get_client()
    response = youtube.videos().list(part="statistics", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        logger.warning(f"YouTube video {video_id} not found - may still be scheduled/private, or removed")
        return None
    stats = items[0]["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
    }
