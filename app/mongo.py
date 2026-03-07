import logging

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

from app.config import settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None


def get_mongo_client() -> MongoClient | None:
    global _client
    if not settings.mongodb_uri:
        return None
    if _client is None:
        _client = MongoClient(settings.mongodb_uri)
        logger.info("MongoDB client initialized")
    return _client


def get_mongo_db() -> Database | None:
    client = get_mongo_client()
    if client is None:
        return None
    return client[settings.mongodb_database]


def get_articles_collection() -> Collection | None:
    db = get_mongo_db()
    return db["articles"] if db is not None else None


def get_keywords_collection() -> Collection | None:
    db = get_mongo_db()
    return db["keywords"] if db is not None else None


def get_graph_sync_log_collection() -> Collection | None:
    db = get_mongo_db()
    return db["graph_sync_log"] if db is not None else None


def get_market_articles_collection() -> Collection | None:
    db = get_mongo_db()
    return db["market_articles"] if db is not None else None


def close_mongo_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("MongoDB client closed")


def ensure_indexes() -> None:
    db = get_mongo_db()
    if db is None:
        return

    db["articles"].create_index([("item_id", ASCENDING)], unique=True)
    logger.info("MongoDB index ensured: articles.item_id (unique)")

    db["keywords"].create_index([("keyword", ASCENDING)], unique=True)
    logger.info("MongoDB index ensured: keywords.keyword (unique)")

    db["market_articles"].create_index([("item_id", ASCENDING)], unique=True)
    db["market_articles"].create_index([("tickers.symbol", ASCENDING)])
    db["market_articles"].create_index([("companies.canonical_name", ASCENDING)])
    db["market_articles"].create_index([("events.type", ASCENDING)])
    db["market_articles"].create_index([("themes.name", ASCENDING)])
    logger.info("MongoDB indexes ensured: market_articles item/entity indexes")
