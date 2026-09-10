import logging

from retry_utils import retry_with_backoff

logger = logging.getLogger("video_pipeline")


@retry_with_backoff(max_retries=3, base_delay=2.0)
def get_or_create_playlist(youtube, title: str, description: str = "", privacy_status: str = "public") -> str:
    """
    Looks for an existing playlist on the authenticated channel with this EXACT
    title first (avoids creating duplicate playlists if a run is retried, or if
    this function is accidentally called twice for the same story) - only creates
    a new one if no match is found. Returns the playlist ID either way.
    """
    existing = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
    for item in existing.get("items", []):
        if item["snippet"]["title"] == title:
            logger.info(f"Reusing existing playlist {item['id']!r} for {title!r}")
            return item["id"]

    # Handle pagination in case the channel has more than 50 playlists already.
    next_page = existing.get("nextPageToken")
    while next_page:
        existing = youtube.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=next_page).execute()
        for item in existing.get("items", []):
            if item["snippet"]["title"] == title:
                logger.info(f"Reusing existing playlist {item['id']!r} for {title!r}")
                return item["id"]
        next_page = existing.get("nextPageToken")

    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": privacy_status},
    }
    response = youtube.playlists().insert(part="snippet,status", body=body).execute()
    playlist_id = response["id"]
    logger.info(f"Created new playlist {playlist_id!r} titled {title!r}")
    return playlist_id


@retry_with_backoff(max_retries=3, base_delay=2.0)
def add_video_to_playlist(youtube, playlist_id: str, video_id: str):
    """Adds one video to an existing playlist, at the end (default position)."""
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    youtube.playlistItems().insert(part="snippet", body=body).execute()
    logger.info(f"Added video {video_id!r} to playlist {playlist_id!r}")


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"
