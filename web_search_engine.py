#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
from ddgs import DDGS

# Быстрый набор запросов. Раньше движок делал десятки почти одинаковых запросов.
QUERY_TEMPLATES = [
    '"{phone}"',
    '"{phone}" контакты OR объявление',
    '"{phone}" организация OR ИП OR ООО',
    '"{phone}" резюме OR сотрудник',
    '"{phone}" site:vk.com OR site:ok.ru',
    '"{phone}" site:t.me OR site:telegram.me',
    '"{phone}" site:avito.ru OR site:youla.ru',
    '"{phone}" filetype:pdf',
]

JUNK_DOMAINS = {
    'baza-nomerov.com', 'centerica.ru', 'kodtelefona.ru', 'mobile-monitor.ru',
    'phoneradar.ru', 'region-operator.ru', 'spravochnik.tel', 'smzka.ru',
    'who-call.me', 'zvonok24.ru', 'numbase.ru', 'ented.ru', '7pld.ru',
    'nomercheck.ru', 'yarchelo.ru', 'truecaller.com', 'numlookup.com',
    'peoplefinders.com', 'spokeo.com', '411.com', 'robokiller.com',
    'findwhocallsyou.com',
}

SOCIAL = {'vk.com', 'ok.ru', 't.me', 'telegram.me', 'facebook.com', 'instagram.com', 'linkedin.com'}
MARKETS = {'avito.ru', 'youla.ru', 'auto.ru', 'farpost.ru', 'irr.ru', 'meshok.net'}
BUSINESS = {'2gis.ru', 'zoon.ru', 'rusprofile.ru', 'companies.rbc.ru', 'list-org.com'}

EMAIL_RE = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
PERSON_RE = re.compile(r'\b([А-ЯЁ][а-яё]{1,25}\s+[А-ЯЁ][а-яё]{1,25}(?:\s+[А-ЯЁ][а-яё]{1,25})?)\b')
ORG_RE = re.compile(r'\b((?:ООО|АО|ПАО|ИП|НКО|АНО|ЗАО)\s+[«"„]?[А-ЯЁA-Z0-9][^<>\n]{1,80}?[»"“]?)\b', re.I)
ADDRESS_RE = re.compile(
    r'\b(?:г\.?|город|обл\.?|область|край|республика|р-н|район|ул\.?|улица|'
    r'проспект|пр-т|пер\.?|переулок|шоссе|наб\.?|набережная|б-р|бульвар)\s+'
    r'[А-ЯЁA-Z0-9][^<>\n]{4,100}', re.I,
)

BAD_NAMES = {
    'Российская Федерация', 'Нижегородская Область', 'Мобильный Номер',
    'Телефонный Номер', 'Кто Звонил', 'Полная Информация', 'Главная Страница',
    'Обратная Связь', 'Пользовательское Соглашение', 'Поиск Организации',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36'
}


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
    if phone_digits and phone_digits in haystack:
        return True
    return len(phone_digits) == 11 and phone_digits.startswith('7') and phone_digits[1:] in haystack


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().split(':')[0].removeprefix('www.')


def valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def junk_url(url: str) -> bool:
    domain = domain_of(url)
    path = urlparse(url).path.lower()
    return domain in JUNK_DOMAINS or any(part in path for part in (
        'reverse-phone', 'phone-lookup', 'kto-zvonil', 'who-called', 'who-call'
    ))


def unique(values) -> list[str]:
    output, seen = [], set()
    for value in values:
        value = re.sub(r'\s+', ' ', value).strip(' ,.;:-')
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def evidence(text: str, needle: str, radius: int = 140) -> str:
    if not needle:
        return text[:280]
    pos = text.casefold().find(needle.casefold())
    if pos < 0:
        return text[:280]
    return text[max(0, pos-radius):min(len(text), pos+len(needle)+radius)].strip()


