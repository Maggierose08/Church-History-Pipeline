import json
import logging

from google.api_core.exceptions import NotFound

from config import config
import gcs_utils

logger = logging.getLogger("video_pipeline")

GCS_TOPIC_HISTORY_PATH = f"{config.gcs_analytics_prefix}/covered_topics.json"


def _blob():
    bucket = gcs_utils.get_client().bucket(config.gcs_bucket)
    return bucket.blob(GCS_TOPIC_HISTORY_PATH)


def load_covered_topics() -> list[dict]:
    """Returns [{"topic": str, "covered_at": float}, ...] - every specific event/story already told."""
    try:
        raw = _blob().download_as_text()
        return json.loads(raw)
    except NotFound:
        return []
    except Exception as e:
        logger.warning(f"Failed to load topic history (proceeding as if empty): {e}")
        return []


def record_covered_topic(topic: str):
    import time
    history = load_covered_topics()
    history.append({"topic": topic, "covered_at": time.time()})
    _blob().upload_from_string(json.dumps(history, indent=2), content_type="application/json")
    logger.info(f"Recorded covered topic: {topic!r} ({len(history)} total in history)")


def get_covered_topic_titles(limit: int = 200) -> list[str]:
    """
    Returns just the topic strings, most recent first, capped at `limit` - used to
    build the "don't repeat these" list passed to the topic-selection prompt. Capped
    so the prompt doesn't grow unbounded as history accumulates over months/years.
    """
    history = load_covered_topics()
    history.sort(key=lambda r: r["covered_at"], reverse=True)
    return [r["topic"] for r in history[:limit]]
