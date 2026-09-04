import json
import logging
import time

from google.api_core.exceptions import NotFound

from config import config
import gcs_utils

logger = logging.getLogger("video_pipeline")


def _blob():
    bucket = gcs_utils.get_client().bucket(config.gcs_bucket)
    return bucket.blob(f"{config.gcs_analytics_prefix}/published_videos.json")


def _load_all() -> list[dict]:
    try:
        raw = _blob().download_as_text()
        return json.loads(raw)
    except NotFound:
        return []
    except Exception as e:
        logger.warning(f"Failed to load published videos log (starting fresh): {e}")
        return []


def _save_all(records: list[dict]):
    _blob().upload_from_string(json.dumps(records, indent=2), content_type="application/json")


def record_published_video(run_id, track, topic, title, youtube_video_id, published_at=None):
    records = _load_all()
    records.append({
        "run_id": run_id, "track": track, "topic": topic, "title": title,
        "youtube_video_id": youtube_video_id,
        "published_at": published_at or time.time(), "analyzed": False,
    })
    _save_all(records)
    logger.info(f"Recorded published video for run {run_id} (YouTube: {youtube_video_id})")


def get_unanalyzed_eligible_records(min_age_days: float) -> list[dict]:
    cutoff = time.time() - (min_age_days * 86400)
    return [r for r in _load_all() if not r.get("analyzed") and r["published_at"] <= cutoff]


def mark_analyzed(run_ids: set):
    records = _load_all()
    for r in records:
        if r["run_id"] in run_ids:
            r["analyzed"] = True
    _save_all(records)
