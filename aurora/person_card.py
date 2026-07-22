from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

LABELS = {
    "person": "ФИО",
    "organization": "Организация",
    "email": "Email",
    "social_profile": "Публичный профиль",
    "listing": "Объявление",
    "public_address": "Публичный адрес",
    "document": "Документ",
    "username": "Username",
    "domain": "Домен",
}


def _dedupe(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for item in values:
        kind = str(item.get("kind", "unknown"))
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        key = (kind, value.casefold())
        current = best.get(key)
        if current is None or int(item.get("confidence", 0)) > int(current.get("confidence", 0)):
            best[key] = item
    return sorted(best.values(), key=lambda x: (-int(x.get("confidence", 0)), x.get("kind", "")))


def build_person_card(phone_report: dict, search_result: dict, output_dir: Path) -> dict:
    phone = phone_report.get("phone", {})
    findings = _dedupe(list(search_result.get("findings", [])))

    grouped: dict[str, list[dict]] = {}
    for item in findings:
        grouped.setdefault(item.get("kind", "unknown"), []).append(item)

    people = grouped.get("person", [])
    primary_name = people[0]["value"] if people else None
    primary_confidence = int(people[0].get("confidence", 0)) if people else 0

    card = {
        "phone": phone.get("e164") or phone_report.get("input"),
        "national": phone.get("national"),
        "operator": phone.get("carrier"),
        "region": phone.get("location") or phone.get("region"),
        "country": phone.get("country"),
        "type": phone.get("type"),
        "possible_name": primary_name,
        "name_confidence": primary_confidence,
        "entities": grouped,
        "source_count": len(search_result.get("results", [])),
        "candidate_count": len(search_result.get("candidates", [])),
        "search_seconds": search_result.get("elapsed_seconds"),
        "warning": (
            "Карточка собрана только из открытых источников. Совпадение не доказывает "
            "личность текущего владельца номера. Адрес может относиться к организации, "
            "объявлению или месту оказания услуги."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "person_card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "person_card.html").write_text(
        render_person_card(card), encoding="utf-8"
    )
    return card


def render_person_card(card: dict) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value)) if value not in (None, "") else "—"

    identity = (
        f'<div class="hero-name">{esc(card.get("possible_name") or "Личность не установлена")}</div>'
        f'<div class="confidence">Уверенность ФИО: {int(card.get("name_confidence", 0))}%</div>'
    )

    summary = "".join([
        f'<div class="fact"><span>Телефон</span><strong>{esc(card.get("phone"))}</strong></div>',
        f'<div class="fact"><span>Оператор</span><strong>{esc(card.get("operator"))}</strong></div>',
        f'<div class="fact"><span>Регион</span><strong>{esc(card.get("region"))}</strong></div>',
        f'<div class="fact"><span>Страна</span><strong>{esc(card.get("country"))}</strong></div>',
        f'<div class="fact"><span>Тип номера</span><strong>{esc(card.get("type"))}</strong></div>',
    ])

    sections = []
    entities = card.get("entities", {})
    order = [
        "person", "organization", "email", "username", "social_profile",
        "listing", "document", "domain", "public_address",
    ]
    for kind in order:
        items = entities.get(kind, [])
        if not items:
            continue
        rows = []
        for item in items[:20]:
            value = esc(item.get("value"))
            confidence = int(item.get("confidence", 0))
            sources = item.get("sources", [])
            links = []
            for source in sources[:4]:
                url = source.get("url")
                title = source.get("title") or source.get("domain") or "Источник"
                if url:
                    links.append(f'<a href="{html.escape(url)}" target="_blank">{html.escape(title)}</a>')
            source_html = " · ".join(links) or "Источник не сохранён"
            rows.append(
                '<div class="entity">'
                f'<div><strong>{value}</strong><div class="sources">{source_html}</div></div>'
                f'<div class="score">{confidence}%</div>'
                '</div>'
            )
        sections.append(
            f'<section><h2>{html.escape(LABELS.get(kind, kind))}</h2>{"".join(rows)}</section>'
        )

    if not sections:
        sections.append(
            '<section><h2>Открытых связей не найдено</h2>'
            '<p class="muted">У номера может отсутствовать публичный цифровой след.</p></section>'
        )

    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AURORA — карточка</title>
<style>
:root{{--bg:#0b0d0f;--panel:#151a1e;--line:#293139;--text:#edf2f5;--muted:#8d9aa4;--accent:#69f0c0;--blue:#86a8ff;--gold:#ffd27d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,sans-serif}}main{{max-width:980px;margin:auto;padding:20px 14px 50px}}header,section{{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:18px;margin-bottom:14px}}h1{{margin:0 0 16px;letter-spacing:.12em}}h2{{font-size:16px;margin:0 0 14px}}.hero-name{{font-size:26px;font-weight:800}}.confidence{{color:var(--gold);font-size:12px;margin-top:5px}}.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:18px}}.fact{{background:#0f1316;border:1px solid var(--line);border-radius:14px;padding:12px}}.fact span{{display:block;color:var(--muted);font-size:11px;margin-bottom:5px}}.entity{{display:flex;justify-content:space-between;gap:15px;padding:13px 0;border-top:1px solid var(--line)}}.entity:first-of-type{{border-top:0}}.score{{color:var(--accent);font-weight:800;white-space:nowrap}}.sources{{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.5}}a{{color:var(--blue);text-decoration:none}}.warning,.muted{{color:var(--muted);font-size:12px;line-height:1.55}}
</style></head><body><main>
<header><h1>AURORA</h1>{identity}<div class="facts">{summary}</div><p class="warning">{esc(card.get("warning"))}</p></header>
{''.join(sections)}
</main></body></html>'''
