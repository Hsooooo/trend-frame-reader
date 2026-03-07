from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta

try:
    from openai import RateLimitError
except ImportError:  # pragma: no cover - local test environments may not have openai installed
    class RateLimitError(Exception):
        pass

from app.config import settings
from app.services.openai_client import get_openai_client

logger = logging.getLogger(__name__)
MARKET_EXTRACTION_VERSION = "market-v1"

_COMPANY_MASTER: list[dict[str, object]] = [
    {"canonical_name": "Apple", "ticker": "AAPL", "exchange": "NASDAQ", "aliases": ["apple", "apple inc", "apple inc."]},
    {"canonical_name": "Microsoft", "ticker": "MSFT", "exchange": "NASDAQ", "aliases": ["microsoft", "microsoft corp", "microsoft corporation"]},
    {"canonical_name": "NVIDIA", "ticker": "NVDA", "exchange": "NASDAQ", "aliases": ["nvidia", "nvidia corp", "nvidia corporation"]},
    {"canonical_name": "Amazon", "ticker": "AMZN", "exchange": "NASDAQ", "aliases": ["amazon", "amazon.com", "amazon com", "amazon.com inc"]},
    {"canonical_name": "Meta Platforms", "ticker": "META", "exchange": "NASDAQ", "aliases": ["meta", "meta platforms", "facebook", "facebook parent"]},
    {"canonical_name": "Alphabet", "ticker": "GOOGL", "exchange": "NASDAQ", "aliases": ["alphabet", "google", "google parent"]},
    {"canonical_name": "Tesla", "ticker": "TSLA", "exchange": "NASDAQ", "aliases": ["tesla", "tesla inc", "tesla motors"]},
    {"canonical_name": "Advanced Micro Devices", "ticker": "AMD", "exchange": "NASDAQ", "aliases": ["amd", "advanced micro devices"]},
    {"canonical_name": "Broadcom", "ticker": "AVGO", "exchange": "NASDAQ", "aliases": ["broadcom", "broadcom inc"]},
    {"canonical_name": "Netflix", "ticker": "NFLX", "exchange": "NASDAQ", "aliases": ["netflix", "netflix inc"]},
    {"canonical_name": "Palantir Technologies", "ticker": "PLTR", "exchange": "NASDAQ", "aliases": ["palantir", "palantir technologies"]},
    {"canonical_name": "Salesforce", "ticker": "CRM", "exchange": "NYSE", "aliases": ["salesforce", "salesforce inc"]},
    {"canonical_name": "Oracle", "ticker": "ORCL", "exchange": "NYSE", "aliases": ["oracle", "oracle corp", "oracle corporation"]},
    {"canonical_name": "Intel", "ticker": "INTC", "exchange": "NASDAQ", "aliases": ["intel", "intel corp", "intel corporation"]},
    {"canonical_name": "Qualcomm", "ticker": "QCOM", "exchange": "NASDAQ", "aliases": ["qualcomm", "qualcomm inc"]},
    {"canonical_name": "Micron Technology", "ticker": "MU", "exchange": "NASDAQ", "aliases": ["micron", "micron technology"]},
    {"canonical_name": "Taiwan Semiconductor Manufacturing", "ticker": "TSM", "exchange": "NYSE", "aliases": ["tsmc", "taiwan semiconductor", "taiwan semiconductor manufacturing"]},
    {"canonical_name": "Super Micro Computer", "ticker": "SMCI", "exchange": "NASDAQ", "aliases": ["super micro", "super micro computer", "smci"]},
    {"canonical_name": "Uber Technologies", "ticker": "UBER", "exchange": "NYSE", "aliases": ["uber", "uber technologies"]},
    {"canonical_name": "Snowflake", "ticker": "SNOW", "exchange": "NYSE", "aliases": ["snowflake", "snowflake inc"]},
]

_TICKER_MASTER = {str(row["ticker"]).upper(): row for row in _COMPANY_MASTER}

