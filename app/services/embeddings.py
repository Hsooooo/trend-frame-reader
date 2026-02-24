from __future__ import annotations

import logging

from app.config import settings
from app.services.openai_client import get_openai_client

logger = logging.getLogger(__name__)


def build_embedding_text(title: str, summary: str | None) -> str | None:
    if not summary or not summary.strip():
        return None
    return f"{title}\n\n{summary}"


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = get_openai_client()
    if client is None:
        logger.warning("OpenAI client unavailable — skipping embedding generation")
        return []
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]
    except Exception:
        logger.exception("Failed to generate embeddings for %d texts", len(texts))
        return []


def generate_embedding(text: str) -> list[float] | None:
    results = generate_embeddings([text])
    return results[0] if results else None
