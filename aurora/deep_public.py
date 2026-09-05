from __future__ import annotations

import hashlib
import html
import ipaddress
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional fallback
    BeautifulSoup = None

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PERSON_RE = re.compile(
    r"\b([А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}"
    r"(?:\s+[А-ЯЁ][а-яё-]{1,30}){0,2})\b"
)
ORG_RE = re.compile(
    r"\b((?:ООО|АО|ПАО|ЗАО|ИП|АНО|НКО)\s+[«\"„]?"
    r"[А-ЯЁA-Z0-9][^<>\n]{1,80}?[»\"“]?(?=\s{2,}|[,.!?;]|$))",
    re.I,
)
NAME_LABEL_RE = re.compile(
    r"(?:ФИО|контактное\s+лицо|владелец|директор|руководитель|имя)\s*[:—-]\s*"
    r"([А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}"
    r"(?:\s+[А-ЯЁ][а-яё-]{1,30}){0,2})",
    re.I,
)
SOCIAL_HOSTS = {
    "vk.com": "vk",
    "t.me": "telegram",
    "telegram.me": "telegram",
    "ok.ru": "ok",
    "github.com": "github",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
}
GENERIC_SOCIAL_PATHS = {
    "share", "login", "signup", "search", "explore", "home", "about",
    "privacy", "terms", "help", "messages", "settings",
}
BAD_NAME_FRAGMENTS = {
    "телефон", "номер", "контакты", "главная", "страница", "россия",
    "обратная связь", "пользовательское соглашение", "политика конфиденциальности",
    "кто звонил", "мобильный номер", "частное лицо",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
    )
}
MAX_PAGE_BYTES = 1_200_000


def phone_digits(value: str) -> str:
    result = re.sub(r"\D", "", value or "")
    if len(result) == 11 and result.startswith("8"):
        result = "7" + result[1:]
    return result


def phone_present(text: str, phone: str) -> bool:
    needle = phone_digits(phone)
    if not needle:
        return False
    haystack = re.sub(r"\D", "", text or "")
    if needle in haystack:
        return True
    return len(needle) == 11 and needle.startswith("7") and needle[1:] in haystack


def safe_public_url(url: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.casefold()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except OSError:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def clean_page(raw_html: str) -> tuple[str, str]:
    raw_html = raw_html or ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        for tag in soup(["script", "style", "nav", "form", "button", "svg"]):
            tag.decompose()
        text = soup.get_text(" ")
    else:
        title_match = re.search(
            r"<title\b[^>]*>(.*?)</title>", raw_html, flags=re.I | re.S
        )
        title = re.sub(r"<[^>]+>", " ", title_match.group(1)) if title_match else ""
        text = re.sub(
            r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.I | re.S
        )
        text = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S
        )
        text = re.sub(r"<[^>]+>", " ", text)
    return (
        re.sub(r"\s+", " ", html.unescape(title)).strip(),
        re.sub(r"\s+", " ", html.unescape(text)).strip(),
    )


def context_around_phone(text: str, phone: str, radius: int = 1100) -> str:
    if not text:
        return ""
    digits = phone_digits(phone)
    compact = re.sub(r"\D", "", text)
    if digits and digits in compact:
        variants = [phone, digits]
        if len(digits) == 11 and digits.startswith("7"):
            variants.extend(["8" + digits[1:], digits[1:]])
        lowered = text.casefold()
        for variant in variants:
            position = lowered.find(variant.casefold())
            if position >= 0:
                return text[max(0, position - radius): position + len(variant) + radius]
    return text[: radius * 2]


