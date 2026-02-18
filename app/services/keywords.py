from __future__ import annotations

import logging
import re

import yake

from app.services.utils import detect_language

logger = logging.getLogger(__name__)

# 단독으로 키워드가 되기엔 의미없는 토큰 패턴
_NOISE_RE = re.compile(
    r"^\d+\.?\d*$"          # 순수 숫자
    r"|^[^a-zA-Z가-힣]{1,2}$"  # 기호·짧은 비문자열
)


def _is_noise(kw: str) -> bool:
    kw = kw.strip()
    if len(kw) < 3:
        return True
    if _NOISE_RE.match(kw):
        return True
    return False


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
            n=3,           # 1~3gram: 단일 단어 + 기술 구문(2~3 단어) 모두 포착
            dedupLim=0.7,  # 유사 키워드 중복 억제 강화 (기본 0.9 → 0.7)
            dedupFunc="seqm",  # sequence matcher: levs보다 구문 중복 감지 정확
            windowsSize=2,
            top=max_keywords + 5,  # 후처리 필터 여유분 확보
        )
        raw = kw_extractor.extract_keywords(text)
        results = [
            {"keyword": kw, "score": float(score)}
            for kw, score in raw
            if not _is_noise(kw)
        ]
        return results[:max_keywords]
    except Exception:
        logger.warning("keyword extraction failed", exc_info=True)
        return []


def build_keyword_text(title: str, summary: str | None, title_weight: int = 3) -> str:
    """Combine title and summary for keyword extraction.

    title_weight: title을 반복할 횟수. YAKE는 빈도를 중요도로 활용하므로
    title을 여러 번 넣으면 title 단어가 높은 점수를 받음.
    """
    parts = [title] * title_weight
    if summary:
        parts.append(summary)
    return " ".join(parts)
