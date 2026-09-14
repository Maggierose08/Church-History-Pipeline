import json
import logging
import os
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
    """
    Filters by the configured tier (e.g. "Studio") rather than the previous
    hardcoded Standard/Wavenet check, since this pipeline now specifically wants
    a single consistent Studio-tier voice, not a rotating pool of Standard/
    Wavenet voices. Gender is confirmed via the API's own ssml_gender field
    rather than assumed from the voice name, since Google doesn't document a
    reliable naming convention for gender.
    """
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
        tier = config.tts_voice_tier
        all_names = [v for v in response.voices if tier in v.name]
        if not all_names:
            logger.warning(f"No {tier}-tier voices found for {config.tts_language_code} - falling back to Standard/Wavenet.")
            all_names = [v for v in response.voices if ("Standard" in v.name or "Wavenet" in v.name)]
        if config.tts_voice_gender:
            target_gender = texttospeech.SsmlVoiceGender[config.tts_voice_gender.upper()]
            gendered = [v.name for v in all_names if v.ssml_gender == target_gender]
            if gendered:
                logger.info(f"Discovered {len(gendered)} {config.tts_voice_gender} {tier} {config.tts_language_code} voice(s) via API: {sorted(gendered)}")
                _voice_pool_cache = sorted(gendered)
                return _voice_pool_cache
            logger.warning(f"No {config.tts_voice_gender} {tier} voices found for {config.tts_language_code} - falling back to any gender within the tier.")
        names = [v.name for v in all_names]
        if names:
            logger.info(f"Discovered {len(names)} {tier} {config.tts_language_code} voice(s) via API: {sorted(names)}")
            _voice_pool_cache = sorted(names)
            return _voice_pool_cache
        logger.warning(f"No voices found for {config.tts_language_code} via API - falling back to {config.tts_fallback_voice}")
    except Exception as e:
        logger.warning(f"Voice discovery failed ({e}) - falling back to {config.tts_fallback_voice}")
    _voice_pool_cache = [config.tts_fallback_voice]
    return _voice_pool_cache


def _pick_voice_name() -> str:
    """
    Picks the FIRST voice from the (sorted, so deterministic) discovered pool -
    NOT a random choice - per explicit request to use the exact same voice for
    every video, rather than rotating through several for variety.
    """
    pool = _discover_voice_pool()
    voice_name = pool[0]
    logger.info(f"Selected Google TTS voice: {voice_name} (same voice used for every video, out of {len(pool)} matching candidate(s))")
    return voice_name


def _build_marked_ssml(text: str, words: list[str] = None):
    """
    One mark per word (not two - collapses adjacent zero-content marks otherwise).
    Marks are named by LOCAL index within this specific call's word list (0-based),
    NOT any global position - callers stitching multiple chunks together are
    responsible for mapping local mark indices back to global word positions
    themselves (see _chunk_words_for_tts / generate_audio).
    """
    if words is None:
        words = text.split()
    parts = ["<speak>"]
    for i, word in enumerate(words):
        escaped = xml.sax.saxutils.escape(word)
        parts.append(f'<mark name="w{i}"/>{escaped} ')
    parts.append("</speak>")
    return "".join(parts), words


# Google Cloud TTS hard-rejects any single request over 5000 bytes of input
# text/SSML. Individual short segments (300-450 words) never came close to this,
# but a full COMPILATION (10-14 segments concatenated, 2000+ words) blows past it
# by 10x or more once per-word <mark> tags are added. This wasn't caught until a
# real compilation actually reached the TTS step in production, since no earlier
# testing exercised a text this long. MAX_CHUNK_BYTES stays well under the hard
# 5000 limit to leave margin for the <speak></speak> wrapper and any single long
# word/mark-index overshoot at a chunk boundary.
MAX_CHUNK_BYTES = 4200


