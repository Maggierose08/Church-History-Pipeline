import json
import logging
import random
import subprocess
import xml.sax.saxutils

from google.cloud import texttospeech_v1beta1 as texttospeech

from config import config
from retry_utils import retry_with_backoff

logger = logging.getLogger("video_pipeline")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = texttospeech.TextToSpeechClient()
    return _client


def _full_narration_text(script: dict) -> str:
    return " ".join(scene["narration"].strip() for scene in script["scenes"])


_voice_pool_cache = None


def _discover_voice_pool() -> list[str]:
    global _voice_pool_cache
    if _voice_pool_cache is not None:
        return _voice_pool_cache
    if config.google_tts_voice_names:
        logger.info(f"Using explicit GOOGLE_TTS_VOICE_NAMES: {config.google_tts_voice_names}")
        _voice_pool_cache = config.google_tts_voice_names
        return _voice_pool_cache
    try:
        client = _get_client()
        response = client.list_voices(language_code=config.tts_language_code)
        all_names = [v for v in response.voices if ("Standard" in v.name or "Wavenet" in v.name)]
        if config.tts_voice_gender:
            target_gender = texttospeech.SsmlVoiceGender[config.tts_voice_gender.upper()]
            gendered = [v.name for v in all_names if v.ssml_gender == target_gender]
            if gendered:
                logger.info(f"Discovered {len(gendered)} {config.tts_voice_gender} {config.tts_language_code} voice(s) via API: {gendered}")
                _voice_pool_cache = gendered
                return gendered
            logger.warning(f"No {config.tts_voice_gender} voices found for {config.tts_language_code} - falling back to any gender.")
        names = [v.name for v in all_names]
        if names:
            logger.info(f"Discovered {len(names)} {config.tts_language_code} voice(s) via API: {names}")
            _voice_pool_cache = names
            return names
        logger.warning(f"No voices found for {config.tts_language_code} via API - falling back to {config.tts_fallback_voice}")
    except Exception as e:
        logger.warning(f"Voice discovery failed ({e}) - falling back to {config.tts_fallback_voice}")
    _voice_pool_cache = [config.tts_fallback_voice]
    return _voice_pool_cache


def _pick_voice_name() -> str:
    pool = _discover_voice_pool()
    voice_name = random.choice(pool)
    logger.info(f"Selected Google TTS voice: {voice_name} (1 of {len(pool)} in pool)")
    return voice_name


def _build_marked_ssml(text: str):
    words = text.split()
    parts = ["<speak>"]
    for i, word in enumerate(words):
        escaped = xml.sax.saxutils.escape(word)
        parts.append(f'<mark name="w{i}"/>{escaped} ')
    parts.append("</speak>")
    return "".join(parts), words


@retry_with_backoff(max_retries=config.max_retries, base_delay=config.retry_base_delay)
def _call_google_tts(ssml: str, voice_name: str, expected_word_count: int):
    client = _get_client()
    request = texttospeech.SynthesizeSpeechRequest(
        input=texttospeech.SynthesisInput(ssml=ssml),
        voice=texttospeech.VoiceSelectionParams(language_code=config.tts_language_code, name=voice_name),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=config.tts_target_speed,
        ),
        enable_time_pointing=[texttospeech.SynthesizeSpeechRequest.TimepointType.SSML_MARK],
    )
    response = client.synthesize_speech(request=request)
    expected_marks = expected_word_count
    found_marks = len(response.timepoints)
    completeness = found_marks / expected_marks if expected_marks else 1.0
    if completeness < config.tts_min_timepoint_completeness:
        raise RuntimeError(f"Incomplete timepoint data: got {found_marks}/{expected_marks} marks ({completeness:.0%}). Retrying.")
    return response.audio_content, response.timepoints


def _timepoints_to_words(timepoints, words, audio_duration):
    times = {tp.mark_name: tp.time_seconds for tp in timepoints}
    starts = []
    missing = 0
    for i in range(len(words)):
        t = times.get(f"w{i}")
        if t is None:
            missing += 1
        starts.append(t)
    i = 0
    while i < len(starts):
        if starts[i] is None:
            j = i
            while j < len(starts) and starts[j] is None:
                j += 1
            prev_time = starts[i - 1] if i > 0 else 0.0
            next_time = starts[j] if j < len(starts) else audio_duration
            gap = max(0.01, next_time - prev_time)
            count = j - i
            for k in range(count):
                starts[i + k] = prev_time + gap * (k + 1) / (count + 1)
            i = j
        else:
            i += 1
    result = []
    for i, word in enumerate(words):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else audio_duration
        result.append({"word": word, "start": start, "end": end})
    if missing:
        logger.warning(f"Google TTS timepointing returned {len(words) - missing}/{len(words)} word(s) with exact timing even after retries.")
    return result


def _get_audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def generate_audio(script: dict, audio_output_path: str, timestamps_output_path: str) -> dict:
    text = _full_narration_text(script)
    voice_name = _pick_voice_name()
    ssml, words = _build_marked_ssml(text)
    logger.info(f"Requesting TTS ({len(words)} words) from Google Cloud TTS voice {voice_name} at {config.tts_target_speed}x")
    audio_content, timepoints = _call_google_tts(ssml, voice_name, len(words))
    with open(audio_output_path, "wb") as f:
        f.write(audio_content)
    duration = _get_audio_duration(audio_output_path)
    word_timestamps = _timepoints_to_words(timepoints, words, duration)
    logger.info(f"Final audio duration: {duration:.1f}s")
    timestamps = {"text": text, "voice_id": voice_name, "words": word_timestamps}
    with open(timestamps_output_path, "w") as f:
        json.dump(timestamps, f, indent=2)
    logger.info(f"Audio saved to {audio_output_path}; {len(word_timestamps)} word-level timestamps saved to {timestamps_output_path}")
    return {
        "audio_path": audio_output_path, "timestamps_path": timestamps_output_path,
        "word_count": len(word_timestamps), "voice_id": voice_name, "duration": duration,
    }
