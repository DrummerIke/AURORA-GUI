#!/usr/bin/env python3

import html
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

SEARCH_GROUPS = {
    "Общий поиск": [
        '"{value}"', '"{value}" телефон', '"{value}" контакты',
        '"{value}" организация', '"{value}" объявление',
    ],
    "Социальные сети": [
        '"{value}" site:vk.com', '"{value}" site:ok.ru',
        '"{value}" site:t.me', '"{value}" site:telegram.me',
    ],
    "Объявления": [
        '"{value}" site:avito.ru', '"{value}" site:youla.ru',
        '"{value}" site:auto.ru',
    ],
    "Организации и документы": [
        '"{value}" site:2gis.ru', '"{value}" site:zoon.ru',
        '"{value}" site:rusprofile.ru', '"{value}" filetype:pdf',
    ],
}


def normalize_phone(raw_value: str, default_region: str = "RU") -> dict:
    raw_value = raw_value.strip()
    if not raw_value:
        raise ValueError("Номер не указан")

    cleaned = re.sub(r"[^\d+]", "", raw_value)
    if cleaned.startswith("8") and len(re.sub(r"\D", "", cleaned)) == 11:
        cleaned = "+7" + cleaned[1:]
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    try:
        parsed = phonenumbers.parse(cleaned, default_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"Не удалось распознать номер: {exc}") from exc

    if not phonenumbers.is_possible_number(parsed):
        raise ValueError("Номер имеет невозможную длину или структуру")

    return {
        "input": raw_value,
        "e164": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        "international": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "national": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL),
        "country_code": parsed.country_code,
        "national_number": str(parsed.national_number),
        "valid": phonenumbers.is_valid_number(parsed),
        "region": phonenumbers.region_code_for_number(parsed) or "",
        "location": geocoder.description_for_number(parsed, "ru") or "",
        "carrier": carrier.name_for_number(parsed, "ru") or "",
        "timezones": list(timezone.time_zones_for_number(parsed)),
    }


def build_variants(phone_data: dict) -> list[str]:
    e164 = phone_data["e164"]
    digits = re.sub(r"\D", "", e164)
    national = phone_data["national_number"]
    variants = {e164, digits, phone_data["international"], phone_data["national"]}

    if e164.startswith("+7") and len(digits) == 11:
        variants.update({
            "8" + national,
            f"+7{national}",
            f"+7 ({national[:3]}) {national[3:6]}-{national[6:8]}-{national[8:]}",
            f"8 ({national[:3]}) {national[3:6]}-{national[6:8]}-{national[8:]}",
        })

    return sorted(v.strip() for v in variants if v.strip())


def build_searches(variants: list[str]) -> list[dict]:
    records, seen = [], set()
    for group, templates in SEARCH_GROUPS.items():
        for variant in variants:
            for template in templates:
                query = template.format(value=variant)
                if query in seen:
                    continue
                seen.add(query)
                encoded = quote_plus(query)
                records.append({
                    "group": group,
                    "variant": variant,
                    "query": query,
                    "google": f"https://www.google.com/search?q={encoded}",
                    "yandex": f"https://yandex.ru/search/?text={encoded}",
                    "bing": f"https://www.bing.com/search?q={encoded}",
                    "duckduckgo": f"https://duckduckgo.com/?q={encoded}",
                })
    return records


def create_report(raw_phone: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    phone_data = normalize_phone(raw_phone)
    variants = build_variants(phone_data)
    searches = build_searches(variants)

    summary = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "phone": phone_data,
        "variants": variants,
        "search_count": len(searches),
        "scope": "Open sources only",
        "warning": "Совпадение не доказывает текущего владельца номера.",
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "number_variants.txt").write_text("\n".join(variants) + "\n", encoding="utf-8")
    (output_dir / "searches.json").write_text(
        json.dumps(searches, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows = []
    for index, item in enumerate(searches, 1):
        rows.append(
            "<tr>"
            f"<td>{index}</td><td>{html.escape(item['group'])}</td>"
            f"<td>{html.escape(item['query'])}</td>"
            f"<td><a href=\"{item['yandex']}\">Яндекс</a> · "
            f"<a href=\"{item['google']}\">Google</a> · "
            f"<a href=\"{item['bing']}\">Bing</a></td></tr>"
        )

    report = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA Phone Intelligence</title><style>body{{margin:0;padding:20px;background:#0b0d0f;color:#edf2f5;font-family:system-ui}}main{{max-width:1300px;margin:auto}}.card{{background:#14191d;border:1px solid #293139;border-radius:18px;padding:18px;margin-bottom:16px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #293139;padding:10px;text-align:left}}th{{background:#1b2227}}a{{color:#69f0c0}}</style></head><body><main><div class="card"><h1>AURORA</h1><p>Номер: {html.escape(phone_data['e164'])}<br>Регион: {html.escape(phone_data['region'] or 'не определён')}<br>Локация: {html.escape(phone_data['location'] or 'не определена')}<br>Оператор: {html.escape(phone_data['carrier'] or 'не определён')}</p></div><table><thead><tr><th>№</th><th>Категория</th><th>Запрос</th><th>Поисковики</th></tr></thead><tbody>{''.join(rows)}</tbody></table></main></body></html>'''
    (output_dir / "report.html").write_text(report, encoding="utf-8")
    return summary
