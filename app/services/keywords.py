from __future__ import annotations

import json
import logging
import re

import yake
from kiwipiepy import Kiwi

from app.config import settings
from app.services.openai_client import get_openai_client
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


def _extract_llm_keywords(title: str, summary: str | None, max_keywords: int) -> list[dict] | None:
    """OpenAI로 키워드 추출. 실패 시 None 반환 → fallback."""
    client = get_openai_client()
    if not client:
        return None

    summary_part = f"\n요약: {summary.strip()}" if summary and summary.strip() else ""
    prompt = (
        f"다음 기사의 핵심 키워드 {max_keywords}개를 추출해줘.\n"
        f"- 기술명, 제품명, 개념어, 고유명사 위주\n"
        f"- '사용자', '정보', '기기' 같은 너무 일반적인 단어 제외\n"
        f"- JSON 배열로만 출력 (설명 없이)\n"
        f"\n제목: {title.strip()}{summary_part}"
    )

    try:
        response = client.chat.completions.create(
            model=settings.openai_keyword_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            timeout=settings.openai_timeout_seconds,
        )
        raw = response.choices[0].message.content or ""
        # 마크다운 코드블록 제거 (```json ... ``` 형태 대응)
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw).strip()
        keywords = json.loads(raw)
        if not isinstance(keywords, list):
            return None
        return [
            {"keyword": str(kw), "score": round(1 - i / max(len(keywords), 1), 4)}
            for i, kw in enumerate(keywords[:max_keywords])
            if str(kw).strip()
        ]
    except Exception:
        logger.warning("OpenAI keyword extraction failed", exc_info=True)
        return None


def extract_keywords(text: str, max_keywords: int = 10, title: str = "", summary: str | None = None) -> list[dict]:
    """Extract keywords from text.

    OpenAI API 키가 설정된 경우 LLM 추출 우선 사용.
    실패 or 키 없을 시:
    - 한국어: kiwipiepy 명사 추출
    - 영어: YAKE 통계 기반 추출

    Returns list of {"keyword": str, "score": float}.
    """
    if not text or len(text.strip()) < 10:
        return []

    try:
        # LLM 경로 (title/summary가 있을 때 더 정확)
        llm_input_title = title or text[:200]
        llm_result = _extract_llm_keywords(llm_input_title, summary, max_keywords)
        if llm_result is not None:
            return llm_result

        # Fallback: 통계 기반
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