def _chunk_words_for_tts(words: list[str], max_bytes: int = MAX_CHUNK_BYTES) -> list[list[str]]:
    """
    Splits a word list into chunks, each of which is guaranteed to produce marked
    SSML under max_bytes - built incrementally (not just an average-size estimate)
    since mark tag byte size grows slightly as the index grows more digits, and a
    naive average could still overshoot right at a chunk boundary.
    """
    chunks = []
    current: list[str] = []
    current_ssml_len = len("<speak></speak>")
    for word in words:
        local_index = len(current)
        mark_and_word = f'<mark name="w{local_index}"/>{xml.sax.saxutils.escape(word)} '
        added_len = len(mark_and_word.encode("utf-8"))
        if current and current_ssml_len + added_len > max_bytes:
            chunks.append(current)
            current = []
            current_ssml_len = len("<speak></speak>")
            local_index = 0
            mark_and_word = f'<mark name="w{local_index}"/>{xml.sax.saxutils.escape(word)} '
            added_len = len(mark_and_word.encode("utf-8"))
        current.append(word)
        current_ssml_len += added_len
    if current:
        chunks.append(current)
    return chunks


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


def _concatenate_audio(chunk_paths: list[str], out_path: str):
    """Concatenates multiple TTS chunk audio files into one, in order, via
    ffmpeg's concat demuxer - same approach already used elsewhere in this
    pipeline for video clips."""
    list_file = f"{out_path}.concat_list.txt"
    with open(list_file, "w") as f:
        for p in chunk_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_path],
        capture_output=True, text=True,
    )
    os.remove(list_file)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio concatenation failed: {result.stderr[-1500:]}")


def generate_audio(script: dict, audio_output_path: str, timestamps_output_path: str) -> dict:
    """
    Splits the full narration into TTS-safe chunks (see _chunk_words_for_tts) when
    the text is long enough to exceed Google's hard 5000-byte-per-request limit -
    this only actually branches into multiple requests for FULL COMPILATIONS
    (2000+ words); every individual short segment still takes the exact same
    single-request path as before, completely unchanged. Each chunk is
    synthesized separately, the resulting audio files are concatenated in order,
    and each chunk's word timestamps are offset by the cumulative duration of
    every prior chunk so the final timestamps are correct against the ONE
    combined audio file, not restarting from zero at each chunk boundary.
    """
    text = _full_narration_text(script)
    voice_name = _pick_voice_name()
    all_words = text.split()
    word_chunks = _chunk_words_for_tts(all_words)

    if len(word_chunks) > 1:
        logger.info(f"Narration ({len(all_words)} words) exceeds the single-request TTS byte limit - splitting into {len(word_chunks)} chunks")

    chunk_audio_paths = []
    all_word_timestamps = []
    cumulative_offset = 0.0
    output_dir = os.path.dirname(audio_output_path) or "."

    for chunk_index, chunk_words in enumerate(word_chunks):
        ssml, _ = _build_marked_ssml(text, words=chunk_words)
        logger.info(f"Requesting TTS chunk {chunk_index+1}/{len(word_chunks)} ({len(chunk_words)} words) from Google Cloud TTS voice {voice_name} at {config.tts_target_speed}x")
        audio_content, timepoints = _call_google_tts(ssml, voice_name, len(chunk_words))

        chunk_path = f"{output_dir}/_tts_chunk_{chunk_index}.mp3"
        with open(chunk_path, "wb") as f:
            f.write(audio_content)
        chunk_audio_paths.append(chunk_path)

        chunk_duration = _get_audio_duration(chunk_path)
        chunk_word_timestamps = _timepoints_to_words(timepoints, chunk_words, chunk_duration)
        for wt in chunk_word_timestamps:
            wt["start"] += cumulative_offset
            wt["end"] += cumulative_offset
        all_word_timestamps.extend(chunk_word_timestamps)
        cumulative_offset += chunk_duration

    if len(chunk_audio_paths) == 1:
        os.replace(chunk_audio_paths[0], audio_output_path)
    else:
        _concatenate_audio(chunk_audio_paths, audio_output_path)
        for p in chunk_audio_paths:
            if os.path.exists(p):
                os.remove(p)

    duration = _get_audio_duration(audio_output_path)
    logger.info(f"Final audio duration: {duration:.1f}s" + (f" ({len(word_chunks)} TTS chunks stitched together)" if len(word_chunks) > 1 else ""))

    timestamps = {"text": text, "voice_id": voice_name, "words": all_word_timestamps}
    with open(timestamps_output_path, "w") as f:
        json.dump(timestamps, f, indent=2)
    logger.info(f"Audio saved to {audio_output_path}; {len(all_word_timestamps)} word-level timestamps saved to {timestamps_output_path}")
    return {
        "audio_path": audio_output_path, "timestamps_path": timestamps_output_path,
        "word_count": len(all_word_timestamps), "voice_id": voice_name, "duration": duration,
    }
