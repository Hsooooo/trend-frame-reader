from __future__ import annotations

from datetime import UTC, datetime


def freshness_score(published_at: datetime | None) -> float:
    if not published_at:
        return 0.2
    now = datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age_hours = max((now - published_at).total_seconds() / 3600, 0)
    return max(0.0, 1.2 - (age_hours / 48.0))


def popularity_score(points: int | None) -> float:
    """Normalize community vote count (e.g. HN points) to 0‑1 range."""
    if not points or points <= 0:
        return 0.0
    return min(points / 300.0, 1.0)


def compute_score(
    source_weight: float,
    published_at: datetime | None,
    *,
    points: int | None = None,
) -> float:
    fresh = freshness_score(published_at)
    pop = popularity_score(points)
    if pop > 0:
        # Sources with community votes: freshness 50% + weight 20% + popularity 30%
        return round(fresh * 0.5 + source_weight * 0.2 + pop * 0.3, 4)
    return round(fresh * 0.7 + source_weight * 0.3, 4)
