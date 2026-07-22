#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from ddgs import DDGS

QUERIES = [
    '"{phone}"',
    '"{phone}" контакты',
    '"{phone}" объявление',
    '"{phone}" организация',
    '"{phone}" директор',
    '"{phone}" ИП',
    '"{phone}" ООО',
    '"{phone}" резюме',
    '"{phone}" site:vk.com',
    '"{phone}" site:ok.ru',
    '"{phone}" site:t.me',
    '"{phone}" site:avito.ru',
    '"{phone}" site:youla.ru',
    '"{phone}" site:hh.ru',
    '"{phone}" site:2gis.ru',
    '"{phone}" site:zoon.ru',
    '"{phone}" site:rusprofile.ru',
    '"{phone}" filetype:pdf',
]

JUNK_DOMAINS = {
    'baza-nomerov.com', 'centerica.ru', 'kodtelefona.ru',
    'mobile-monitor.ru', 'phoneradar.ru', 'region-operator.ru',
    'spravochnik.tel', 'smzka.ru', 'who-call.me', 'zvonok24.ru',
    'numbase.ru', 'ented.ru', '7pld.ru', 'nomercheck.ru',
    'yarchelo.ru', 'truecaller.com', 'numlookup.com',
    'peoplefinders.com', 'spokeo.com', '411.com', 'robokiller.com',
    'findwhocallsyou.com',
}

SOCIAL = {'vk.com', 'ok.ru', 't.me', 'telegram.me', 'facebook.com', 'instagram.com', 'linkedin.com'}
MARKETS = {'avito.ru', 'youla.ru', 'auto.ru', 'farpost.ru', 'irr.ru', 'meshok.net'}
BUSINESS = {'2gis.ru', 'zoon.ru', 'rusprofile.ru', 'companies.rbc.ru', 'list-org.com'}

EMAIL_RE = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
PERSON_RE = re.compile(r'\b([А-ЯЁ][а-яё]{1,24}\s+[А-ЯЁ][а-яё]{1,24}(?:\s+[А-ЯЁ][а-яё]{1,24})?)\b')
ORG_RE = re.compile(r'\b((?:ООО|АО|ПАО|ИП|НКО|АНО|ЗАО)\s+[«"„]?[А-ЯЁA-Z0-9][^<>\n]{1,80}?[»"“]?)\b', re.I)
ADDRESS_RE = re.compile(
    r'\b(?:г\.?|город|обл\.?|область|край|республика|р-н|район|'
    r'ул\.?|улица|проспект|пр-т|пер\.?|переулок|шоссе|наб\.?|'
    r'набережная|б-р|бульвар)\s+[А-ЯЁA-Z0-9][^<>\n]{4,100}',
    re.I,
)

