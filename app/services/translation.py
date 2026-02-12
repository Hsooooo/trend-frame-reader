from __future__ import annotations

import httpx

from app.config import settings


def translate_title_to_korean(title: str) -> str | None:
    api_key = settings.deepl_api_key.strip()
    if not api_key:
        return None

    headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
    payload = {"text": [title], "target_lang": "KO"}
    attempts = max(1, settings.deepl_retries + 1)

    for _ in range(attempts):
        try:
            response = httpx.post(
                settings.deepl_api_url,
                headers=headers,
                data=payload,
                timeout=settings.deepl_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            translations = data.get("translations", [])
            if not translations:
                return None
            text = translations[0].get("text")
            if not text:
                return None
            return str(text)
        except Exception:
            continue

    return None
