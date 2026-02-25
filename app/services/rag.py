from __future__ import annotations

import logging

from app.config import settings
from app.mongo import get_articles_collection
from app.services.embeddings import generate_embedding
from app.services.openai_client import get_openai_client

logger = logging.getLogger(__name__)


def search_similar_bookmarks(query_embedding: list[float], top_k: int = 5, user_id: int | None = None) -> list[dict]:
    collection = get_articles_collection()
    if collection is None:
        return []

    vector_search: dict = {
        "index": "vector_index",
        "path": "embedding",
        "queryVector": query_embedding,
        "numCandidates": top_k * 10,
        "limit": top_k,
    }
    if user_id is not None:
        vector_search["filter"] = {"user_id": {"$eq": user_id}}

    pipeline = [
        {"$vectorSearch": vector_search},
        {
            "$project": {
                "item_id": 1,
                "title": 1,
                "summary": 1,
                "url": 1,
                "source": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    try:
        results = list(collection.aggregate(pipeline))
        return [
            {
                "item_id": r.get("item_id"),
                "title": r.get("title"),
                "summary": r.get("summary"),
                "url": r.get("url"),
                "source": r.get("source"),
                "similarity_score": r.get("score"),
            }
            for r in results
        ]
    except Exception:
        logger.exception("Failed to run vector search pipeline")
        return []


def build_rag_context(results: list[dict]) -> str:
    lines: list[str] = []
    for i, r in enumerate(results, start=1):
        lines.append(f"[{i}] {r.get('title', '')}")
        lines.append(f"출처: {r.get('source', '')}")
        lines.append(f"URL: {r.get('url', '')}")
        lines.append(f"요약: {r.get('summary', '')}")
        lines.append("")
    return "\n".join(lines).rstrip()


def generate_rag_answer(query: str, context: str) -> str:
    client = get_openai_client()
    if client is None:
        return "OpenAI 클라이언트를 초기화할 수 없습니다."

    system_prompt = (
        "너는 사용자의 북마크된 기사를 기반으로 질문에 답하는 어시스턴트야.\n"
        "아래 북마크 기사를 참고해서 질문에 답해줘.\n"
        "답변에 사용한 기사는 출처로 표시해줘.\n"
        "관련 북마크가 없으면 \"관련 북마크를 찾지 못했습니다\"라고 답해."
    )
    user_message = f"[북마크 기사]\n{context}\n\n[질문]\n{query}"

    try:
        response = client.chat.completions.create(
            model=settings.openai_keyword_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            timeout=settings.openai_timeout_seconds,
        )
        return response.choices[0].message.content or ""
    except Exception:
        logger.exception("Failed to generate RAG answer for query: %s", query)
        return "답변 생성에 실패했습니다."


def ask_bookmarks(query: str, top_k: int | None = None, user_id: int | None = None) -> dict:
    top_k = top_k or settings.rag_top_k

    embedding = generate_embedding(query)
    if embedding is None:
        return {"answer": "임베딩 생성에 실패했습니다.", "sources": []}

    results = search_similar_bookmarks(embedding, top_k=top_k, user_id=user_id)
    if not results:
        return {"answer": "관련 북마크를 찾지 못했습니다.", "sources": []}

    context = build_rag_context(results)
    answer = generate_rag_answer(query, context)

    sources = [
        {
            "item_id": r.get("item_id"),
            "title": r.get("title"),
            "url": r.get("url"),
            "similarity": r.get("similarity_score"),
        }
        for r in results
    ]

    return {"answer": answer, "sources": sources}
