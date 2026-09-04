import json
import logging
import time
import uuid

from google.api_core.exceptions import NotFound

from config import config
import gcs_utils

logger = logging.getLogger("video_pipeline")


def _blob():
    bucket = gcs_utils.get_client().bucket(config.gcs_bucket)
    return bucket.blob(f"{config.gcs_analytics_prefix}/pending_compilations.json")


def _load_all() -> list[dict]:
    try:
        raw = _blob().download_as_text()
        return json.loads(raw)
    except NotFound:
        return []
    except Exception as e:
        logger.warning(f"Failed to load pending compilations queue (starting fresh): {e}")
        return []


def _save_all(entries: list[dict]):
    _blob().upload_from_string(json.dumps(entries, indent=2), content_type="application/json")


def add_pending_compilation(full_script_data: dict, scheduled_date: str, origin_track: int) -> str:
    """
    Queues a finished story's full-compilation for posting once `scheduled_date`
    arrives. Returns the compilation's ID. Not tied to any specific track going
    forward - any track's daily slot can end up posting it once it's due, since the
    originating track is free to start a new story immediately.
    """
    entries = _load_all()
    compilation_id = uuid.uuid4().hex[:10]
    entries.append({
        "compilation_id": compilation_id,
        "origin_track": origin_track,
        "full_script_data": full_script_data,
        "scheduled_date": scheduled_date,
        "posted": False,
        "queued_at": time.time(),
    })
    _save_all(entries)
    logger.info(f"Queued compilation {compilation_id} (from track {origin_track}) for {scheduled_date}")
    return compilation_id


def get_due_compilation(today_str: str) -> dict | None:
    """
    Returns the oldest-scheduled unposted compilation that's due (scheduled_date <=
    today), or None if nothing is due yet. FIFO order, so if the queue ever backs up
    (multiple due on the same day), the earliest-queued one goes out first and the
    rest wait for subsequent days - only one compilation posts per day, since it
    consumes a full daily slot like anything else.
    """
    entries = _load_all()
    due = [e for e in entries if not e["posted"] and e["scheduled_date"] <= today_str]
    if not due:
        return None
    due.sort(key=lambda e: e["scheduled_date"])
    return due[0]


def mark_compilation_posted(compilation_id: str):
    entries = _load_all()
    for e in entries:
        if e["compilation_id"] == compilation_id:
            e["posted"] = True
    _save_all(entries)
    logger.info(f"Marked compilation {compilation_id} as posted")
