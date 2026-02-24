from __future__ import annotations

from openai import OpenAI

from app.config import settings

_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI | None:
    global _openai_client
    if not settings.openai_api_key.strip():
        return None
    if _openai_client is None:
        _openai_client = OpenAI(api_key=settings.openai_api_key.strip())
    return _openai_client
