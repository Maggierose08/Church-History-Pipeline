import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import config
from retry_utils import retry_with_backoff
import youtube_playlists

logger = logging.getLogger("video_pipeline")

YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube"]


def _get_credentials() -> Credentials:
    creds = Credentials(
        token=None, refresh_token=config.youtube_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.youtube_client_id, client_secret=config.youtube_client_secret,
        scopes=YOUTUBE_UPLOAD_SCOPE,
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def _build_title(title: str) -> str:
    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    return title[:100]


@retry_with_backoff(max_retries=config.max_retries, base_delay=config.retry_base_delay)
def _upload(youtube, video_path, thumbnail_path, title, description, publish_at=None) -> str:
    status = {"selfDeclaredMadeForKids": False}
    if publish_at is not None:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
    else:
        status["privacyStatus"] = config.youtube_privacy_status
    body = {
        "snippet": {"title": _build_title(title), "description": f"{description}\n\n#Shorts #ChurchHistory", "categoryId": config.youtube_category_id},
        "status": status,
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response["id"]
    if publish_at is not None:
        logger.info(f"Uploaded to YouTube (scheduled for {status['publishAt']}): https://youtube.com/shorts/{video_id}")
    else:
        logger.info(f"Uploaded to YouTube: https://youtube.com/shorts/{video_id}")
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
        except HttpError as e:
            logger.warning(f"Video uploaded but setting custom thumbnail failed: {e}")
    return video_id


def publish_to_youtube(video_path, thumbnail_path, title, description, publish_at=None, playlist_title: str = None) -> dict:
    """
    `playlist_title`, if given, gets-or-creates a playlist with that exact title
    (reusing it across every segment of the same story), links to it in the
    video's own description (a real "related videos" mechanism within what the
    official API actually supports - end screens/cards are NOT exposed via the
    API at all, only through unofficial, unsupported workarounds this pipeline
    deliberately avoids), and adds the newly-uploaded video to it.
    """
    if not (config.youtube_client_id and config.youtube_client_secret and config.youtube_refresh_token):
        logger.info("YouTube credentials not configured - skipping YouTube upload")
        return {"skipped": True}

    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    playlist_id = None
    if playlist_title:
        try:
            playlist_id = youtube_playlists.get_or_create_playlist(youtube, playlist_title)
            description = f"{description}\n\nWatch the full story: {youtube_playlists.playlist_url(playlist_id)}"
        except Exception as e:
            logger.warning(f"Playlist setup failed (continuing without it): {e}")

    video_id = _upload(youtube, video_path, thumbnail_path, title, description, publish_at=publish_at)

    if playlist_id:
        try:
            youtube_playlists.add_video_to_playlist(youtube, playlist_id, video_id)
        except Exception as e:
            logger.warning(f"Adding video to playlist failed (video still published normally): {e}")

    result = {"skipped": False, "video_id": video_id, "url": f"https://youtube.com/shorts/{video_id}"}
    if playlist_id:
        result["playlist_id"] = playlist_id
        result["playlist_url"] = youtube_playlists.playlist_url(playlist_id)
    return result
