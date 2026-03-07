from datetime import UTC, datetime, timedelta

from app.services import keywords


def test_extract_llm_keywords_skips_timed_out_fallback_temporarily(monkeypatch):
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

    monkeypatch.setattr(keywords, "APITimeoutError", FakeTimeoutError)
    monkeypatch.setattr(keywords, "get_openai_client", lambda: dummy_client)
    monkeypatch.setattr(
        keywords,
        "_LLM_RATE_LIMITED_UNTIL",
        datetime.now(UTC) + timedelta(seconds=30),
    )
    monkeypatch.setattr(keywords, "_FALLBACK_LLM_UNAVAILABLE_UNTIL", None)

    first = keywords._extract_llm_keywords(
        "Apple expands AI features after earnings beat",
        "The iPhone maker also raised guidance for its services business.",
        5,
    )
    second = keywords._extract_llm_keywords(
        "Apple expands AI features after earnings beat",
        "The iPhone maker also raised guidance for its services business.",
        5,
    )

    assert first is None
    assert second is None
    assert dummy_completions.calls == 1
    assert keywords._FALLBACK_LLM_UNAVAILABLE_UNTIL is not None

    monkeypatch.setattr(
        keywords,
        "_LLM_RATE_LIMITED_UNTIL",
        datetime.now(UTC) - timedelta(seconds=1),
    )
    monkeypatch.setattr(keywords, "_FALLBACK_LLM_UNAVAILABLE_UNTIL", None)
