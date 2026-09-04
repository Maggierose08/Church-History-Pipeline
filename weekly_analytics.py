import logging
import sys

import published_videos
import youtube_analytics
import performance_scoring
import guidance_extraction
import performance_guidance
from config import config

logger = logging.getLogger("video_pipeline")


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _build_report(scored, top, bottom, guidance) -> str:
    lines = [f"Weekly performance report - {len(scored)} video(s) analyzed\n", "=" * 50, "\nTOP PERFORMERS:"]
    for r in top:
        lines.append(f"  [{r['score']:.0f}] {r['title']} - topic: {r['topic']}")
    lines.append("\nBOTTOM PERFORMERS:")
    for r in bottom:
        lines.append(f"  [{r['score']:.0f}] {r['title']} - topic: {r['topic']}")
    lines.append("\n" + "=" * 50)
    lines.append("\nGUIDANCE FOR FUTURE SCRIPTS (auto-applied to prompts going forward):")
    lines.append(guidance)
    return "\n".join(lines)


def run():
    setup_logging()
    logger.info("=== Starting weekly analytics run ===")
    eligible = published_videos.get_unanalyzed_eligible_records(config.performance_min_age_days)
    logger.info(f"Found {len(eligible)} video(s) eligible for analysis (posted {config.performance_min_age_days}+ days ago)")
    if not eligible:
        logger.info("Nothing new to analyze this week - exiting.")
        return

    scored = []
    for record in eligible:
        yt_stats = youtube_analytics.get_video_stats(record["youtube_video_id"]) if record.get("youtube_video_id") else None
        if yt_stats is None:
            logger.warning(f"Run {record['run_id']}: no stats available, skipping")
            continue
        score = performance_scoring.compute_score(yt_stats)
        scored.append({**record, "score": score, "youtube_stats": yt_stats})
        logger.info(f"Run {record['run_id']}: score={score:.0f} (YouTube: {yt_stats})")

    if len(scored) < 2:
        logger.info(f"Only {len(scored)} video(s) got real stats - not enough for a meaningful comparison this week.")
        published_videos.mark_analyzed({r["run_id"] for r in eligible})
        return

    top, bottom = performance_scoring.rank_performance(scored, top_fraction=0.3)
    guidance = guidance_extraction.extract_guidance(top, bottom)
    performance_guidance.save_guidance(guidance, based_on_n_videos=len(scored))
    published_videos.mark_analyzed({r["run_id"] for r in eligible})

    report = _build_report(scored, top, bottom, guidance)
    logger.info(f"\n{report}")
    logger.info("=== Weekly analytics run complete ===")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.error(f"Weekly analytics run failed: {e}")
        sys.exit(1)
