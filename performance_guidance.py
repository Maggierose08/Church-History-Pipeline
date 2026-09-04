import json
import logging
import time

from google.api_core.exceptions import NotFound

from config import config
import gcs_utils

logger = logging.getLogger("video_pipeline")


def _blob():
    bucket = gcs_utils.get_client().bucket(config.gcs_bucket)
    return bucket.blob(f"{config.gcs_analytics_prefix}/performance_guidance.json")


def save_guidance(guidance_text: str, based_on_n_videos: int):
    data = {"guidance": guidance_text, "based_on_n_videos": based_on_n_videos, "updated_at": time.time()}
    _blob().upload_from_string(json.dumps(data, indent=2), content_type="application/json")
    logger.info(f"Saved updated performance guidance (based on {based_on_n_videos} videos)")


def load_guidance() -> str | None:
    try:
        raw = _blob().download_as_text()
        return json.loads(raw).get("guidance")
    except NotFound:
        return None
    except Exception as e:
        logger.warning(f"Failed to load performance guidance (proceeding without it): {e}")
        return None
