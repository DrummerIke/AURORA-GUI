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


def context_around_phone(text: str, phone: str, radius: int = 900) -> str:
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
    digest = hashlib.sha256(f"{current_url}|{excerpt}".encode()).hexdigest()
    return {
        "id": f"ev_page_{digest[:12]}",
        "source": "deep_public_page",
        "source_url": current_url,
        "source_type": "public_page",
        "title": title or item.get("title") or current_url,
        "excerpt": excerpt[:2200],
        "reliability": 0.76,
        "direct_match": True,
        "content_hash": digest,
        "metadata": {
            "parent_evidence_id": item.get("id"),
            "extracted_emails": emails,
        },
    }


def fetch_phone_linked_pages(
    evidence: list[dict], phone: str, max_pages: int | None = None
) -> list[dict]:
    if max_pages is None:
        max_pages = int(os.getenv("AURORA_DEEP_FETCH_MAX_PAGES", "10"))
    max_pages = max(0, min(max_pages, 20))
    if max_pages == 0:
        return []

    candidates: list[dict] = []
    seen_urls: set[str] = set()
    for item in evidence:
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
    workers = min(4, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_page_evidence, item, phone): item
            for item in candidates
        }
        try:
            for future in as_completed(futures, timeout=25):
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


def _email_entities_from_pages(case: dict, pages: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for page in pages:
        values = set(page.get("metadata", {}).get("extracted_emails") or [])
        values.update(value.casefold() for value in EMAIL_RE.findall(page.get("excerpt", "")))
        for value in values:
            grouped.setdefault(value, []).append(page)

    existing = _known_entity_values(case, "email")
    entities: list[dict] = []
    for email, items in grouped.items():
        if email in existing:
            continue
        domains = {_domain(item.get("source_url", "")) for item in items}
        domains.discard("")
        score = min(88, 68 + max(0, len(domains) - 1) * 10)
        entities.append(
            {
                "id": f"email_page_{hashlib.sha1(email.encode()).hexdigest()[:10]}",
                "type": "email",
                "claims": [
                    {
                        "field": "email",
                        "value": email,
                        "normalized_value": email,
                        "confidence": score,
                        "verification_status": (
                            "Высокая вероятность" if len(domains) >= 2 else "Вероятно"
                        ),
                        "source_count": len(items),
                        "independent_source_count": len(domains),
                        "evidence_ids": [item["id"] for item in items],
                        "extraction_method": "phone_linked_public_page",
                        "reasoning_summary": (
                            "Email найден на публичной странице, где присутствует "
                            "исходный номер телефона. Совпадение требует проверки "
                            "контекста страницы."
                        ),
                        "confidence_breakdown": {
                            "direct_phone_page_match": 55,
                            "source_reliability": 13,
                            "independent_confirmation": max(0, len(domains) - 1) * 10,
                            "final_score": score,
                        },
                    }
                ],
            }
        )
    return entities


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

    email_entities = _email_entities_from_pages(case, pages)
    case.setdefault("entities", []).extend(email_entities)

    if email_entities:
        best = max(
            email_entities,
            key=lambda entity: entity["claims"][0].get("confidence", 0),
        )["claims"][0]
        case.setdefault("summary", {})["email"] = (
            f"кандидат: {best['value']} ({best['confidence']}%)"
        )

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
            "entities": email_entities,
            "evidence": pages,
            "warnings": warnings,
            "errors": [],
            "raw_reference": None,
            "metadata": {
                "pages_with_exact_phone": len(pages),
                "email_candidates": len(email_entities),
            },
        }
    )
    case.setdefault("summary", {})["deep_public"] = {
        "pages_with_exact_phone": len(pages),
        "email_candidates": len(email_entities),
    }
    return case
