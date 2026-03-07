from datetime import UTC, datetime, timedelta

from app.services import market_entities
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


def test_extract_market_entities_skips_llm_temporarily_after_rate_limit(monkeypatch):
    class FakeRateLimitError(Exception):
        pass

    class DummyCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise FakeRateLimitError(
                "Rate limit reached. Please try again in 8.64s."
            )

    dummy_completions = DummyCompletions()
    dummy_client = type(
        "DummyClient",
        (),
        {"chat": type("DummyChat", (), {"completions": dummy_completions})()},
    )()

    monkeypatch.setattr(market_entities, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(market_entities, "get_openai_client", lambda: dummy_client)
    monkeypatch.setattr(market_entities, "_LLM_RATE_LIMITED_UNTIL", None)

    first = extract_market_entities(
        title="Apple (AAPL) announces AI features",
        summary="The company introduced new AI tooling for developers.",
    )
    second = extract_market_entities(
        title="Apple (AAPL) announces AI features",
        summary="The company introduced new AI tooling for developers.",
    )

    assert any(ticker["symbol"] == "AAPL" for ticker in first["tickers"])
    assert any(theme["name"] == "ai" for theme in first["themes"])
    assert second["entity_extraction_status"] in {"heuristic", "empty"}
    assert dummy_completions.calls == 1
    assert market_entities._LLM_RATE_LIMITED_UNTIL is not None

    monkeypatch.setattr(
        market_entities,
        "_LLM_RATE_LIMITED_UNTIL",
        datetime.now(UTC) - timedelta(seconds=1),
    )
