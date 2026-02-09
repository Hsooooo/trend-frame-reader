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


def compute_score(source_weight: float, published_at: datetime | None) -> float:
    return round((freshness_score(published_at) * 0.7) + (source_weight * 0.3), 4)
