import logging
logger = logging.getLogger("video_pipeline")
def send_failure_email(run_id, failed_step, exception):
    logger.warning(f"[SMTP not configured in test] Would send failure email for {run_id} at {failed_step}")
