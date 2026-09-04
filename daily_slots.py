import json, logging
from google.api_core.exceptions import NotFound
from config import config
import gcs_utils
logger = logging.getLogger("video_pipeline")
def _blob():
    bucket = gcs_utils.get_client().bucket(config.gcs_bucket)
    return bucket.blob(config.gcs_daily_slot_path)
def _load(today_str):
    try:
        raw = _blob().download_as_text()
        state = json.loads(raw)
    except NotFound:
        state = None
    except Exception as e:
        logger.warning(f"Failed to load daily slot counter: {e}")
        state = None
    if state is None or state.get("date") != today_str:
        state = {"date": today_str, "used_slots": []}
    return state
def _save(state):
    _blob().upload_from_string(json.dumps(state, indent=2), content_type="application/json")
def claim_next_slot(today_str):
    state = _load(today_str)
    available = [s for s in range(config.videos_per_day) if s not in state["used_slots"]]
    if not available:
        return None
    slot = min(available)
    state["used_slots"].append(slot)
    _save(state)
    logger.info(f"Claimed slot {slot} for {today_str} (used so far today: {sorted(state['used_slots'])})")
    return slot
