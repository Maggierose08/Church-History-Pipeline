import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import daily_slots
import published_videos
import pending_compilations
import series_state
import story_generation
from config import config
from notifier import send_failure_email
from schedule_check import local_today_str, pick_target_publish_datetime
from state import RunState
from steps.step2_tts import generate_audio
from church_render import render_segment_video
from steps.step4_thumbnail import generate_thumbnail
from steps.step5_upload import upload_for_review
from steps.step6_youtube_upload import publish_to_youtube

logger = logging.getLogger("video_pipeline")


def setup_logging(run_dir: Path):
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )


def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _compilation_to_segment_shape(compilation_data: dict) -> dict:
    """
    Normalizes a queued compilation (title/social_title/caption + a list of segments,
    each with its own scenes) into the same {"title", "social_title", "caption",
    "scenes"} shape a single segment already has, by flattening every segment's
    scenes into one combined list - so TTS/render code downstream never needs to
    know whether it's handling a single short segment or a full compilation.
    """
    all_scenes = [scene for seg in compilation_data["segments"] for scene in seg["scenes"]]
    return {
        "title": compilation_data["title"],
        "social_title": compilation_data["social_title"],
        "caption": compilation_data["caption"],
        "scenes": all_scenes,
    }


def _determine_track_and_schedule(state: RunState, skip_schedule_check: bool):
    if skip_schedule_check and "track" in state.data:
        logger.info(f"Resuming run on track {state.data['track']} (schedule check skipped)")
        return state.data["track"], state.data["target_date"]
    today = local_today_str()
    track = daily_slots.claim_next_slot(today)
    if track is None:
        logger.info(f"All {config.videos_per_day} of today's ({today}) video slots are already claimed - nothing to do.")
        return None
    state.data["track"] = track
    state.data["target_date"] = today
    state.save()
    return track, today


def _get_todays_script(track: int, target_date: str) -> tuple[dict, bool, str | None]:
    """
    Returns (script_in_segment_shape, is_compilation, compilation_id_or_none).
    Checks the pending-compilations queue FIRST - if anything is due today, that
    fills this slot instead of continuing/starting a track's short-form series,
    since compilations and short-form content share the same 3-per-day budget.
    """
    due = pending_compilations.get_due_compilation(target_date)
    if due is not None:
        logger.info(f"Compilation {due['compilation_id']} is due today - posting it instead of short-form content")
        return _compilation_to_segment_shape(due["full_script_data"]), True, due["compilation_id"]

    segment = series_state.advance_series(track, target_date)
    if segment is not None:
        return segment, False, None

    exclude_files = series_state.get_active_source_files(track, config.videos_per_day)
    story_data, source_file = story_generation.generate_story_with_fallback(exclude_local_files=exclude_files)
    segment = series_state.start_new_series(story_data, track, source_file)
    return segment, False, None


