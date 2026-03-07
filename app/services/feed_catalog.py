STOCK_FEED_CATEGORIES = frozenset({
    "us-stock-news",
    "us-stock-filings",
})


def is_stock_feed_category(category: str | None) -> bool:
    return bool(category) and category in STOCK_FEED_CATEGORIES
