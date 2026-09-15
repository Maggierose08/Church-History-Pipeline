import os
import random
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # --- Google Cloud Text-to-Speech ---
    google_tts_voice_names: list = field(
        default_factory=lambda: [
            v.strip()
            for v in (os.environ.get("GOOGLE_TTS_VOICE_NAMES") or "").split(",")
            if v.strip()
        ]
    )
    # British male voice, per explicit request - en-GB (not en-US), MALE gender.
    # Tier is Wavenet, NOT Studio. Studio was the original choice (based on
    # documentation suggesting it supported the SSML <mark> tags this pipeline's
    # word-timing captions depend on), but a REAL production run proved that
    # wrong: Google's actual API returned "400 <mark> tags are not currently
    # supported by Studio voices" - a flat, tier-wide rejection, not something
    # that varies by specific voice. That earlier research was incorrect and
    # should not have been trusted as strongly as it was. Wavenet is used here
    # instead specifically because it's the ONE tier with actual CONFIRMED
    # working evidence of <mark>-based captions succeeding in this project's own
    # real production logs (other pipelines, prior sessions) - not just
    # documentation claiming it should work. Neural2 is a plausible future
    # upgrade (Google's own docs list it at the same SSML/GA support level as
    # Wavenet), but should only be adopted after an actual test run confirms it
    # - not swapped in again on documentation alone, given what just happened.
    tts_language_code: str = os.environ.get("TTS_LANGUAGE_CODE") or "en-GB"
    tts_voice_gender: str = os.environ.get("TTS_VOICE_GENDER") or "MALE"
    tts_voice_tier: str = os.environ.get("TTS_VOICE_TIER") or "Wavenet"
    tts_fallback_voice: str = os.environ.get("TTS_FALLBACK_VOICE") or "en-GB-Wavenet-B"
    # 1.2x per explicit request. NOTE: church_script.py's word-count targets were
    # recalibrated (300-450 -> 240-360) based on PROPORTIONAL scaling from the
    # previously measured real rate (5.0 words/sec at 1.5x, on a different
    # voice/tier/accent) - not re-measured against this specific new voice.
    # Verify the actual duration in the first real production log (look for
    # "Final audio duration") and adjust church_script.py's word constants if
    # the real rate differs meaningfully from the ~4.0 words/sec this assumes.
    tts_target_speed: float = float(os.environ.get("TTS_TARGET_SPEED") or "1.2")
    tts_min_timepoint_completeness: float = float(os.environ.get("TTS_MIN_TIMEPOINT_COMPLETENESS") or "0.9")

    # --- Video / subtitle style ---
    # NOTE: no footage_source / pexels settings here - unlike the other pipelines,
    # visuals are procedurally-drawn stick figures (stick_figures.py), not downloaded
    # stock/gameplay footage clips, so there's nothing to fetch externally at all.
    video_width: int = int(os.environ.get("VIDEO_WIDTH", "1080"))
    video_height: int = int(os.environ.get("VIDEO_HEIGHT", "1920"))
    subtitle_font_family: str = os.environ.get("SUBTITLE_FONT_FAMILY", "Montserrat")
    subtitle_bold: bool = os.environ.get("SUBTITLE_BOLD", "true").lower() == "true"
    subtitle_font_size: int = int(os.environ.get("SUBTITLE_FONT_SIZE") or "72")
    subtitle_max_words_per_line: int = int(os.environ.get("SUBTITLE_MAX_WORDS_PER_LINE") or "3")
    # Captions default to the TOP of the frame here specifically (not "middle" like
    # the other pipelines) - the stick-figure scenes are composed with the top third
    # of the frame deliberately left empty for exactly this purpose.
    subtitle_vertical_position: str = os.environ.get("SUBTITLE_VERTICAL_POSITION") or "top"
    subtitle_vertical_offset_px: int = int(os.environ.get("SUBTITLE_VERTICAL_OFFSET_PX") or "60")
    subtitle_active_word_color: str = os.environ.get("SUBTITLE_ACTIVE_WORD_COLOR", "#FF0000")
    subtitle_line_color: str = os.environ.get("SUBTITLE_LINE_COLOR", "#FFFFFF")
    subtitle_color_palette: list = field(
        default_factory=lambda: [
            ("FF0000", "FFFFFF"), ("00C2FF", "FFFFFF"), ("39FF14", "FFFFFF"),
            ("FF9900", "FFFFFF"), ("FF00E6", "FFFFFF"),
        ]
    )

    # --- Gemini (script generation with Search Grounding + thumbnail generation) ---
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
    gemini_text_model: str = os.environ.get("GEMINI_TEXT_MODEL") or "gemini-3.6-flash"
    gemini_image_model: str = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

    # --- Pollinations (free fallback for thumbnails only) ---
    pollinations_api_key: str = os.environ.get("POLLINATIONS_API_KEY", "")

    # --- Mistral + Tavily (manual grounding fallback when Gemini is unavailable) ---
    mistral_api_key: str = os.environ.get("MISTRAL_API_KEY", "")
    # mistral-small-latest, not mistral-large-latest - Large requires phone (SMS)
    # verification on Mistral's free tier, and a 403 "tier_not_allowed" error was
    # hit in production on an unverified account. Small is confirmed available on
    # every free-tier account regardless of verification status.
    mistral_text_model: str = os.environ.get("MISTRAL_TEXT_MODEL") or "mistral-small-latest"
    tavily_api_key: str = os.environ.get("TAVILY_API_KEY", "")

    # --- Google Cloud Storage ---
    gcs_bucket: str = os.environ.get("GCS_BUCKET", "")
    gcs_staging_prefix: str = os.environ.get("GCS_STAGING_PREFIX", "church_staging")
    gcs_review_prefix: str = os.environ.get("GCS_REVIEW_PREFIX", "church_review")
    gcs_signed_url_days: int = int(os.environ.get("GCS_SIGNED_URL_DAYS", "7"))
    gcs_series_state_path_template: str = os.environ.get("GCS_SERIES_STATE_PATH_TEMPLATE") or "church_series/track_{track}.json"
    gcs_daily_slot_path: str = os.environ.get("GCS_DAILY_SLOT_PATH") or "church_series/daily_slot_counter.json"
    gcs_analytics_prefix: str = os.environ.get("GCS_ANALYTICS_PREFIX") or "church_analytics"

    # --- YouTube Shorts ---
    youtube_client_id: str = os.environ.get("YOUTUBE_CLIENT_ID", "")
    youtube_client_secret: str = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    youtube_refresh_token: str = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
    youtube_privacy_status: str = os.environ.get("YOUTUBE_PRIVACY_STATUS") or "public"
    youtube_category_id: str = os.environ.get("YOUTUBE_CATEGORY_ID") or "27"  # 27 = Education

    # --- Notifications ---
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT") or "587")
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    notify_email_to: str = os.environ.get("NOTIFY_EMAIL_TO", "")
    notify_email_from: str = os.environ.get("NOTIFY_EMAIL_FROM", "")
    performance_min_age_days: float = float(os.environ.get("PERFORMANCE_MIN_AGE_DAYS") or "7")

    # --- Local state / output ---
    output_dir: str = os.environ.get("OUTPUT_DIR", "./outputs")
    max_retries: int = int(os.environ.get("MAX_RETRIES", "3"))
    retry_base_delay: float = float(os.environ.get("RETRY_BASE_DELAY", "2.0"))

    # --- Multi-part story continuation ---
    videos_per_day: int = int(os.environ.get("VIDEOS_PER_DAY") or "3")

    # --- Publish scheduling ---
    post_window_start: str = os.environ.get("POST_WINDOW_START") or "14:30"
    post_window_end: str = os.environ.get("POST_WINDOW_END") or "17:30"
    post_timezone: str = os.environ.get("POST_TIMEZONE") or "America/New_York"

    def pick_subtitle_color_pair(self):
        active, line = random.choice(self.subtitle_color_palette)
        return f"#{active}", f"#{line}"

    def validate_for_steps(self, steps):
        missing = []
        if "upload" in steps and not self.gcs_bucket:
            missing.append("GCS_BUCKET")
        if missing:
            raise EnvironmentError("Missing required environment variable(s): " + ", ".join(missing))


config = Config()
