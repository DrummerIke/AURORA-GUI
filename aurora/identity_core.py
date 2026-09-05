from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from urllib.parse import urlparse

from ddgs import DDGS

PERSON_RE = re.compile(
    r"\b([А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}"
    r"(?:\s+[А-ЯЁ][а-яё-]{1,30}){0,2})\b"
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
CONTEXT_FIELD_META = {
    "name": ("person", "fio_context", "ФИО"),
    "username": ("username", "username_context", "Username"),
    "city": ("location", "city_context", "Город"),
    "company": ("organization", "company_context", "Компания"),
}


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _normalize_context_value(key: str, value: str) -> str:
    normalized = _normalize_text(value)
    if key == "username":
        normalized = normalized.lstrip("@")
    return normalized


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
    return list(dict.fromkeys(v for v in variants if v))


def _is_noise(url: str, text: str) -> bool:
    host = _domain(url)
    lowered = (text or "").casefold()
    if host in SEO_PHONE_DOMAINS:
        return True
    return sum(1 for word in NOISE_WORDS if word in lowered) >= 2


def _search_queries(
    queries: list[str], phone: str, limit_per_query: int = 6
) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    variants = _phone_variants(phone)
    with DDGS(timeout=10) as ddgs:
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
                        "direct_match": any(
                            v.casefold() in text.casefold() for v in variants
                        ),
                        "content_hash": key,
                    }
                )
    return rows


def _search_phone(phone: str) -> list[dict]:
    queries: list[str] = []
    for variant in _phone_variants(phone):
        queries.extend([f'"{variant}"', f'"{variant}" имя', f'"{variant}" ФИО'])
    return _search_queries(list(dict.fromkeys(queries)), phone)


def _search_context(phone: str, context: dict) -> list[dict]:
    queries: list[str] = []
    values = [
        v.strip()
        for v in context.values()
        if isinstance(v, str) and v.strip()
    ]
    for variant in _phone_variants(phone):
        for value in values:
            queries.append(f'"{variant}" "{value}"')

    name = context.get("name", "").strip()
    username = context.get("username", "").strip().lstrip("@")
    city = context.get("city", "").strip()
    company = context.get("company", "").strip()
    if name and username:
        queries.append(f'"{name}" "{username}"')
    if name and city:
        queries.append(f'"{name}" "{city}"')
    if name and company:
        queries.append(f'"{name}" "{company}"')
    if username and company:
        queries.append(f'"{username}" "{company}"')

    return _search_queries(
        list(dict.fromkeys(queries)), phone, limit_per_query=5
    )


def _extract_person_candidates(
    phone: str, evidence: list[dict]
) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    rejected: list[dict] = []
    variants = [v.casefold() for v in _phone_variants(phone)]

    for ev in evidence:
        text = f"{ev.get('title', '')} {ev.get('excerpt', '')}"
        if not any(v in text.casefold() for v in variants):
            continue
        for name in PERSON_RE.findall(text):
            grouped[_normalize_text(name)].append(ev)

    entities: list[dict] = []
    for normalized, items in grouped.items():
        domains = {
            _domain(item.get("source_url", ""))
            for item in items
            if _domain(item.get("source_url", ""))
        }
        value = " ".join(word.capitalize() for word in normalized.split())
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
                "id": (
                    "person_"
                    + hashlib.sha1(normalized.encode()).hexdigest()[:10]
                ),
                "type": "person",
                "claims": [
                    {
                        "field": "fio_candidate",
                        "value": value,
                        "normalized_value": normalized,
                        "confidence": score,
                        "verification_status": (
                            "Вероятно" if score < 80 else "Высокая вероятность"
                        ),
                        "source_count": len(items),
                        "independent_source_count": len(domains),
                        "evidence_ids": [item["id"] for item in items],
                        "extraction_method": "multi_query_context_resolution",
                        "reasoning_summary": (
                            f"Имя найдено рядом с номером в {len(domains)} "
                            "независимых доменах; требуется ручная проверка "
                            "первоисточников."
                        ),
                        "confidence_breakdown": {
                            "base_score": 46,
                            "independent_confirmation": min(
                                30, len(domains) * 10
                            ),
                            "context_strength": 12,
                            "final_score": score,
                        },
                    }
                ],
            }
        )
    return entities, rejected


