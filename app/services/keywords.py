from __future__ import annotations

import logging
import re

import yake
from kiwipiepy import Kiwi

from app.services.utils import detect_language

logger = logging.getLogger(__name__)

# 한국어 명사 추출용 — 모듈 수준에서 한 번만 초기화
_kiwi = Kiwi()

# 명사 태그: 일반명사(NNG), 고유명사(NNP)
_KO_NOUN_TAGS = {"NNG", "NNP"}

# 단독으로 키워드가 되기엔 의미없는 토큰 패턴
_NOISE_RE = re.compile(
    r"^\d+\.?\d*$"              # 순수 숫자
    r"|^[^a-zA-Z가-힣]{1,2}$"  # 기호·짧은 비문자열
)


def _is_noise(kw: str) -> bool:
    kw = kw.strip()
    if len(kw) < 2:
        return True
    if _NOISE_RE.match(kw):
        return True
    return False


def _extract_ko_keywords(text: str, max_keywords: int) -> list[dict]:
    """한국어: kiwipiepy로 명사 추출 후 빈도 기반 상위 키워드 반환."""
    tokens = _kiwi.tokenize(text)
    freq: dict[str, int] = {}
    for token in tokens:
        if token.tag not in _KO_NOUN_TAGS:
            continue
        noun = token.form.strip()
        if _is_noise(noun):
            continue
        freq[noun] = freq.get(noun, 0) + 1

    # 빈도 내림차순 정렬, score는 정규화 (1 - rank/total) 형태로 저장
    sorted_kw = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    total = len(sorted_kw)
    return [
        {"keyword": kw, "score": round(1 - i / max(total, 1), 4)}
        for i, (kw, _) in enumerate(sorted_kw[:max_keywords])
    ]


def extract_keywords(text: str, max_keywords: int = 10) -> list[dict]:
    """Extract keywords from text.

    - 한국어: kiwipiepy 명사 추출 (조사 제거, 의미 단위 보장)
    - 영어: YAKE 통계 기반 추출 (1~3gram)

    Returns list of {"keyword": str, "score": float}.
    """
    if not text or len(text.strip()) < 10:
        return []

    try:
        lang = detect_language(text)

        if lang == "ko":
            return _extract_ko_keywords(text, max_keywords)

        # 영어 경로: YAKE
        kw_extractor = yake.KeywordExtractor(
            lan="en",
            n=3,
            dedupLim=0.7,
            dedupFunc="seqm",
            windowsSize=2,
            top=max_keywords + 5,
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

    title_weight: title을 반복할 횟수. 빈도 기반 추출 시 title 단어에 가중치 부여.
    """
    parts = [title] * title_weight
    if summary:
        parts.append(summary)
    return " ".join(parts)
