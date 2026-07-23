from __future__ import annotations

import json
import re
from pathlib import Path

# Каталоги обратного поиска номера полезны только как технические кандидаты.
# Они не являются доказательством ФИО, адреса или принадлежности номера.
LOW_TRUST_PHONE_DOMAINS = {
    "spam-nomera.ru",
    "apk-shatura.ru",
    "xn--90aakbpnp1abtmc.xn--p1ai",
    "baza-nomerov.com",
    "centerica.ru",
    "kodtelefona.ru",
    "mobile-monitor.ru",
    "phoneradar.ru",
    "region-operator.ru",
    "spravochnik.tel",
    "who-call.me",
    "zvonok24.ru",
    "numbase.ru",
    "nomercheck.ru",
}

UI_WORDS = {
    "поиск", "главная", "варианты", "номер", "телефон", "мобильный",
    "реклама", "опросы", "инфо", "группа", "ремонт", "техника",
    "отзывы", "комментарии", "оператор", "регион", "область", "страница",
    "контакты", "информация", "анализ", "проверить", "звонок", "сайт",
}

ADDRESS_MARKERS = re.compile(
    r"\b(?:ул\.?|улица|проспект|пр-т|переулок|пер\.?|шоссе|набережная|наб\.?|"
    r"бульвар|б-р|дом|д\.|корпус|корп\.|строение|стр\.)\s+[А-ЯЁA-Z0-9]",
    re.I,
)
HOUSE_NUMBER = re.compile(r"\b(?:д(?:ом)?\.?\s*)?\d{1,4}[А-ЯA-Zа-яё]?\b", re.I)
PERSON_SHAPE = re.compile(
    r"^[А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}(?:\s+[А-ЯЁ][а-яё-]{1,30})?$"
)


def _words(value: str) -> list[str]:
    return [part.casefold() for part in re.findall(r"[А-ЯЁа-яё-]+", value)]


def valid_person(value: str, sources: list[dict]) -> bool:
    value = re.sub(r"\s+", " ", value).strip()
    if not PERSON_SHAPE.fullmatch(value):
        return False

    words = _words(value)
    if len(words) not in {2, 3}:
        return False
    if any(word in UI_WORDS for word in words):
        return False

    # ФИО из телефонного каталога без независимого источника не принимаем.
    trusted_sources = [
        source for source in sources
        if str(source.get("domain", "")).casefold() not in LOW_TRUST_PHONE_DOMAINS
    ]
    return bool(trusted_sources)


def valid_address(value: str, sources: list[dict]) -> bool:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) < 12 or len(value) > 160:
        return False
    if not ADDRESS_MARKERS.search(value) or not HOUSE_NUMBER.search(value):
        return False
    if any(str(source.get("domain", "")).casefold() in LOW_TRUST_PHONE_DOMAINS for source in sources):
        return False
    return True


def clean_findings(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    rejected: list[dict] = []

    for item in findings:
        kind = item.get("kind")
        value = str(item.get("value", ""))
        sources = item.get("sources", []) or []

        accepted = True
        reason = ""
        if kind == "person" and not valid_person(value, sources):
            accepted = False
            reason = "not a credible person name"
        elif kind == "public_address" and not valid_address(value, sources):
            accepted = False
            reason = "not a complete credible address"

        if accepted:
            kept.append(item)
        else:
            rejected.append({**item, "rejection_reason": reason})

    return kept, rejected


def clean_search_result(result: dict, output_dir: Path) -> dict:
    cleaned, rejected = clean_findings(result.get("findings", []))
    result = {**result, "findings": cleaned, "finding_count": len(cleaned)}
    result["quality_filter"] = {
        "rejected_count": len(rejected),
        "rejected": rejected,
    }

    # Перезаписываем структурированные результаты уже после контроля качества.
    (output_dir / "web_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "findings.json").write_text(
        json.dumps(
            {
                "phone": result.get("phone"),
                "findings": cleaned,
                "candidates": result.get("candidates", []),
                "rejected_false_positives": rejected,
                "warning": result.get("warning"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result
