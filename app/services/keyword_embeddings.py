from __future__ import annotations

import logging
import math

from pymongo.collection import Collection

from app.services.embeddings import generate_embedding, generate_embeddings

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """In-memory cosine similarity fallback."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_similar_en_keyword(
    keywords_col: Collection,
    ko_keyword: str,
    ko_embedding: list[float],
    threshold: float = 0.85,
) -> dict | None:
    """Find the most similar English keyword using Atlas Vector Search.

    Falls back to in-memory cosine similarity if Atlas Vector Search is unavailable.
    """
    # Try Atlas Vector Search first
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "keyword_vector_index",
                    "path": "embedding",
                    "queryVector": ko_embedding,
                    "numCandidates": 50,
                    "limit": 5,
                    "filter": {"language": "en"},
                }
            },
            {
                "$project": {
                    "keyword": 1,
                    "doc_frequency": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        results = list(keywords_col.aggregate(pipeline))
        for r in results:
            if r["keyword"] != ko_keyword and r.get("score", 0) >= threshold:
                return {
                    "keyword": r["keyword"],
                    "doc_frequency": r.get("doc_frequency", 0),
                    "similarity": r["score"],
                }
        return None
    except Exception:
        logger.debug("Atlas Vector Search unavailable, falling back to in-memory similarity")

    # Fallback: in-memory cosine similarity
    cursor = keywords_col.find(
        {"language": "en", "embedding": {"$exists": True}},
        {"keyword": 1, "embedding": 1, "doc_frequency": 1},
    )
    best_match = None
    best_score = 0.0
    for doc in cursor:
        sim = _cosine_similarity(ko_embedding, doc["embedding"])
        if sim >= threshold and sim > best_score:
            best_score = sim
            best_match = {
                "keyword": doc["keyword"],
                "doc_frequency": doc.get("doc_frequency", 0),
                "similarity": sim,
            }
    return best_match


def get_topic_clusters(
    keywords_col: Collection,
    period_keywords: list[dict],
) -> list[dict]:
    """Build cross-language topic clusters from period keywords.

    Args:
        keywords_col: MongoDB keywords collection
        period_keywords: List of dicts with 'keyword', 'doc_frequency', 'language'

    Returns:
        List of cluster dicts sorted by total_frequency desc:
        [
            {
                "topic": "kubernetes / 쿠버네티스",
                "en_keyword": "kubernetes",
                "ko_keyword": "쿠버네티스",
                "total_frequency": 15,
                "en_frequency": 10,
                "ko_frequency": 5,
                "similarity": 0.92,
            },
            ...
        ]
    """
    en_keywords = [kw for kw in period_keywords if kw.get("language") == "en"]
    ko_keywords = [kw for kw in period_keywords if kw.get("language") == "ko"]

    # Track which en keywords are already paired
    paired_en: set[str] = set()
    clusters: list[dict] = []

    # For each ko keyword, find the best matching en keyword
    for ko_kw in ko_keywords:
        ko_word = ko_kw["keyword"]
        # Fetch embedding from MongoDB
        kw_doc = keywords_col.find_one({"keyword": ko_word}, {"embedding": 1})
        if kw_doc is None or "embedding" not in kw_doc:
            # No embedding — standalone cluster
            clusters.append({
                "topic": ko_word,
                "en_keyword": None,
                "ko_keyword": ko_word,
                "total_frequency": ko_kw["doc_frequency"],
                "en_frequency": 0,
                "ko_frequency": ko_kw["doc_frequency"],
                "similarity": None,
            })
            continue

        match = _find_similar_en_keyword(
            keywords_col, ko_word, kw_doc["embedding"]
        )
        if match and match["keyword"] not in paired_en:
            en_word = match["keyword"]
            paired_en.add(en_word)
            en_freq = next(
                (k["doc_frequency"] for k in en_keywords if k["keyword"] == en_word), 0
            )
            clusters.append({
                "topic": f"{en_word} / {ko_word}",
                "en_keyword": en_word,
                "ko_keyword": ko_word,
                "total_frequency": en_freq + ko_kw["doc_frequency"],
                "en_frequency": en_freq,
                "ko_frequency": ko_kw["doc_frequency"],
                "similarity": match["similarity"],
            })
        else:
            clusters.append({
                "topic": ko_word,
                "en_keyword": None,
                "ko_keyword": ko_word,
                "total_frequency": ko_kw["doc_frequency"],
                "en_frequency": 0,
                "ko_frequency": ko_kw["doc_frequency"],
                "similarity": None,
            })

    # Add unpaired en keywords as standalone clusters
    for en_kw in en_keywords:
        if en_kw["keyword"] not in paired_en:
            clusters.append({
                "topic": en_kw["keyword"],
                "en_keyword": en_kw["keyword"],
                "ko_keyword": None,
                "total_frequency": en_kw["doc_frequency"],
                "en_frequency": en_kw["doc_frequency"],
                "ko_frequency": 0,
                "similarity": None,
            })

    # Sort by total_frequency descending
    clusters.sort(key=lambda c: c["total_frequency"], reverse=True)
    return clusters


def backfill_keyword_embeddings(keywords_col: Collection) -> dict:
    """Generate embeddings for all keywords that don't have one yet."""
    cursor = keywords_col.find(
        {"embedding": {"$exists": False}},
        {"keyword": 1},
    )
    keywords_to_embed = [(doc["_id"], doc["keyword"]) for doc in cursor]

    if not keywords_to_embed:
        return {"processed": 0, "status": "no_keywords_to_embed"}

    batch_size = 100
    total_processed = 0

    for i in range(0, len(keywords_to_embed), batch_size):
        batch = keywords_to_embed[i : i + batch_size]
        texts = [kw for _, kw in batch]
        embeddings = generate_embeddings(texts)

        if not embeddings:
            logger.warning("Failed to generate embeddings for batch %d", i // batch_size)
            continue

        for j, (doc_id, _) in enumerate(batch):
            if j < len(embeddings):
                keywords_col.update_one(
                    {"_id": doc_id},
                    {"$set": {"embedding": embeddings[j]}},
                )
                total_processed += 1

    return {"processed": total_processed, "status": "completed"}