def run(run_id: str, skip_schedule_check: bool):
    run_dir = Path(config.output_dir) / run_id
    setup_logging(run_dir)
    state = RunState(run_id, config.output_dir)
    logger.info(f"=== Starting run {run_id} ===")

    try:
        result = _determine_track_and_schedule(state, skip_schedule_check)
        if result is None:
            return
        track, target_date = result

        target_publish_datetime = pick_target_publish_datetime(target_date, track)
        state.data["target_publish_datetime"] = target_publish_datetime.isoformat()
        state.save()
        logger.info(f"Track {track}, target publish datetime: {target_publish_datetime.isoformat()}")

        if state.is_done("script"):
            logger.info("Step 'script' already completed - skipping (resuming run)")
            script = _load_json(state.get_artifact("script")["path"])
            is_compilation = state.data.get("is_compilation", False)
            compilation_id = state.data.get("compilation_id")
        else:
            state.mark_running("script")
            script_path = run_dir / "script.json"
            try:
                script, is_compilation, compilation_id = _get_todays_script(track, target_date)
                state.data["is_compilation"] = is_compilation
                state.data["compilation_id"] = compilation_id
                state.save()
                with open(script_path, "w") as f:
                    json.dump(script, f, indent=2)
                state.mark_completed("script", {"path": str(script_path)})
            except Exception as e:
                state.mark_failed("script", e)
                raise

        if state.is_done("tts"):
            logger.info("Step 'tts' already completed - skipping (resuming run)")
        else:
            state.mark_running("tts")
            audio_path = run_dir / "audio.mp3"
            timestamps_path = run_dir / "timestamps.json"
            try:
                tts_result = generate_audio(script, str(audio_path), str(timestamps_path))
                state.mark_completed("tts", tts_result)
            except Exception as e:
                state.mark_failed("tts", e)
                raise

        if state.is_done("render"):
            logger.info("Step 'render' already completed - skipping (resuming run)")
            render_result = state.get_artifact("render")
        else:
            state.mark_running("render")
            try:
                tts_artifact = state.get_artifact("tts")
                render_result = render_segment_video(
                    script, tts_artifact["audio_path"], tts_artifact["timestamps_path"], run_id, str(run_dir)
                )
                state.mark_completed("render", render_result)
            except Exception as e:
                state.mark_failed("render", e)
                raise

        if state.is_done("thumbnail"):
            logger.info("Step 'thumbnail' already completed - skipping (resuming run)")
            thumbnail_result = state.get_artifact("thumbnail")
        else:
            state.mark_running("thumbnail")
            try:
                thumbnail_path = run_dir / "thumbnail.png"
                thumbnail_result = generate_thumbnail(script["title"], str(thumbnail_path))
                state.mark_completed("thumbnail", thumbnail_result)
            except Exception as e:
                state.mark_failed("thumbnail", e)
                raise

        if state.is_done("upload"):
            logger.info("Step 'upload' already completed - skipping (resuming run)")
            upload_result = state.get_artifact("upload")
        else:
            state.mark_running("upload")
            try:
                upload_result = upload_for_review(render_result["video_path"], thumbnail_result["thumbnail_path"], run_id)
                state.mark_completed("upload", upload_result)
            except Exception as e:
                state.mark_failed("upload", e)
                raise

        if state.is_done("youtube"):
            logger.info("Step 'youtube' already completed - skipping (resuming run)")
        else:
            state.mark_running("youtube")
            try:
                target_dt = datetime.fromisoformat(state.data["target_publish_datetime"])
                youtube_result = publish_to_youtube(
                    render_result["video_path"], thumbnail_result["thumbnail_path"],
                    script["social_title"], script["caption"], publish_at=target_dt,
                )
                state.mark_completed("youtube", youtube_result)
            except Exception as e:
                state.mark_failed("youtube", e)
                logger.error(f"YouTube publish failed (non-fatal, continuing): {e}")

        if state.data.get("is_compilation") and state.data.get("compilation_id"):
            try:
                pending_compilations.mark_compilation_posted(state.data["compilation_id"])
            except Exception as e:
                logger.warning(f"Failed to mark compilation as posted (non-fatal): {e}")

        try:
            youtube_artifact = state.get_artifact("youtube") or {}
        except Exception:
            youtube_artifact = {}
        youtube_video_id = youtube_artifact.get("video_id")
        try:
            published_videos.record_published_video(
                run_id, track, script.get("social_title", script["title"]), script["title"], youtube_video_id,
            )
        except Exception as e:
            logger.warning(f"Failed to record published video for analytics tracking (non-fatal): {e}")

        logger.info(f"Review this run's video before it goes anywhere further: {upload_result['review_video_url']}")
        logger.info(f"=== Run {run_id} finished successfully (track {track}, compilation={state.data.get('is_compilation')}) ===")
        logger.info(f"Outputs in: {run_dir}")

    except Exception as e:
        failed_step = state.first_failed_step() or "unknown"
        logger.error(f"Run {run_id} failed at step '{failed_step}' after retries: {e}")
        send_failure_email(run_id, failed_step, e)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Church history video pipeline")
    parser.add_argument("--run-id", default=None, help="Resume an existing run by ID.")
    args = parser.parse_args()
    is_resume = args.run_id is not None
    run_id = args.run_id or (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    run(run_id, skip_schedule_check=is_resume)
