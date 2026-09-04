import logging

logger = logging.getLogger("video_pipeline")


def compute_score(youtube_stats: dict | None) -> float:
    score = 0.0
    if youtube_stats:
        score += youtube_stats["views"] * 100.0
        score += youtube_stats["likes"] * 5.0
        score += youtube_stats["comments"] * 10.0
    return score


def rank_performance(scored_records: list[dict], top_fraction: float = 0.3):
    if not scored_records:
        return [], []
    ranked = sorted(scored_records, key=lambda r: r["score"], reverse=True)
    n = len(ranked)
    split_count = max(1, round(n * top_fraction))
    return ranked[:split_count], ranked[-split_count:]
