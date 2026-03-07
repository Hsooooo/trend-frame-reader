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


def test_extract_market_entities_accepts_string_confidence_labels(monkeypatch):
    monkeypatch.setattr(
        market_entities,
        "_extract_llm_entities",
        lambda *args, **kwargs: {
            "companies": [{"canonical_name": "Apple", "raw_name": "Apple", "confidence": "high"}],
            "tickers": [{"symbol": "AAPL", "exchange": "NASDAQ", "company_name": "Apple", "confidence": "0.91"}],
            "events": [{"type": "earnings", "label": "earnings update", "sentiment": "neutral", "confidence": "medium"}],
            "themes": [{"name": "ai", "confidence": "low"}],
        },
    )

    result = extract_market_entities(
        title="Apple discusses AI roadmap after earnings",
        summary="Management detailed the product roadmap and market outlook.",
    )

    apple_company = next(company for company in result["companies"] if company["canonical_name"] == "Apple")
    ai_theme = next(theme for theme in result["themes"] if theme["name"] == "ai")
    assert apple_company["confidence"] >= 0.8
    assert ai_theme["confidence"] > 0.0
    assert result["entity_extraction_status"] == "heuristic+llm"


def test_extract_market_entities_skips_timed_out_fallback_temporarily(monkeypatch):
    class FakeTimeoutError(Exception):
        pass

    class DummyCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise FakeTimeoutError("Request timed out.")

    dummy_completions = DummyCompletions()
    dummy_client = type(
        "DummyClient",
        (),
        {"chat": type("DummyChat", (), {"completions": dummy_completions})()},
    )()

    monkeypatch.setattr(market_entities, "APITimeoutError", FakeTimeoutError)
    monkeypatch.setattr(market_entities, "get_openai_client", lambda: dummy_client)
    monkeypatch.setattr(
        market_entities,
        "_LLM_RATE_LIMITED_UNTIL",
        datetime.now(UTC) + timedelta(seconds=30),
    )
    monkeypatch.setattr(market_entities, "_FALLBACK_LLM_UNAVAILABLE_UNTIL", None)

    first = extract_market_entities(
        title="Apple (AAPL) expands AI features after earnings beat",
        summary="The iPhone maker also raised guidance for its services business.",
    )
    second = extract_market_entities(
        title="Apple (AAPL) expands AI features after earnings beat",
        summary="The iPhone maker also raised guidance for its services business.",
    )

    assert any(ticker["symbol"] == "AAPL" for ticker in first["tickers"])
    assert any(ticker["symbol"] == "AAPL" for ticker in second["tickers"])
    assert dummy_completions.calls == 1
    assert market_entities._FALLBACK_LLM_UNAVAILABLE_UNTIL is not None

    monkeypatch.setattr(
        market_entities,
        "_LLM_RATE_LIMITED_UNTIL",
        datetime.now(UTC) - timedelta(seconds=1),
    )
    monkeypatch.setattr(market_entities, "_FALLBACK_LLM_UNAVAILABLE_UNTIL", None)


def test_market_entities_omit_temperature_for_gpt5_models():
    assert market_entities._uses_default_temperature_only("gpt-5-mini") is True
    assert market_entities._uses_default_temperature_only("gpt-4o-mini") is False