def _evidence_text(ev: dict) -> str:
    return _normalize_text(
        f"{ev.get('title', '')} {ev.get('excerpt', '')}"
    )


def _context_match(key: str, normalized_value: str, ev: dict) -> bool:
    text = _evidence_text(ev)
    if not normalized_value or not text:
        return False
    if key == "username":
        pattern = re.compile(
            rf"(?<![\w.-])@?{re.escape(normalized_value)}(?![\w.-])",
            re.I,
        )
        return bool(pattern.search(text))
    return normalized_value in text


def _best_conflicting_person(
    provided_name: str, person_entities: list[dict]
) -> dict | None:
    provided = _normalize_text(provided_name)
    candidates: list[dict] = []
    for entity in person_entities:
        for claim in entity.get("claims", []):
            candidate = _normalize_text(
                claim.get("normalized_value") or claim.get("value", "")
            )
            if (
                candidate
                and candidate != provided
                and claim.get("confidence", 0) >= 80
                and claim.get("independent_source_count", 0) >= 2
            ):
                candidates.append(claim)
    if not candidates:
        return None
    return max(candidates, key=lambda claim: claim.get("confidence", 0))


def _context_entities(
    context: dict, evidence: list[dict], person_entities: list[dict]
) -> tuple[list[dict], list[dict]]:
    entities: list[dict] = []
    verification: list[dict] = []

    for key, value in context.items():
        if not value or key not in CONTEXT_FIELD_META:
            continue

        entity_type, field, label = CONTEXT_FIELD_META[key]
        normalized = _normalize_context_value(key, value)
        supporting = [
            ev for ev in evidence if _context_match(key, normalized, ev)
        ]
        domains = {
            _domain(ev.get("source_url", ""))
            for ev in supporting
            if _domain(ev.get("source_url", ""))
        }
        strong_sources = [
            ev
            for ev in supporting
            if ev.get("direct_match")
            and float(ev.get("reliability", 0.0)) >= 0.7
        ]
        conflict = (
            _best_conflicting_person(value, person_entities)
            if key == "name"
            else None
        )

        if conflict:
            status = "conflict"
            status_label = "Обнаружено противоречие"
            score = 20
            reasoning = (
                "В открытых источниках найден другой кандидат с высокой "
                f"оценкой: {conflict.get('value')}. Это не доказывает "
                "ошибочность введённого ФИО, но требует ручной проверки."
            )
        elif len(domains) >= 2:
            status = "confirmed"
            status_label = "Подтверждено"
            score = min(90, 60 + len(domains) * 10)
            reasoning = (
                f"Значение найдено в {len(domains)} независимых доменах."
            )
        elif strong_sources:
            status = "partially_confirmed"
            status_label = "Частично подтверждено"
            score = 60
            reasoning = (
                "Значение найдено в одном источнике с прямым совпадением "
                "и повышенной надёжностью."
            )
        elif supporting:
            status = "weak_signal"
            status_label = "Слабый сигнал"
            score = 42
            reasoning = (
                "Значение встречается в открытой выдаче, но независимых "
                "подтверждений недостаточно."
            )
        else:
            status = "insufficient"
            status_label = "Недостаточно данных"
            score = 25
            reasoning = (
                "Значение введено пользователем; независимое подтверждение "
                "в открытых источниках не найдено."
            )

        claim = {
            "field": field,
            "value": value,
            "normalized_value": normalized,
            "confidence": score,
            "verification_status": status_label,
            "source_count": len(supporting) + 1,
            "independent_source_count": len(domains),
            "evidence_ids": [ev["id"] for ev in supporting],
            "extraction_method": "user_context_correlation",
            "reasoning_summary": reasoning,
            "confidence_breakdown": {
                "user_context": 25,
                "independent_confirmation": min(40, len(domains) * 20),
                "strong_direct_sources": len(strong_sources),
                "final_score": score,
            },
        }
        entities.append(
            {
                "id": (
                    f"context_{key}_"
                    f"{hashlib.sha1(normalized.encode()).hexdigest()[:8]}"
                ),
                "type": entity_type,
                "claims": [claim],
            }
        )
        verification.append(
            {
                "field": key,
                "label": label,
                "provided_value": value,
                "status": status,
                "status_label": status_label,
                "confidence": score,
                "source_count": len(supporting),
                "independent_source_count": len(domains),
                "evidence_ids": [ev["id"] for ev in supporting],
                "reasoning": reasoning,
                "conflicting_value": (
                    conflict.get("value") if conflict else None
                ),
            }
        )

    return entities, verification


