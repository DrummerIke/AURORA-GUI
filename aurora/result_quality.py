from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urlparse

from ddgs import DDGS

LOW_SIGNAL_PHONE_DOMAINS = {
    "xn--90aakbpnp1abtmc.xn--p1ai",  # неберитрубку.рф
    "zvonili-spam.com",
    "kto-zvonil-mne.ru",
    "secab.ru",
    "smzka.ru",
    "931.xn--p1ai",
    "xn----ftbb5asafy9f.xn--p1ai",
    "apk-shatura.ru",
    "spam-nomera.ru",
    "ss1.ru",
    "hulstcustoms.ru",
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
    "truecaller.com",
    "numlookup.com",
    "findwhocallsyou.com",
    "robokiller.com",
    "numtrace.com",
    "thisnumber.com",
    "tellows.com",
    "411.com",
}

LOW_SIGNAL_MARKERS = {
    "кто звонил",
    "чей номер",
    "отзывы о номере",
    "номер и регион",
    "проверить номер",
    "reverse phone lookup",
    "who called me",
    "unknown caller",
    "spam phone",
}

HIGH_SIGNAL_DOMAINS = {
    "vk.com",
    "ok.ru",
    "t.me",
    "telegram.me",
    "avito.ru",
    "youla.ru",
    "rusprofile.ru",
    "2gis.ru",
    "hh.ru",
    "github.com",
    "linkedin.com",
}

TARGETED_SITES = [
    "vk.com",
    "ok.ru",
    "t.me",
    "avito.ru",
    "youla.ru",
    "rusprofile.ru",
    "2gis.ru",
    "hh.ru",
    "github.com",
]


def _domain(url: str) -> str:
    return (urlparse(url or "").hostname or "").casefold().removeprefix("www.")


