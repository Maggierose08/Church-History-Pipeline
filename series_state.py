import json
import logging
import time

from google.api_core.exceptions import NotFound

from config import config
import gcs_utils
import pending_compilations
import topic_history

logger = logging.getLogger("video_pipeline")

COMPILATION_DELAY_DAYS = 3


def _blob(track: int):
    bucket = gcs_utils.get_client().bucket(config.gcs_bucket)
    return bucket.blob(f"{config.gcs_series_state_path_template.format(track=track)}")


def load_series_state(track: int) -> dict | None:
    try:
        raw = _blob(track).download_as_text()
    except NotFound:
        return None
    except Exception as e:
        logger.warning(f"Failed to load series state for track {track} (starting a fresh series instead): {e}")
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Series state for track {track} is corrupted (starting a fresh series instead): {e}")
        return None


def save_series_state(state: dict, track: int):
    _blob(track).upload_from_string(json.dumps(state, indent=2), content_type="application/json")


def clear_series_state(track: int):
    try:
        _blob(track).delete()
    except NotFound:
        pass


def start_new_series(story_data: dict, track: int, source_file: str | None = None) -> dict:
    """
    story_data: the full structured output from church_script.generate_church_history_story()
    (topic, segments list, full_compilation). Records the topic as covered IMMEDIATELY
    (not waiting for the series to finish), so it can never be re-selected while its
    own series is still mid-release across multiple days. `source_file` is the local
    fallback pool filename if that tier was used (None if AI-generated) - lets sibling
    tracks avoid picking the same local story on the same day. Returns segment 1.
    """
    segments = story_data["segments"]
    state = {
        "series_id": f"series-track{track}-{int(time.time())}",
        "topic": story_data["topic"],
        "segments": segments,
        "full_compilation": story_data["full_compilation"],
        "next_segment_index": 2,
        "total_segments": len(segments),
        "created_at": time.time(),
        "source_file": source_file,
    }
    save_series_state(state, track)
    topic_history.record_covered_topic(story_data["topic"])
    logger.info(
        f"Started new series {state['series_id']} on track {track}: "
        f"{state['total_segments']} segments, topic={story_data['topic']!r}"
    )
    return segments[0]


def advance_series(track: int, today_str: str) -> dict | None:
    """
    Releases the next segment for this track's in-progress series, or None if no
    series is in progress (caller should start a new one). If this was the LAST
    segment, queues the full compilation for posting COMPILATION_DELAY_DAYS later
    and clears this track's state, so it's immediately free to start a new story -
    the compilation itself is handled independently via pending_compilations.py,
    decoupled from this track going forward.
    """
    state = load_series_state(track)
    if state is None:
        return None

    next_index = state["next_segment_index"]
    segment = state["segments"][next_index - 1]
    logger.info(
        f"Continuing series {state['series_id']} on track {track}: "
        f"releasing segment {next_index}/{state['total_segments']}"
    )

    if next_index >= state["total_segments"]:
        scheduled_date = _add_days(today_str, COMPILATION_DELAY_DAYS)
        pending_compilations.add_pending_compilation(
            full_script_data={
                "title": state["full_compilation"]["title"],
                "social_title": state["full_compilation"]["social_title"],
                "caption": state["full_compilation"]["caption"],
                "segments": state["segments"],  # full narration/scenes = all segments concatenated
                "topic": state["topic"],
            },
            scheduled_date=scheduled_date,
            origin_track=track,
        )
        clear_series_state(track)
        logger.info(
            f"Series {state['series_id']} finished all {state['total_segments']} segments - "
            f"full compilation queued for {scheduled_date}, track {track} is now free"
        )
    else:
        state["next_segment_index"] = next_index + 1
        save_series_state(state, track)

    return segment


def _add_days(date_str: str, days: int) -> str:
    from datetime import datetime, timedelta
    d = datetime.fromisoformat(date_str).date() + timedelta(days=days)
    return d.isoformat()


def get_active_source_files(exclude_track: int, num_tracks: int) -> set[str]:
    """Local fallback filenames currently in progress on OTHER tracks, to avoid a same-day repeat."""
    in_use = set()
    for track in range(num_tracks):
        if track == exclude_track:
            continue
        state = load_series_state(track)
        if state and state.get("source_file"):
            in_use.add(state["source_file"])
    return in_use
