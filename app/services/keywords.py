from __future__ import annotations

import logging

import yake

from app.services.utils import detect_language

logger = logging.getLogger(__name__)


def extract_keywords(text: str, max_keywords: int = 10) -> list[dict]:
    """Extract keywords from text using YAKE.

    Returns list of {"keyword": str, "score": float}.
    YAKE score is lower = more relevant; stored as-is for downstream use.
    """
    if not text or len(text.strip()) < 10:
        return []

    try:
        lang = detect_language(text)
        lan = "ko" if lang == "ko" else "en"

        kw_extractor = yake.KeywordExtractor(
            lan=lan,
            n=2,
            dedupLim=0.9,
            top=max_keywords,
        )
        raw = kw_extractor.extract_keywords(text)
        return [{"keyword": kw, "score": float(score)} for kw, score in raw]
    except Exception:
        logger.warning("keyword extraction failed", exc_info=True)
        return []


def build_keyword_text(title: str, summary: str | None) -> str:
    """Combine title and summary for keyword extraction."""
    parts = [title]
    if summary:
        parts.append(summary)
    return " ".join(parts)
