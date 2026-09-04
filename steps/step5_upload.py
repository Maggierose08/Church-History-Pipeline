import logging

from config import config
import gcs_utils

logger = logging.getLogger("video_pipeline")


def upload_for_review(video_path: str, thumbnail_path: str, run_id: str) -> dict:
    logger.info("Uploading final video + thumbnail to GCS for review")
    video_url = gcs_utils.upload_and_sign(video_path, f"{config.gcs_review_prefix}/{run_id}/final_video.mp4")
    thumbnail_url = gcs_utils.upload_and_sign(thumbnail_path, f"{config.gcs_review_prefix}/{run_id}/thumbnail.png")
    logger.info(f"Review video URL (expires in {config.gcs_signed_url_days} days): {video_url}")
    logger.info(f"Review thumbnail URL (expires in {config.gcs_signed_url_days} days): {thumbnail_url}")
    return {"review_video_url": video_url, "review_thumbnail_url": thumbnail_url}