def _response_body(response: requests.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_PAGE_BYTES:
            raise ValueError("page too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _normalise_name(value: str) -> str:
    return " ".join(value.split()).strip(" ,.;:-")


def _valid_person_candidate(value: str) -> bool:
    candidate = _normalise_name(value)
    lowered = candidate.casefold()
    if not candidate or any(fragment in lowered for fragment in BAD_NAME_FRAGMENTS):
        return False
    words = candidate.split()
    if not 2 <= len(words) <= 4:
        return False
    return all(re.fullmatch(r"[А-ЯЁ][а-яё-]{1,30}", word) for word in words)


def _extract_names(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in NAME_LABEL_RE.findall(text or ""):
        value = _normalise_name(value)
        key = value.casefold()
        if _valid_person_candidate(value) and key not in seen:
            seen.add(key)
            found.append(value)
    for value in PERSON_RE.findall(text or ""):
        value = _normalise_name(value)
        key = value.casefold()
        if _valid_person_candidate(value) and key not in seen:
            seen.add(key)
            found.append(value)
        if len(found) >= 10:
            break
    return found


def _extract_orgs(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for value in ORG_RE.findall(text or ""):
        value = re.sub(r"\s+", " ", value).strip(" ,.;:-")
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            values.append(value)
    return values[:8]


def _profile_from_url(url: str) -> dict | None:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    network = SOCIAL_HOSTS.get(host)
    if not network:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    username = parts[0].lstrip("@").strip()
    if not username or username.casefold() in GENERIC_SOCIAL_PATHS:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,80}", username):
        return None
    return {"network": network, "username": username, "url": url}


def _extract_social_profiles(raw_html: str, base_url: str) -> list[dict]:
    links: list[str] = []
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html or "", "html.parser")
        for anchor in soup.find_all("a", href=True):
            links.append(urljoin(base_url, anchor.get("href", "")))
    else:
        for href in re.findall(r"href=[\"']([^\"']+)[\"']", raw_html or "", re.I):
            links.append(urljoin(base_url, href))

    source_profile = _profile_from_url(base_url)
    profiles: list[dict] = [source_profile] if source_profile else []
    seen = {(item["network"], item["username"].casefold()) for item in profiles}
    for link in links:
        profile = _profile_from_url(link)
        if not profile:
            continue
        key = (profile["network"], profile["username"].casefold())
        if key in seen:
            continue
        seen.add(key)
        profiles.append(profile)
        if len(profiles) >= 12:
            break
    return profiles


def fetch_page_evidence(item: dict, phone: str) -> dict | None:
    current_url = str(item.get("source_url") or "")
    if not safe_public_url(current_url):
        return None

    response: requests.Response | None = None
    for _ in range(4):
        response = requests.get(
            current_url,
            headers=HEADERS,
            timeout=(3, 7),
            allow_redirects=False,
            stream=True,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "")
            response.close()
            next_url = urljoin(current_url, location)
            if not location or not safe_public_url(next_url):
                return None
            current_url = next_url
            continue
        break

    if response is None:
        return None
    try:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        if not any(
            value in content_type
            for value in ("text/html", "text/plain", "application/xhtml")
        ):
            return None
        body = _response_body(response)
        encoding = response.encoding or "utf-8"
        raw_html = body.decode(encoding, errors="replace")
    finally:
        response.close()

    title, text = clean_page(raw_html)
    if not phone_present(text, phone):
        return None

    excerpt = context_around_phone(text, phone)
    emails = sorted({value.casefold() for value in EMAIL_RE.findall(excerpt)})
    names = _extract_names(excerpt)
    organisations = _extract_orgs(excerpt)
    social_profiles = _extract_social_profiles(raw_html, current_url)
    digest = hashlib.sha256(f"{current_url}|{excerpt}".encode()).hexdigest()
    return {
        "id": f"ev_page_{digest[:12]}",
        "source": "deep_public_page",
        "source_url": current_url,
        "source_type": "public_page",
        "title": title or item.get("title") or current_url,
        "excerpt": excerpt[:2400],
        "reliability": 0.76,
        "direct_match": True,
        "content_hash": digest,
        "metadata": {
            "parent_evidence_id": item.get("id"),
            "extracted_emails": emails,
            "extracted_names": names,
            "extracted_organisations": organisations,
            "social_profiles": social_profiles,
        },
    }


def fetch_phone_linked_pages(
    evidence: list[dict], phone: str, max_pages: int | None = None
) -> list[dict]:
    if max_pages is None:
        max_pages = int(os.getenv("AURORA_DEEP_FETCH_MAX_PAGES", "15"))
    max_pages = max(0, min(max_pages, 30))
    if max_pages == 0:
        return []

    candidates: list[dict] = []
    seen_urls: set[str] = set()
    ranked = sorted(
        evidence,
        key=lambda item: (
            bool(item.get("direct_match")),
            float(item.get("reliability", 0.0)),
        ),
        reverse=True,
    )
    for item in ranked:
        url = str(item.get("source_url") or "").rstrip("/")
        if not url or url.casefold() in seen_urls:
            continue
        if item.get("source_type") not in {"search_result", "web"}:
            continue
        seen_urls.add(url.casefold())
        candidates.append(item)
        if len(candidates) >= max_pages:
            break

    if not candidates:
        return []

    results: list[dict] = []
    workers = min(5, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_page_evidence, item, phone): item
            for item in candidates
        }
        try:
            for future in as_completed(futures, timeout=35):
                try:
                    result = future.result()
                except Exception:
                    continue
                if result:
                    results.append(result)
        except TimeoutError:
            for future in futures:
                future.cancel()

    return results


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.casefold().removeprefix("www.")


def _known_entity_values(case: dict, entity_type: str) -> set[str]:
    values: set[str] = set()
    for entity in case.get("entities", []):
        if entity.get("type") != entity_type:
            continue
        for claim in entity.get("claims", []):
            value = str(claim.get("normalized_value") or claim.get("value") or "")
            if value:
                values.add(value.casefold())
    return values


def _entity(
    entity_type: str,
    field: str,
    value: str,
    items: list[dict],
    *,
    base_score: int,
    method: str,
    reasoning: str,
) -> dict:
    domains = {_domain(item.get("source_url", "")) for item in items}
    domains.discard("")
    score = min(90, base_score + max(0, len(domains) - 1) * 10)
    status = "Высокая вероятность" if len(domains) >= 2 and score >= 78 else "Вероятно"
    normalized = value.casefold().lstrip("@") if entity_type == "username" else value.casefold()
    return {
        "id": f"{entity_type}_page_{hashlib.sha1(normalized.encode()).hexdigest()[:10]}",
        "type": entity_type,
        "claims": [
            {
                "field": field,
                "value": value,
                "normalized_value": normalized,
                "confidence": score,
                "verification_status": status,
                "source_count": len(items),
                "independent_source_count": len(domains),
                "evidence_ids": [item["id"] for item in items],
                "extraction_method": method,
                "reasoning_summary": reasoning,
                "confidence_breakdown": {
                    "exact_phone_page": base_score,
                    "independent_confirmation": max(0, len(domains) - 1) * 10,
                    "final_score": score,
                },
            }
        ],
    }


def _entities_from_pages(case: dict, pages: list[dict]) -> list[dict]:
    buckets: dict[str, dict[str, list[dict]]] = {
        "email": {},
        "person": {},
        "organization": {},
        "username": {},
    }
    username_display: dict[str, str] = {}

    for page in pages:
        metadata = page.get("metadata", {})
        for email in metadata.get("extracted_emails") or []:
            buckets["email"].setdefault(email.casefold(), []).append(page)
        for name in metadata.get("extracted_names") or []:
            buckets["person"].setdefault(name.casefold(), []).append(page)
        for org in metadata.get("extracted_organisations") or []:
            buckets["organization"].setdefault(org.casefold(), []).append(page)
        for profile in metadata.get("social_profiles") or []:
            username = str(profile.get("username") or "").strip()
            network = str(profile.get("network") or "social").strip()
            if not username:
                continue
            key = f"{network}:{username.casefold()}"
            username_display[key] = f"{network}: @{username}"
            buckets["username"].setdefault(key, []).append(page)

    entities: list[dict] = []
    existing = {
        entity_type: _known_entity_values(case, entity_type)
        for entity_type in buckets
    }

    for email, items in buckets["email"].items():
        if email in existing["email"]:
            continue
        entities.append(
            _entity(
                "email", "email", email, items,
                base_score=68,
                method="phone_linked_public_page",
                reasoning=(
                    "Email найден на публичной странице, где исходный номер "
                    "телефона присутствует непосредственно в тексте."
                ),
            )
        )

    for normalized, items in buckets["person"].items():
        if normalized in existing["person"]:
            continue
        value = next(
            name
            for page in items
            for name in page.get("metadata", {}).get("extracted_names", [])
            if name.casefold() == normalized
        )
        entities.append(
            _entity(
                "person", "fio_candidate", value, items,
                base_score=58,
                method="phone_linked_public_page_name",
                reasoning=(
                    "ФИО-кандидат найден в непосредственном контексте номера "
                    "на публичной странице. Это кандидат, а не установленный владелец."
                ),
            )
        )

    for normalized, items in buckets["organization"].items():
        if normalized in existing["organization"]:
            continue
        value = next(
            org
            for page in items
            for org in page.get("metadata", {}).get("extracted_organisations", [])
            if org.casefold() == normalized
        )
        entities.append(
            _entity(
                "organization", "organization_candidate", value, items,
                base_score=64,
                method="phone_linked_public_page_organization",
                reasoning=(
                    "Организация упоминается рядом с исходным номером на "
                    "публичной странице."
                ),
            )
        )

    for key, items in buckets["username"].items():
        display = username_display[key]
        normalized = display.casefold().lstrip("@")
        if normalized in existing["username"]:
            continue
        entities.append(
            _entity(
                "username", "public_profile", display, items,
                base_score=66,
                method="phone_linked_public_social_profile",
                reasoning=(
                    "Публичный профиль найден на странице, где исходный номер "
                    "присутствует непосредственно в тексте."
                ),
            )
        )

    return entities


def _count_types(entities: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        entity_type = entity.get("type", "unknown")
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return counts


def enrich_case_with_public_pages(case: dict) -> dict:
    inp = case.get("input", {})
    if inp.get("type") != "phone":
        return case

    phone = inp.get("normalized") or inp.get("raw") or ""
    pages = fetch_phone_linked_pages(case.get("evidence", []), phone)
    if pages:
        seen = {
            item.get("content_hash") or item.get("id")
            for item in case.get("evidence", [])
        }
        case.setdefault("evidence", []).extend(
            item
            for item in pages
            if (item.get("content_hash") or item.get("id")) not in seen
        )

    new_entities = _entities_from_pages(case, pages)
    case.setdefault("entities", []).extend(new_entities)

    relationships = case.setdefault("relationships", [])
    for entity in new_entities:
        claim = (entity.get("claims") or [{}])[0]
        relationships.append(
            {
                "from": "entity_input",
                "to": entity.get("id"),
                "type": "co_occurs_with_phone_on_public_page",
                "evidence_ids": claim.get("evidence_ids", []),
                "confidence": claim.get("confidence", 0),
            }
        )

    summary = case.setdefault("summary", {})
    person_entities = [entity for entity in new_entities if entity.get("type") == "person"]
    email_entities = [entity for entity in new_entities if entity.get("type") == "email"]

    if person_entities and str(summary.get("fio", "")).startswith("не подтверж"):
        best = max(person_entities, key=lambda e: e["claims"][0].get("confidence", 0))["claims"][0]
        summary["fio"] = f"кандидат: {best['value']} ({best['confidence']}%)"
    if email_entities and str(summary.get("email", "")).startswith("не подтверж"):
        best = max(email_entities, key=lambda e: e["claims"][0].get("confidence", 0))["claims"][0]
        summary["email"] = f"кандидат: {best['value']} ({best['confidence']}%)"

    counts = _count_types(new_entities)
    warnings = [] if pages else [
        "Публичные страницы с точным присутствием номера не найдены или недоступны."
    ]
    case.setdefault("connector_runs", []).append(
        {
            "connector_id": "deep_public_fetch",
            "status": "OK",
            "started_at": "",
            "completed_at": "",
            "duration_ms": 0,
            "entities": new_entities,
            "evidence": pages,
            "warnings": warnings,
            "errors": [],
            "raw_reference": None,
            "metadata": {
                "pages_with_exact_phone": len(pages),
                "person_candidates": counts.get("person", 0),
                "email_candidates": counts.get("email", 0),
                "organization_candidates": counts.get("organization", 0),
                "username_candidates": counts.get("username", 0),
            },
        }
    )
    summary["deep_public"] = {
        "pages_with_exact_phone": len(pages),
        "person_candidates": counts.get("person", 0),
        "email_candidates": counts.get("email", 0),
        "organization_candidates": counts.get("organization", 0),
        "username_candidates": counts.get("username", 0),
        "useful_entities": len(new_entities),
    }
    return case