def enrich_phone_case(case: dict, context: dict | None = None) -> dict:
    inp = case.get("input", {})
    if inp.get("type") != "phone":
        return case

    context = {
        key: value
        for key, value in (context or {}).items()
        if isinstance(value, str) and value.strip()
    }
    phone = inp.get("normalized") or inp.get("raw") or ""
    original = case.get("evidence", [])
    clean_original = [
        ev
        for ev in original
        if not _is_noise(
            ev.get("source_url", ""),
            f"{ev.get('title', '')} {ev.get('excerpt', '')}",
        )
    ]

    supplemental = _search_phone(phone)
    contextual = _search_context(phone, context) if context else []
    evidence = clean_original + supplemental + contextual

    deduped: dict[str, dict] = {}
    for ev in evidence:
        key = (
            ev.get("content_hash")
            or ev.get("id")
            or hashlib.sha256(repr(sorted(ev.items())).encode()).hexdigest()
        )
        deduped[key] = ev
    evidence = list(deduped.values())

    person_entities, rejected = _extract_person_candidates(phone, evidence)
    context_entities, context_verification = _context_entities(
        context, evidence, person_entities
    )

    case["evidence"] = evidence
    case.setdefault("entities", []).extend(
        person_entities + context_entities
    )
    case.setdefault("rejected_candidates", []).extend(rejected)
    case["input"]["user_context"] = context

    summary = case.setdefault("summary", {})
    summary["context_verification"] = context_verification

    confirmed_context = [
        item
        for item in context_verification
        if item["status"] in {"confirmed", "partially_confirmed"}
    ]
    conflicts = [
        item for item in context_verification if item["status"] == "conflict"
    ]

    if person_entities:
        best = max(
            person_entities,
            key=lambda entity: entity["claims"][0].get("confidence", 0),
        )["claims"][0]
        summary["fio"] = (
            f"кандидат: {best['value']} ({best['confidence']}%)"
        )
        summary["headline"] = (
            "Найдены обоснованные кандидаты по открытым источникам. "
            "Это гипотезы, а не установленная личность; проверьте ссылки "
            "и контекст."
        )
    elif context.get("name"):
        name_row = next(
            (
                item
                for item in context_verification
                if item["field"] == "name"
            ),
            None,
        )
        state = (
            name_row["status_label"].casefold()
            if name_row
            else "недостаточно данных"
        )
        summary["fio"] = (
            f"указано пользователем: {context['name']} — {state}"
        )
        summary["headline"] = (
            "Пользовательский контекст проверен по открытым источникам. "
            "Отчёт отделяет подтверждения, слабые сигналы и противоречия."
        )
    else:
        summary["fio"] = "не подтверждено"
        summary["headline"] = (
            "Надёжная связь номера с ФИО в открытых источниках не "
            "подтверждена. SEO-каталоги и шаблонные совпадения удалены."
        )

    summary["identity_core"] = {
        "query_variants": _phone_variants(phone),
        "supplemental_evidence": len(supplemental),
        "contextual_evidence": len(contextual),
        "filtered_noise": len(original) - len(clean_original),
        "person_candidates": len(person_entities),
        "user_context_fields": list(context),
        "confirmed_context_fields": len(confirmed_context),
        "context_conflicts": len(conflicts),
    }
    return case
