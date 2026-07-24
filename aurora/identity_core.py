from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from urllib.parse import urlparse

from ddgs import DDGS


PERSON_RE = re.compile(
    r"\b([А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}(?:\s+[А-ЯЁ][а-яё-]{1,30}){0,2})\b"
)

SEO_PHONE_DOMAINS = {
    "nachrichtenkrefeld.de",
    "nachrichtenlingen.de",
    "nachrichtendusseldorf.de",
    "nachrichtenosnabruck.de",
    "nachrichtenoldenburg.de",
    "nachrichtenemmerich.de",
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
    "numlookup.com",
    "findwhocallsyou.com",
}

NOISE_WORDS = {
    "telefonnummer",
    "telefonbuch",
    "rückwärtssuche",
    "nummern suchen",
    "spam",
    "кто звонил",
    "мошенники",
    "не бери трубку",
}


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _phone_variants(phone: str) -> list[str]:
    digits = re.sub(r"\D", "", phone)
    variants = [phone]
    if len(digits) == 11 and digits.startswith("7"):
        variants.extend(
            [
                digits,
                "8" + digits[1:],
                f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}",
                f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}",
            ]
        )
    return list(dict.fromkeys(variants))


def _is_noise(url: str, text: str) -> bool:
    host = _domain(url)
    lowered = (text or "").casefold()
    if host in SEO_PHONE_DOMAINS:
        return True
    return sum(1 for word in NOISE_WORDS if word in lowered) >= 2


def _search_phone(phone: str, limit_per_query: int = 6) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    with DDGS(timeout=10) as ddgs:
        for variant in _phone_variants(phone):
            queries = [f'"{variant}"', f'"{variant}" имя', f'"{variant}" ФИО']
            for query in queries:
                try:
                    found = list(ddgs.text(query, max_results=limit_per_query) or [])
                except Exception:
                    continue
                for item in found:
                    url = str(item.get("href") or item.get("url") or "")
                    title = str(item.get("title") or "")
                    excerpt = str(item.get("body") or item.get("snippet") or "")
                    text = f"{title} {excerpt}".strip()
                    key = hashlib.sha256(f"{url}|{text}".encode()).hexdigest()
                    if not url or key in seen or _is_noise(url, text):
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "id": f"ev_identity_{key[:12]}",
                            "source": "identity_web_search",
                            "source_url": url,
                            "source_type": "search_result",
                            "title": title,
                            "excerpt": excerpt[:700],
                            "reliability": 0.58,
                            "direct_match": any(v.casefold() in text.casefold() for v in _phone_variants(phone)),
                            "content_hash": key,
                        }
                    )
    return rows


def _extract_person_candidates(phone: str, evidence: list[dict]) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    rejected: list[dict] = []
    variants = [v.casefold() for v in _phone_variants(phone)]

    for ev in evidence:
        text = f"{ev.get('title', '')} {ev.get('excerpt', '')}"
        if not any(v in text.casefold() for v in variants):
            continue
        for name in PERSON_RE.findall(text):
            normalized = " ".join(name.split()).casefold()
            grouped[normalized].append(ev)

    entities: list[dict] = []
    for normalized, items in grouped.items():
        domains = {_domain(item.get("source_url", "")) for item in items if _domain(item.get("source_url", ""))}
        display_name = " ".join(items[0].get("excerpt", "").split())
        match = PERSON_RE.search(display_name)
        value = match.group(1) if match else normalized.title()

        if len(domains) < 2:
            rejected.append(
                {
                    "value": value,
                    "kind": "person",
                    "reason": "только один независимый веб-источник",
                    "source_url": items[0].get("source_url", ""),
                    "context": items[0].get("excerpt", "")[:250],
                }
            )
            continue

        score = min(88, 58 + (len(domains) - 1) * 12)
        entities.append(
            {
                "id": f"person_{hashlib.sha1(normalized.encode()).hexdigest()[:10]}",
                "type": "person",
                "claims": [
                    {
                        "field": "fio_candidate",
                        "value": value,
                        "normalized_value": normalized,
                        "confidence": score,
                        "verification_status": "Вероятно" if score < 80 else "Высокая вероятность",
                        "source_count": len(items),
                        "independent_source_count": len(domains),
                        "evidence_ids": [item["id"] for item in items],
                        "extraction_method": "multi_query_context_resolution",
                        "reasoning_summary": f"Имя найдено рядом с номером в {len(domains)} независимых доменах; требуется ручная проверка первоисточников.",
                        "confidence_breakdown": {
                            "base_score": 46,
                            "independent_confirmation": min(30, len(domains) * 10),
                            "context_strength": 12,
                            "final_score": score,
                        },
                    }
                ],
            }
        )
    return entities, rejected


def enrich_phone_case(case: dict) -> dict:
    inp = case.get("input", {})
    if inp.get("type") != "phone":
        return case

    phone = inp.get("normalized") or inp.get("raw") or ""
    original = case.get("evidence", [])
    clean_original = [
        ev
        for ev in original
        if not _is_noise(ev.get("source_url", ""), f"{ev.get('title', '')} {ev.get('excerpt', '')}")
    ]
    supplemental = _search_phone(phone)
    evidence = clean_original + supplemental

    person_entities, rejected = _extract_person_candidates(phone, evidence)
    case["evidence"] = evidence
    case.setdefault("entities", []).extend(person_entities)
    case.setdefault("rejected_candidates", []).extend(rejected)

    if person_entities:
        best = max(
            person_entities,
            key=lambda entity: entity["claims"][0].get("confidence", 0),
        )["claims"][0]
        case.setdefault("summary", {})["fio"] = f"кандидат: {best['value']} ({best['confidence']}%)"
        case["summary"]["headline"] = (
            "Найдены обоснованные кандидаты по открытым источникам. Это гипотезы, а не установленная личность; проверьте ссылки и контекст."
        )
    else:
        case.setdefault("summary", {})["fio"] = "не подтверждено"
        case["summary"]["headline"] = (
            "Надёжная связь номера с ФИО в открытых источниках не подтверждена. SEO-каталоги и шаблонные совпадения удалены."
        )

    case["summary"]["identity_core"] = {
        "query_variants": _phone_variants(phone),
        "supplemental_evidence": len(supplemental),
        "filtered_noise": len(original) - len(clean_original),
        "person_candidates": len(person_entities),
    }
    return case