_EVENT_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (re.compile(r"\bearnings\b|\bquarterly results\b|\brevenue\b|\bprofit\b", re.I), "earnings", "earnings update", "neutral"),
    (re.compile(r"\bguidance\b|\bforecast\b|\boutlook\b", re.I), "guidance", "guidance update", "neutral"),
    (re.compile(r"\bmerger\b|\bacquisition\b|\bacquire\b|\bdeal\b", re.I), "merger_acquisition", "merger or acquisition", "positive"),
    (re.compile(r"\bpartnership\b|\bpartnered\b|\bcollaboration\b", re.I), "partnership", "partnership or collaboration", "positive"),
    (re.compile(r"\blaunch\b|\bunveil\b|\brelease\b", re.I), "product_launch", "product or platform launch", "positive"),
    (re.compile(r"\blawsuit\b|\bsued\b|\blegal\b|\bcourt\b", re.I), "lawsuit", "legal or lawsuit event", "negative"),
    (re.compile(r"\bupgrade\b|\bdowngrade\b|\bprice target\b|\banalyst\b", re.I), "analyst_action", "analyst action", "neutral"),
    (re.compile(r"\bregulator\b|\bregulation\b|\bantitrust\b|\bprobe\b|\binvestigation\b", re.I), "regulation", "regulatory event", "negative"),
    (re.compile(r"\bsupply chain\b|\bmanufacturing\b|\bcapacity\b", re.I), "supply_chain", "supply chain update", "neutral"),
    (re.compile(r"\bceo\b|\bcfo\b|\bexecutive\b|\bresign\b|\bappointment\b", re.I), "executive_change", "executive change", "neutral"),
]

_THEME_PATTERNS: dict[str, re.Pattern[str]] = {
    "ai": re.compile(r"\bartificial intelligence\b|\bai\b|\bgenerative ai\b|\bllm\b|\bmodel\b", re.I),
    "semiconductors": re.compile(r"\bsemiconductor\b|\bchip\b|\bgpu\b|\bfoundry\b|\bhbm\b", re.I),
    "cloud": re.compile(r"\bcloud\b|\bdata center\b|\bsaas\b", re.I),
    "cybersecurity": re.compile(r"\bcybersecurity\b|\bsecurity\b|\bbreach\b|\bmalware\b", re.I),
    "consumer": re.compile(r"\bconsumer\b|\bretail\b|\be-commerce\b", re.I),
    "biotech": re.compile(r"\bbiotech\b|\bdrug\b|\bclinical\b|\btrial\b|\bfda\b", re.I),
    "ev": re.compile(r"\bev\b|\belectric vehicle\b|\bbattery\b|\bautonomous\b", re.I),
    "energy": re.compile(r"\boil\b|\bgas\b|\benergy\b|\bsolar\b|\bpower\b", re.I),
    "fintech": re.compile(r"\bpayments\b|\bfintech\b|\bdigital bank\b|\bcrypto\b", re.I),
    "defense": re.compile(r"\bdefense\b|\bmilitary\b|\bmissile\b|\bweapon\b", re.I),
}

_LLM_RATE_LIMITED_UNTIL: datetime | None = None


class MarketEntityRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(f"market_entity_rate_limited:{self.retry_after_seconds:.2f}")


