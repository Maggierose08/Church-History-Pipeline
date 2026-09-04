import datetime
import logging

from google.cloud import storage

from config import config

logger = logging.getLogger("video_pipeline")

_client = None


def get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def upload_and_sign(local_path: str, gcs_path: str) -> str:
    bucket = get_client().bucket(config.gcs_bucket)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(local_path)
    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(days=config.gcs_signed_url_days),
        method="GET",
    )
    logger.info(f"Uploaded {local_path} -> gs://{config.gcs_bucket}/{gcs_path} (signed URL generated)")
    return url
