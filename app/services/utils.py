from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonicalize_url(raw: str) -> str:
    parsed = urlparse(raw.strip())
    filtered_qs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_KEYS]
    clean = parsed._replace(query=urlencode(filtered_qs), fragment="")
    return urlunparse(clean)


def detect_language(title: str) -> str:
    if re.search(r"[\uac00-\ud7af]", title):
        return "ko"
    return "en"


def title_key(title: str) -> str:
    norm = re.sub(r"\s+", " ", title.lower()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