def fetch_page(url: str) -> tuple[str, str]:
    try:
        response = requests.get(url, timeout=(3, 5), headers=HEADERS, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if not any(x in content_type for x in ('text/html', 'text/plain', 'application/xhtml')):
            return '', f'unsupported content type: {content_type}'
        if len(response.content) > 1_500_000:
            return '', 'page too large'
        response.encoding = response.apparent_encoding or response.encoding
        return clean_text(response.text), ''
    except Exception as exc:
        return '', str(exc)


def source_score(domain: str, on_page: bool, in_result: bool) -> int:
    score = 32
    if on_page:
        score += 42
    elif in_result:
        score += 24
    if domain in BUSINESS:
        score += 12
    elif domain in SOCIAL or domain in MARKETS:
        score += 9
    return min(score, 96)


def add_finding(bucket: list[dict], kind: str, value: str, confidence: int, record: dict, context: str) -> None:
    if not value:
        return
    bucket.append({
        'kind': kind,
        'value': value,
        'confidence': max(1, min(confidence, 99)),
        'source_title': record.get('title', ''),
        'source_url': record['url'],
        'domain': record['domain'],
        'evidence': context[:700],
    })


def extract(record: dict, page: str, phone_digits: str) -> list[dict]:
    title = clean_text(record.get('title', ''))
    snippet = clean_text(record.get('snippet', ''))
    combined = ' '.join((title, snippet, page[:18000])).strip()
    in_result = phone_present(title + ' ' + snippet, phone_digits)
    on_page = phone_present(page, phone_digits)
    base = source_score(record['domain'], on_page, in_result)
    findings: list[dict] = []

    for value in unique(EMAIL_RE.findall(combined)):
        add_finding(findings, 'email', value, base + 5, record, evidence(combined, value))

    for value in unique(ORG_RE.findall(combined)):
        add_finding(findings, 'organization', value, base + 7, record, evidence(combined, value))

    names = unique(PERSON_RE.findall(' '.join((title, snippet, page[:9000]))))
    for value in names[:8]:
        if value in BAD_NAMES:
            continue
        title_hit = value.casefold() in (title + ' ' + snippet).casefold()
        confidence = base + (10 if title_hit else 0)
        # Даже слабые, но связанные с точной выдачей кандидаты теперь сохраняются.
        if confidence >= 48:
            add_finding(findings, 'person', value, confidence, record, evidence(combined, value))

    for value in unique(ADDRESS_RE.findall(page))[:6]:
        add_finding(findings, 'public_address', value[:130], base, record, evidence(page, value))

    if record['domain'] in SOCIAL:
        add_finding(findings, 'social_profile', record['url'], base, record, (title + ' — ' + snippet).strip(' —'))
    if record['domain'] in MARKETS:
        add_finding(findings, 'listing', record['url'], base, record, (title + ' — ' + snippet).strip(' —'))

    return findings


def merge_findings(items: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item['kind'], item['value'].casefold())
        source = {
            'title': item['source_title'], 'url': item['source_url'],
            'domain': item['domain'], 'evidence': item['evidence'],
        }
        if key not in merged:
            merged[key] = {
                'kind': item['kind'], 'value': item['value'],
                'confidence': item['confidence'], 'sources': [source],
            }
            continue
        current = merged[key]
        if all(src['url'].rstrip('/').casefold() != item['source_url'].rstrip('/').casefold() for src in current['sources']):
            current['sources'].append(source)
            current['confidence'] = min(99, max(current['confidence'], item['confidence']) + 5)
    return sorted(merged.values(), key=lambda x: (-x['confidence'], x['kind'], x['value'].casefold()))


def write_reports(output_dir: Path, phone: str, findings: list[dict], candidates: list[dict], errors: list[dict], elapsed: float) -> None:
    labels = {
        'person': 'ФИО / возможный человек', 'organization': 'Организация',
        'email': 'Email', 'social_profile': 'Публичный профиль',
        'listing': 'Объявление', 'public_address': 'Публичный адрес',
    }
    lines = [
        'AURORA PHONE INTELLIGENCE', f'Номер: {phone}', f'Время поиска: {elapsed:.1f} сек.', '',
        'Совпадение из открытой выдачи не доказывает текущего владельца номера.', '',
        f'Извлечённых связей: {len(findings)}', f'Страниц-кандидатов: {len(candidates)}',
        f'Ошибок: {len(errors)}', '',
    ]
    for index, item in enumerate(findings, 1):
        lines += [
            f'{index}. {labels.get(item["kind"], item["kind"])}',
            f'Значение: {item["value"]}', f'Уверенность: {item["confidence"]}%',
        ]
        for source in item['sources'][:4]:
            lines += [f'  {source["url"]}', f'  {source["evidence"][:450]}']
        lines.append('')
    if not findings:
        lines += ['ЯВНЫХ СВЯЗЕЙ НЕ НАЙДЕНО', 'Ниже сохранены наиболее релевантные страницы-кандидаты.', '']
    for item in candidates[:15]:
        lines += [f'- {item["title"] or "[без заголовка]"}', f'  {item["url"]}', f'  {item["snippet"][:350]}', '']
    (output_dir / 'findings.txt').write_text('\n'.join(lines), encoding='utf-8')

    cards = []
    for item in findings:
        links = ''.join(
            f'<li><a href="{html.escape(src["url"])}" target="_blank">{html.escape(src["title"] or src["domain"])}</a>'
            f'<div class="e">{html.escape(src["evidence"][:500])}</div></li>' for src in item['sources'][:5]
        )
        cards.append(f'<section><div class="k">{html.escape(labels.get(item["kind"], item["kind"]))}</div><h2>{html.escape(item["value"])}</h2><b>{item["confidence"]}%</b><ul>{links}</ul></section>')
    candidate_html = ''.join(
        f'<li><a href="{html.escape(x["url"])}" target="_blank">{html.escape(x["title"] or x["domain"])}</a><div class="e">{html.escape(x["snippet"][:400])}</div></li>'
        for x in candidates[:20]
    )
    document = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA</title><style>body{{margin:0;padding:18px;background:#0b0d0f;color:#edf2f5;font-family:system-ui}}main{{max-width:950px;margin:auto}}header,section{{background:#151a1e;border:1px solid #293139;border-radius:18px;padding:17px;margin-bottom:13px}}a{{color:#86a8ff}}.k{{color:#69f0c0;font-size:12px}}.e{{color:#9aa6ae;font-size:12px;margin-top:5px;line-height:1.4}}b{{color:#ffd27d}}</style></head><body><main><header><h1>AURORA</h1><p>{html.escape(phone)} · {elapsed:.1f} сек.</p><p>Совпадение не доказывает текущего владельца.</p></header>{''.join(cards)}<section><h2>Страницы-кандидаты</h2><ul>{candidate_html or '<li>Нет результатов</li>'}</ul></section></main></body></html>'''
    (output_dir / 'findings.html').write_text(document, encoding='utf-8')


def search_phone(phone: str, variants: list[str], output_dir: Path, max_results_per_query: int = 5) -> dict:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    phone_digits = digits(phone)

    # Используем максимум два действительно разных текстовых формата номера.
    selected = []
    for value in [phone, *variants]:
        value = clean_text(value)
        if value and value not in selected and digits(value) == phone_digits:
            selected.append(value)
        if len(selected) == 2:
            break

    queries = list(dict.fromkeys(
        template.format(phone=value) for value in selected for template in QUERY_TEMPLATES
    ))

    raw, seen, errors = [], set(), []
    with DDGS(timeout=8) as search:
        for query in queries:
            try:
                for item in search.text(query, max_results=min(max_results_per_query, 5)) or []:
                    url = clean_text(item.get('href') or item.get('url') or '')
                    if not valid_url(url) or junk_url(url):
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
                # Небольшая пауза снижает риск блокировки, но не растягивает поиск.
                time.sleep(0.12)
            except Exception as exc:
                errors.append({'query': query, 'error': str(exc)})

    # Сначала результаты, где номер уже виден в сниппете.
    raw.sort(key=lambda x: phone_present(x['title'] + ' ' + x['snippet'], phone_digits), reverse=True)
    candidates = raw[:24]

    pages: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(fetch_page, item['url']): item['url'] for item in candidates[:12]}
        for future in as_completed(future_map):
            url = future_map[future]
            try:
                pages[url] = future.result()
            except Exception as exc:
                pages[url] = ('', str(exc))

    accepted, extracted = [], []
    for record in candidates:
        page, fetch_error = pages.get(record['url'], ('', 'not fetched'))
        in_result = phone_present(record['title'] + ' ' + record['snippet'], phone_digits)
        on_page = phone_present(page, phone_digits)
        enriched = {**record, 'phone_in_search_result': in_result, 'phone_on_page': on_page, 'fetch_error': fetch_error}

        # Сохраняем и прямые совпадения, и хорошие поисковые кандидаты.
        if in_result or on_page:
            accepted.append(enriched)
            extracted.extend(extract(record, page, phone_digits))
        elif record['domain'] in SOCIAL | MARKETS | BUSINESS:
            extracted.extend(extract(record, page, phone_digits))

    findings = merge_findings(extracted)
    elapsed = time.monotonic() - started
    payload = {
        'phone': phone,
        'query_count': len(queries),
        'raw_result_count': len(raw),
        'result_count': len(accepted),
        'rejected_count': max(0, len(raw) - len(accepted)),
        'finding_count': len(findings),
        'findings': findings,
        'results': accepted,
        'candidates': candidates,
        'errors': errors,
        'elapsed_seconds': round(elapsed, 2),
        'scope': 'public open web only',
        'warning': 'Совпадение не доказывает текущего владельца номера.',
    }
    (output_dir / 'web_results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'raw_web_results.json').write_text(json.dumps({'phone': phone, 'queries': queries, 'results': raw, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'findings.json').write_text(json.dumps({'phone': phone, 'findings': findings, 'candidates': candidates, 'warning': payload['warning']}, ensure_ascii=False, indent=2), encoding='utf-8')
    write_reports(output_dir, phone, findings, candidates, errors, elapsed)
    return payload