BAD_PERSON = {
    'Нижегородская Область', 'Российская Федерация', 'Поиск Организации',
    'Мобильный Номер', 'Телефонный Номер', 'Кто Звонил',
    'Полная Информация', 'Узнать Владельца', 'Обратная Связь',
    'Главная Страница', 'Пользовательское Соглашение',
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Safari/537.36'}


@dataclass
class Finding:
    kind: str
    value: str
    confidence: int
    source_title: str
    source_url: str
    domain: str
    evidence: str


def clean_text(value: str) -> str:
    value = html.unescape(value or '')
    value = re.sub(r'<script\b[^>]*>.*?</script>', ' ', value, flags=re.I | re.S)
    value = re.sub(r'<style\b[^>]*>.*?</style>', ' ', value, flags=re.I | re.S)
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def digits(value: str) -> str:
    result = re.sub(r'\D', '', value or '')
    if len(result) == 11 and result.startswith('8'):
        result = '7' + result[1:]
    return result


def phone_present(text: str, phone_digits: str) -> bool:
    haystack = re.sub(r'\D', '', text or '')
    return phone_digits in haystack or (
        len(phone_digits) == 11 and phone_digits.startswith('7') and phone_digits[1:] in haystack
    )


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().split(':')[0].removeprefix('www.')


def valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def junk_url(url: str) -> bool:
    domain = domain_of(url)
    path = urlparse(url).path.lower()
    return domain in JUNK_DOMAINS or any(x in path for x in (
        'reverse-phone', 'phone-lookup', 'kto-zvonil', 'who-called', 'who-call', '/phone/', '/number/'
    ))


def fetch_page(url: str) -> tuple[str, str]:
    try:
        response = requests.get(url, timeout=12, headers=HEADERS, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if not any(x in content_type for x in ('text/html', 'text/plain', 'application/xhtml')):
            return '', f'unsupported content type: {content_type}'
        if len(response.content) > 2_500_000:
            return '', 'page too large'
        response.encoding = response.apparent_encoding or response.encoding
        return clean_text(response.text), ''
    except Exception as exc:
        return '', str(exc)


def evidence(text: str, needle: str, radius: int = 140) -> str:
    pos = text.casefold().find(needle.casefold())
    if pos < 0:
        return text[:280]
    return text[max(0, pos-radius):min(len(text), pos+len(needle)+radius)].strip()


def unique(values) -> list[str]:
    output, seen = [], set()
    for value in values:
        value = re.sub(r'\s+', ' ', value).strip(' ,.;:-')
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def source_score(domain: str, on_page: bool, in_result: bool) -> int:
    score = 25 + (40 if on_page else 20 if in_result else 0)
    if domain in SOCIAL or domain in MARKETS:
        score += 12
    elif domain in BUSINESS:
        score += 15
    return min(score, 95)


def extract(record: dict, page: str, phone_digits: str) -> list[Finding]:
    title = clean_text(record.get('title', ''))
    snippet = clean_text(record.get('snippet', ''))
    url = record['url']
    domain = domain_of(url)
    combined = ' '.join((title, snippet, page)).strip()
    on_page = phone_present(page, phone_digits)
    in_result = phone_present(title + ' ' + snippet, phone_digits)
    if not (on_page or in_result):
        return []

    base = source_score(domain, on_page, in_result)
    found: list[Finding] = []

    for value in unique(EMAIL_RE.findall(combined)):
        found.append(Finding('email', value, min(base+5, 98), title, url, domain, evidence(combined, value)))

    for value in unique(ORG_RE.findall(combined)):
        found.append(Finding('organization', value, min(base+8, 98), title, url, domain, evidence(combined, value)))

    near_phone = evidence(combined, phone_digits[-10:], 320)
    for value in unique(PERSON_RE.findall(' '.join((title, snippet, page[:12000])))):
        if value in BAD_PERSON:
            continue
        title_hit = value.casefold() in (title + ' ' + snippet).casefold()
        nearby = value.casefold() in near_phone.casefold()
        confidence = base + (12 if title_hit else 0) + (8 if nearby else 0)
        if confidence >= 55:
            found.append(Finding('person', value, min(confidence, 98), title, url, domain, evidence(combined, value)))

    for value in unique(ADDRESS_RE.findall(page)):
        found.append(Finding('public_address', value[:130], min(base + (10 if domain in BUSINESS else 0), 95), title, url, domain, evidence(page, value)))

    if domain in SOCIAL:
        found.append(Finding('social_profile', url, base, title, url, domain, (title + ' — ' + snippet).strip(' —')))
    if domain in MARKETS:
        found.append(Finding('listing', url, base, title, url, domain, (title + ' — ' + snippet).strip(' —')))

    return found


def merge_findings(items: list[Finding]) -> list[dict]:
    merged = {}
    for item in items:
        key = (item.kind, item.value.casefold())
        source = {'title': item.source_title, 'url': item.source_url, 'domain': item.domain, 'evidence': item.evidence}
        if key not in merged:
            merged[key] = {**asdict(item), 'sources': [source]}
            continue
        current = merged[key]
        if all(x['url'].rstrip('/').casefold() != item.source_url.rstrip('/').casefold() for x in current['sources']):
            current['sources'].append(source)
        current['confidence'] = min(99, max(current['confidence'], item.confidence) + min(12, (len(current['sources'])-1)*4))
    return sorted(merged.values(), key=lambda x: (-x['confidence'], x['kind'], x['value'].casefold()))


def write_reports(output_dir: Path, phone: str, findings: list[dict], accepted: list[dict], rejected: list[dict], errors: list[dict]) -> None:
    labels = {
        'person': 'ФИО / человек', 'organization': 'Организация', 'email': 'Email',
        'social_profile': 'Публичный профиль', 'listing': 'Объявление',
        'public_address': 'Публичный адрес',
    }
    lines = [
        'AURORA PHONE INTELLIGENCE', f'Номер: {phone}', '',
        'Совпадение не доказывает текущего владельца номера.',
        'Публичный адрес может быть офисом, местом услуги или адресом объявления.', '',
        f'Подтверждаемых находок: {len(findings)}', f'Полезных страниц: {len(accepted)}',
        f'Отброшено страниц: {len(rejected)}', f'Ошибок: {len(errors)}', '',
    ]
    if not findings:
        lines += ['ПОДТВЕРЖДАЕМЫХ СВЯЗЕЙ НЕ НАЙДЕНО', '']
    for index, item in enumerate(findings, 1):
        lines += [f'{index}. {labels.get(item["kind"], item["kind"])}', f'Значение: {item["value"]}', f'Уверенность: {item["confidence"]}%']
        for source in item['sources'][:5]:
            lines += [f'  - {source["title"] or "[без заголовка]"}', f'    {source["url"]}', f'    Контекст: {source["evidence"][:500]}']
        lines.append('')
    (output_dir / 'findings.txt').write_text('\n'.join(lines), encoding='utf-8')

    cards = []
    for item in findings:
        sources = ''.join(
            f'<li><a href="{html.escape(src["url"])}" target="_blank">{html.escape(src["title"] or src["domain"])}</a>'
            f'<div class="evidence">{html.escape(src["evidence"][:600])}</div></li>'
            for src in item['sources'][:8]
        )
        cards.append(
            f'<section><div class="kind">{html.escape(labels.get(item["kind"], item["kind"]))}</div>'
            f'<h2>{html.escape(item["value"])}</h2><div class="score">Уверенность: {item["confidence"]}%</div><ul>{sources}</ul></section>'
        )
    if not cards:
        cards = ['<section><h2>Подтверждаемых связей не найдено</h2></section>']
    document = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA</title><style>body{{margin:0;padding:20px;background:#0b0d0f;color:#edf2f5;font-family:system-ui}}main{{max-width:980px;margin:auto}}header,section{{background:#14191d;border:1px solid #293139;border-radius:18px;padding:18px;margin-bottom:14px}}h1{{letter-spacing:.12em}}.kind{{color:#69f0c0;font-size:12px;text-transform:uppercase}}.score{{color:#ffd27d}}a{{color:#86a8ff}}.evidence{{color:#9aa6ae;font-size:12px;margin-top:4px}}</style></head><body><main><header><h1>AURORA</h1><div>{html.escape(phone)}</div><p>Совпадение не доказывает текущего владельца.</p></header>{''.join(cards)}</main></body></html>'''
    (output_dir / 'findings.html').write_text(document, encoding='utf-8')


def search_phone(phone: str, variants: list[str], output_dir: Path, max_results_per_query: int = 8) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    phone_digits = digits(phone)
    selected = []
    for variant in variants:
        if digits(variant) == phone_digits and variant not in selected:
            selected.append(variant)
        if len(selected) >= 4:
            break
    if phone not in selected:
        selected.insert(0, phone)

    queries = list(dict.fromkeys(template.format(phone=value) for value in selected[:4] for template in QUERIES))
    raw, seen, errors = [], set(), []
    with DDGS(timeout=15) as search:
        for query in queries:
            try:
                for item in search.text(query, max_results=max_results_per_query) or []:
                    url = clean_text(item.get('href') or item.get('url') or '')
                    if not valid_url(url):
                        continue
                    key = url.rstrip('/').casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    raw.append({
                        'query': query,
                        'title': clean_text(item.get('title', '')),
                        'url': url,
                        'snippet': clean_text(item.get('body') or item.get('snippet') or ''),
                        'domain': domain_of(url),
                    })
                time.sleep(0.45)
            except Exception as exc:
                errors.append({'query': query, 'error': str(exc)})

    raw.sort(key=lambda x: phone_present(x['title'] + ' ' + x['snippet'], phone_digits), reverse=True)
    accepted, rejected, extracted = [], [], []
    fetched = 0
    for record in raw:
        if junk_url(record['url']):
            rejected.append({**record, 'reason': 'lookup/catalog noise'})
            continue
        in_result = phone_present(record['title'] + ' ' + record['snippet'], phone_digits)
        page, fetch_error = ('', '')
        if fetched < 35:
            page, fetch_error = fetch_page(record['url'])
            fetched += 1
        on_page = phone_present(page, phone_digits)
        if not (in_result or on_page):
            rejected.append({**record, 'reason': 'phone not confirmed', 'fetch_error': fetch_error})
            continue
        accepted.append({**record, 'phone_in_search_result': in_result, 'phone_on_page': on_page, 'fetch_error': fetch_error})
        extracted.extend(extract(record, page, phone_digits))

    findings = merge_findings(extracted)
    payload = {
        'phone': phone, 'query_count': len(queries), 'raw_result_count': len(raw),
        'result_count': len(accepted), 'rejected_count': len(rejected),
        'finding_count': len(findings), 'findings': findings, 'results': accepted,
        'rejected': rejected, 'errors': errors, 'scope': 'public open web only',
        'warning': 'Совпадение не доказывает текущего владельца номера.',
    }
    (output_dir / 'web_results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'raw_web_results.json').write_text(json.dumps({'phone': phone, 'queries': queries, 'results': raw, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'findings.json').write_text(json.dumps({'phone': phone, 'findings': findings, 'warning': payload['warning']}, ensure_ascii=False, indent=2), encoding='utf-8')
    write_reports(output_dir, phone, findings, accepted, rejected, errors)
    return payload