def _unique_by(rows: list[dict], key: str) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in rows:
        raw_key = str(row.get(key, "")).strip()
        if not raw_key:
            continue
        existing = merged.get(raw_key)
        if existing is None:
            merged[raw_key] = row
            continue
        if float(row.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
            merged[raw_key] = row
    return list(merged.values())


def _extract_known_tickers(text: str) -> set[str]:
    candidates: set[str] = set()
    patterns = [
        r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b",
        r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)",
        r"\b(?:NASDAQ|NYSE|AMEX):\s*([A-Z]{1,5}(?:\.[A-Z])?)\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            ticker = match.upper().strip()
            if ticker in _TICKER_MASTER:
                candidates.add(ticker)
    return candidates


def _extract_from_master(text: str) -> tuple[list[dict], list[dict]]:
    companies: list[dict] = []
    tickers: list[dict] = []
    lowered = text.lower()
    explicit_tickers = _extract_known_tickers(text)

    for entry in _COMPANY_MASTER:
        aliases = [str(alias).lower() for alias in entry["aliases"]]
        matched_alias = next(
            (alias for alias in aliases if re.search(rf"\b{re.escape(alias)}\b", lowered)),
            None,
        )
        ticker = str(entry["ticker"]).upper()
        if matched_alias or ticker in explicit_tickers:
            confidence = 0.9 if ticker in explicit_tickers else 0.72
            companies.append(
                {
                    "canonical_name": entry["canonical_name"],
                    "raw_name": matched_alias or entry["canonical_name"],
                    "confidence": round(confidence, 2),
                }
            )
            tickers.append(
                {
                    "symbol": ticker,
                    "exchange": entry["exchange"],
                    "company_name": entry["canonical_name"],
                    "confidence": round(max(confidence, 0.75), 2),
                    "source": "heuristic",
                }
            )

    for ticker in explicit_tickers:
        entry = _TICKER_MASTER[ticker]
        if not any(company.get("canonical_name") == entry["canonical_name"] for company in companies):
            companies.append(
                {
                    "canonical_name": entry["canonical_name"],
                    "raw_name": entry["canonical_name"],
                    "confidence": 0.9,
                }
            )
        if not any(item.get("symbol") == ticker for item in tickers):
            tickers.append(
                {
                    "symbol": ticker,
                    "exchange": entry["exchange"],
                    "company_name": entry["canonical_name"],
                    "confidence": 0.95,
                    "source": "heuristic",
                }
            )

    return _unique_by(companies, "canonical_name"), _unique_by(tickers, "symbol")


def _extract_events(text: str) -> list[dict]:
    events: list[dict] = []
    for pattern, event_type, label, sentiment in _EVENT_PATTERNS:
        if pattern.search(text):
            events.append(
                {
                    "type": event_type,
                    "label": label,
                    "sentiment": sentiment,
                    "confidence": 0.65,
                }
            )
    return _unique_by(events, "type")


def _extract_themes(text: str) -> list[dict]:
    themes: list[dict] = []
    for theme_name, pattern in _THEME_PATTERNS.items():
        if pattern.search(text):
            themes.append({"name": theme_name, "confidence": 0.62})
    return _unique_by(themes, "name")


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _parse_retry_after_seconds(message: str) -> float | None:
    match = re.search(r"Please try again in\s+([0-9]+(?:\.[0-9]+)?)s", message, re.I)
    if match is None:
        return None
    try:
        return max(0.0, float(match.group(1)))
    except ValueError:
        return None


def _extract_llm_entities(
    title: str,
    summary: str | None,
    *,
    raise_on_rate_limit: bool = False,
) -> dict | None:
    global _LLM_RATE_LIMITED_UNTIL

    client = get_openai_client()
    if client is None:
        return None

    if _LLM_RATE_LIMITED_UNTIL is not None and datetime.now(UTC) < _LLM_RATE_LIMITED_UNTIL:
        retry_after = (_LLM_RATE_LIMITED_UNTIL - datetime.now(UTC)).total_seconds()
        if raise_on_rate_limit:
            raise MarketEntityRateLimitedError(retry_after)
        return None

    summary_part = f"\nSummary: {summary.strip()}" if summary and summary.strip() else ""
    prompt = (
        "Extract market entities from the article below.\n"
        "Return only JSON with keys companies, tickers, events, themes.\n"
        "Each company item must have canonical_name, raw_name, confidence.\n"
        "Each ticker item must have symbol, exchange, company_name, confidence, source.\n"
        "Each event item must have type, label, sentiment, confidence.\n"
        "Each theme item must have name, confidence.\n"
        "Focus on publicly traded U.S. companies and only include items directly supported by the text.\n"
        f"\nTitle: {title.strip()}{summary_part}"
    )

    try:
        response = client.chat.completions.create(
            model=settings.openai_market_entity_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract market entities from financial news.\n"
                        "Return JSON only. Never include markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            timeout=settings.openai_timeout_seconds,
        )
        raw = _strip_code_fences(response.choices[0].message.content or "")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        return payload
    except RateLimitError as exc:
        retry_after = _parse_retry_after_seconds(str(exc)) or 60.0
        _LLM_RATE_LIMITED_UNTIL = datetime.now(UTC) + timedelta(seconds=retry_after)
        logger.warning(
            "LLM market entity extraction rate-limited; using heuristic only for %.2fs",
            retry_after,
        )
        if raise_on_rate_limit:
            raise MarketEntityRateLimitedError(retry_after) from exc
        return None
    except Exception:
        logger.warning("LLM market entity extraction failed", exc_info=True)
        return None


def _normalize_llm_rows(rows: object, kind: str) -> list[dict]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if kind == "companies":
            name = str(row.get("canonical_name", "")).strip()
            if not name:
                continue
            normalized.append(
                {
                    "canonical_name": name,
                    "raw_name": str(row.get("raw_name", name)).strip() or name,
                    "confidence": float(row.get("confidence", 0.6)),
                }
            )
        elif kind == "tickers":
            symbol = str(row.get("symbol", "")).upper().strip()
            if not re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", symbol):
                continue
            normalized.append(
                {
                    "symbol": symbol,
                    "exchange": str(row.get("exchange", "")).upper().strip() or None,
                    "company_name": str(row.get("company_name", "")).strip() or symbol,
                    "confidence": float(row.get("confidence", 0.6)),
                    "source": str(row.get("source", "llm")).strip() or "llm",
                }
            )
        elif kind == "events":
            event_type = str(row.get("type", "")).strip()
            if not event_type:
                continue
            normalized.append(
                {
                    "type": event_type,
                    "label": str(row.get("label", event_type)).strip() or event_type,
                    "sentiment": str(row.get("sentiment", "neutral")).strip() or "neutral",
                    "confidence": float(row.get("confidence", 0.6)),
                }
            )
        elif kind == "themes":
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            normalized.append({"name": name, "confidence": float(row.get("confidence", 0.6))})
    key_map = {
        "companies": "canonical_name",
        "tickers": "symbol",
        "events": "type",
        "themes": "name",
    }
    return _unique_by(normalized, key_map[kind])


def extract_market_entities(
    title: str,
    summary: str | None = None,
    *,
    raise_on_rate_limit: bool = False,
) -> dict:
    text = "\n".join(part for part in [title.strip(), (summary or "").strip()] if part)
    companies, tickers = _extract_from_master(text)
    events = _extract_events(text)
    themes = _extract_themes(text)

    status = "heuristic"
    llm_payload = _extract_llm_entities(
        title,
        summary,
        raise_on_rate_limit=raise_on_rate_limit,
    )
    if llm_payload:
        companies = _unique_by(companies + _normalize_llm_rows(llm_payload.get("companies"), "companies"), "canonical_name")
        tickers = _unique_by(tickers + _normalize_llm_rows(llm_payload.get("tickers"), "tickers"), "symbol")
        events = _unique_by(events + _normalize_llm_rows(llm_payload.get("events"), "events"), "type")
        themes = _unique_by(themes + _normalize_llm_rows(llm_payload.get("themes"), "themes"), "name")
        status = "heuristic+llm"

    confidence_values = [
        float(row.get("confidence", 0.0))
        for bucket in (companies, tickers, events, themes)
        for row in bucket
    ]
    if not confidence_values:
        status = "empty"

    return {
        "companies": companies,
        "tickers": tickers,
        "events": events,
        "themes": themes,
        "entity_extraction_status": status,
        "extraction_version": MARKET_EXTRACTION_VERSION,
        "extraction_confidence": round(max(confidence_values), 2) if confidence_values else 0.0,
    }
