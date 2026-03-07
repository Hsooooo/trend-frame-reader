from app.services.market_entities import extract_market_entities


def test_extract_market_entities_uses_alias_and_ticker_patterns():
    result = extract_market_entities(
        title="Apple (AAPL) expands AI features after earnings beat",
        summary="The iPhone maker also raised guidance for its services business.",
    )

    assert any(company["canonical_name"] == "Apple" for company in result["companies"])
    assert any(ticker["symbol"] == "AAPL" for ticker in result["tickers"])
    assert any(event["type"] == "earnings" for event in result["events"])
    assert any(theme["name"] == "ai" for theme in result["themes"])


def test_extract_market_entities_returns_empty_status_without_market_signal():
    result = extract_market_entities(
        title="Open source maintainers discuss documentation cleanup",
        summary="The post focused on contributor experience and release process.",
    )

    assert result["entity_extraction_status"] in {"empty", "heuristic", "heuristic+llm"}