def _digits(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def phone_variants(phone: str) -> list[str]:
    digits = _digits(phone)
    variants = [phone]
    if len(digits) == 11 and digits.startswith("7"):
        national = digits[1:]
        variants.extend(
            [
                digits,
                "8" + national,
                f"+7 ({national[:3]}) {national[3:6]}-{national[6:8]}-{national[8:]}",
            ]
        )
    return list(dict.fromkeys(v for v in variants if v))


def is_low_signal(url: str, title: str = "", excerpt: str = "") -> bool:
    host = _domain(url)
    if host in LOW_SIGNAL_PHONE_DOMAINS:
        return True
    text = f"{title} {excerpt}".casefold()
    hits = sum(1 for marker in LOW_SIGNAL_MARKERS if marker in text)
    return hits >= 2


def evidence_quality(item: dict) -> str:
    host = _domain(str(item.get("source_url") or ""))
    if is_low_signal(
        str(item.get("source_url") or ""),
        str(item.get("title") or ""),
        str(item.get("excerpt") or ""),
    ):
        return "low"
    if host in HIGH_SIGNAL_DOMAINS:
        return "high"
    if item.get("source_type") == "public_page" and item.get("direct_match"):
        return "medium"
    return "unknown"


def _search_rows(phone: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    max_results = int(os.getenv("AURORA_TARGETED_RESULTS_PER_QUERY", "4"))
    variants = phone_variants(phone)
    queries: list[str] = []
    for variant in variants[:3]:
        for site in TARGETED_SITES:
            queries.append(f'"{variant}" site:{site}')
        queries.append(f'"{variant}" filetype:pdf')
        queries.append(f'"{variant}" контакты')
        queries.append(f'"{variant}" организация')

    with DDGS(timeout=10) as ddgs:
        for query in queries:
            try:
                found = list(ddgs.text(query, max_results=max_results) or [])
            except Exception:
                continue
            for result in found:
                url = str(result.get("href") or result.get("url") or "")
                title = str(result.get("title") or "")
                excerpt = str(result.get("body") or result.get("snippet") or "")
                if not url or is_low_signal(url, title, excerpt):
                    continue
                key = hashlib.sha256(f"{url}|{title}|{excerpt}".encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                host = _domain(url)
                rows.append(
                    {
                        "id": f"ev_targeted_{key[:12]}",
                        "source": "targeted_public_search",
                        "source_url": url,
                        "source_type": "search_result",
                        "title": title,
                        "excerpt": excerpt[:900],
                        "reliability": 0.72 if host in HIGH_SIGNAL_DOMAINS else 0.60,
                        "direct_match": any(
                            variant.casefold() in f"{title} {excerpt}".casefold()
                            for variant in variants
                        ),
                        "content_hash": key,
                        "metadata": {
                            "source_quality": "high" if host in HIGH_SIGNAL_DOMAINS else "medium",
                            "query": query,
                        },
                    }
                )
    return rows


def enrich_targeted_search(case: dict) -> dict:
    inp = case.get("input", {})
    if inp.get("type") != "phone":
        return case
    phone = inp.get("normalized") or inp.get("raw") or ""
    rows = _search_rows(phone)
    existing = {
        item.get("content_hash") or item.get("id")
        for item in case.get("evidence", [])
    }
    case.setdefault("evidence", []).extend(
        row for row in rows if (row.get("content_hash") or row.get("id")) not in existing
    )
    case.setdefault("connector_runs", []).append(
        {
            "connector_id": "targeted_public_search",
            "status": "OK",
            "started_at": "",
            "completed_at": "",
            "duration_ms": 0,
            "entities": [],
            "evidence": rows,
            "warnings": [],
            "errors": [],
            "raw_reference": None,
            "metadata": {
                "results": len(rows),
                "high_signal_results": sum(
                    1 for row in rows if evidence_quality(row) == "high"
                ),
            },
        }
    )
    case.setdefault("summary", {})["targeted_search"] = {
        "results": len(rows),
        "high_signal_results": sum(
            1 for row in rows if evidence_quality(row) == "high"
        ),
    }
    return case


def filter_low_value_results(case: dict) -> dict:
    original = list(case.get("evidence", []))
    kept = [item for item in original if evidence_quality(item) != "low"]
    kept_ids = {item.get("id") for item in kept if item.get("id")}

    filtered_entities: list[dict] = []
    removed_entities = 0
    for entity in case.get("entities", []):
        if entity.get("id") == "entity_input":
            filtered_entities.append(entity)
            continue
        claims = entity.get("claims") or []
        valid_claims = []
        for claim in claims:
            evidence_ids = set(claim.get("evidence_ids") or [])
            method = str(claim.get("extraction_method") or "")
            if method in {"input_normalizer", "user_context_correlation"}:
                valid_claims.append(claim)
                continue
            if evidence_ids and evidence_ids & kept_ids:
                valid_claims.append(claim)
        if valid_claims:
            copied = dict(entity)
            copied["claims"] = valid_claims
            filtered_entities.append(copied)
        else:
            removed_entities += 1

    case["evidence"] = kept
    case["entities"] = filtered_entities

    summary = case.setdefault("summary", {})
    quality = summary.setdefault("quality_filter", {})
    quality["suppressed_low_signal_evidence"] = (
        quality.get("suppressed_low_signal_evidence", 0) + len(original) - len(kept)
    )
    quality["suppressed_orphan_entities"] = (
        quality.get("suppressed_orphan_entities", 0) + removed_entities
    )

    useful = [
        entity
        for entity in filtered_entities
        if entity.get("type") in {"person", "email", "organization", "username"}
    ]
    summary["useful_entity_count"] = len(useful)
    if not useful and not summary.get("context_verification"):
        summary["headline"] = (
            "По открытым источникам полезная связь номера с человеком, email, "
            "профилем или организацией не подтверждена. Каталоги «кто звонил» "
            "и похожий SEO-шум скрыты из результата."
        )
        summary["fio"] = "не найдено в качественных публичных источниках"
        if str(summary.get("email", "")).startswith("не подтверж"):
            summary["email"] = "не найден в качественных публичных источниках"
    return case
