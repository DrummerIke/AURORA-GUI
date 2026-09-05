from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    return html.escape(str(value)) if value not in (None, "") else "—"


UNAVAILABLE_STATUSES = {"CONFIGURATION_REQUIRED", "DISABLED"}
STATUS_CLASS = {
    "confirmed": "confirmed",
    "partially_confirmed": "partially-confirmed",
    "weak_signal": "weak-signal",
    "conflict": "conflict",
    "insufficient": "insufficient",
}


def _source_card(run: dict) -> str:
    details = "; ".join(run.get("warnings") or run.get("errors") or [])
    metadata = run.get("metadata") or {}
    counters = []
    labels = {
        "pages_with_exact_phone": "страниц с точным номером",
        "person_candidates": "ФИО-кандидатов",
        "email_candidates": "email-кандидатов",
        "organization_candidates": "организаций",
        "username_candidates": "публичных профилей",
    }
    for key, label in labels.items():
        if key in metadata:
            counters.append(f"{label}: {metadata[key]}")
    if counters:
        details = "; ".join(filter(None, [details, ", ".join(counters)]))
    return (
        "<div class='source'>"
        f"<span>{esc(run.get('connector_id'))}</span>"
        f"<b class='{esc(run.get('status', '')).lower()}'>"
        f"{esc(run.get('status'))}</b>"
        f"<small>{esc(details)}</small>"
        "</div>"
    )


def _claim_card(entity: dict, claim: dict) -> str:
    evidence_count = len(claim.get("evidence_ids") or [])
    return (
        "<article class='finding'>"
        "<div>"
        f"<span class='tag'>{esc(entity.get('type'))}</span>"
        f"<h3>{esc(claim.get('value'))}</h3>"
        f"<p>{esc(claim.get('reasoning_summary'))}</p>"
        "</div>"
        "<div class='claim-score'>"
        f"<b>{esc(claim.get('verification_status'))}</b>"
        f"<small>{esc(claim.get('confidence'))}% · "
        f"{esc(claim.get('independent_source_count'))} независимых источника · "
        f"{evidence_count} доказательств</small>"
        "</div>"
        "</article>"
    )


def render_report(case: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "aurora_case.json").write_text(
        json.dumps(case, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    inp = case.get("input", {})
    summary = case.get("summary", {})
    entities = case.get("entities", [])
    evidence = case.get("evidence", [])
    runs = case.get("connector_runs", [])
    rejected = case.get("rejected_candidates", [])
    verification = summary.get("context_verification", [])
    deep_stats = summary.get("deep_public", {})

    useful_entities = [
        entity
        for entity in entities
        if entity.get("type") not in {"phone", "input"}
    ]
    finding_cards = "".join(
        _claim_card(entity, claim)
        for entity in useful_entities
        for claim in entity.get("claims", [])
    )

    if finding_cards:
        result_html = finding_cards
        result_note = (
            "Ниже показаны не места поиска, а сущности, которые удалось связать "
            "с исходным номером через сохранённые публичные доказательства."
        )
    else:
        result_html = (
            "<div class='empty-result'>"
            "<strong>Связанные ФИО, email, организация или публичный профиль не найдены.</strong>"
            "<p>Это означает, что в доступных индексируемых публичных источниках "
            "AURORA не получила прямого совпадения, достаточного для вывода сущности. "
            "Список поисковиков ниже не считается результатом.</p>"
            "</div>"
        )
        result_note = "Пустой результат не заменяется списком источников."

    verification_rows = []
    for item in verification:
        css_class = STATUS_CLASS.get(item.get("status"), "insufficient")
        conflict = (
            f"<div class='conflict-note'>Альтернативный кандидат: "
            f"{esc(item.get('conflicting_value'))}</div>"
            if item.get("conflicting_value")
            else ""
        )
        verification_rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('label'))}</strong></td>"
            f"<td>{esc(item.get('provided_value'))}</td>"
            f"<td><span class='status {css_class}'>"
            f"{esc(item.get('status_label'))}</span>{conflict}</td>"
            f"<td>{esc(item.get('confidence'))}%</td>"
            f"<td>{esc(item.get('independent_source_count'))}</td>"
            f"<td>{esc(item.get('reasoning'))}</td>"
            "</tr>"
        )

    verification_section = (
        "<section class='card'>"
        "<h2>Проверка введённого контекста</h2>"
        "<div class='table-wrap'><table>"
        "<thead><tr><th>Поле</th><th>Указано</th><th>Статус</th>"
        "<th>Уверенность</th><th>Источники</th><th>Основание</th></tr></thead>"
        f"<tbody>{''.join(verification_rows)}</tbody></table></div></section>"
        if verification_rows
        else ""
    )

    evidence_html = "".join(
        "<article class='evidence'>"
        f"<a href='{esc(item.get('source_url'))}' target='_blank' rel='noreferrer'>"
        f"{esc(item.get('title') or item.get('source'))}</a>"
        f"<p>{esc(item.get('excerpt'))}</p>"
        "<small>"
        f"{esc(item.get('source'))} · надёжность {esc(item.get('reliability'))} · "
        f"{'прямое совпадение' if item.get('direct_match') else 'косвенный сигнал'}"
        "</small>"
        "</article>"
        for item in evidence[:50]
        if item.get("source_url") or item.get("source_type") == "public_page"
    )

    active_runs = [run for run in runs if run.get("status") not in UNAVAILABLE_STATUSES]
    unavailable_runs = [run for run in runs if run.get("status") in UNAVAILABLE_STATUSES]
    active_run_html = "".join(_source_card(run) for run in active_runs)
    unavailable_run_html = "".join(_source_card(run) for run in unavailable_runs)

    rejected_html = "".join(
        f"<li><b>{esc(item.get('kind'))}</b>: {esc(item.get('value'))} — "
        f"{esc(item.get('reason'))}</li>"
        for item in rejected[:80]
    )

    html_doc = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AURORA report</title>
<style>
:root{{--background:#0D1113;--surface:#141A1D;--surface2:#192125;--border:#2A3338;--text:#F3F5F6;--muted:#9BA8AE;--accent:#EF6F2E;--success:#58D6A9;--warning:#F2C14E;--danger:#FF6B6B;--info:#7BB7FF}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--background);color:var(--text);font-family:Inter,system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:18px 14px 48px}}header,.card,.finding,.evidence{{background:var(--surface);border:1px solid var(--border);border-radius:22px;padding:18px;margin:12px 0}}
header{{background:linear-gradient(135deg,var(--surface2),var(--surface));padding:22px}}h1,h2,h3{{margin:.1rem 0 .7rem}}p,small,.muted{{color:var(--muted);line-height:1.5}}a{{color:var(--accent);overflow-wrap:anywhere}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.fact{{background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:14px}}.fact span,.tag{{color:var(--muted);font-size:12px}}.fact strong{{display:block;margin-top:5px;font-size:18px}}
.finding{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}.claim-score{{text-align:right;min-width:210px}}.claim-score b{{display:block;color:var(--success)}}.claim-score small{{display:block;margin-top:5px}}
.empty-result{{background:var(--surface2);border:1px dashed var(--border);border-radius:16px;padding:18px}}.empty-result strong{{font-size:18px}}.source{{display:grid;grid-template-columns:1fr auto;gap:6px;background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:12px;margin:8px 0}}.source small{{grid-column:1/-1;overflow-wrap:anywhere}}
.configuration_required,.timeout,.rate_limited{{color:var(--warning)}}.error{{color:var(--danger)}}.ok{{color:var(--success)}}
.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:850px}}th,td{{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--border)}}th{{color:var(--muted);font-size:12px}}
.status{{display:inline-block;padding:5px 9px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}}.status.confirmed{{color:var(--success)}}.status.partially-confirmed{{color:var(--info)}}.status.weak-signal{{color:var(--warning)}}.status.conflict{{color:var(--danger)}}.status.insufficient{{color:var(--muted)}}.conflict-note{{margin-top:7px;color:var(--danger);font-size:12px}}
details{{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:14px;margin:12px 0}}summary{{cursor:pointer;color:var(--accent);min-height:44px}}ul{{padding-left:20px}}
@media(max-width:640px){{main{{padding:10px 8px 32px}}header,.card,.finding,.evidence{{border-radius:16px;padding:14px}}.grid{{grid-template-columns:1fr 1fr}}.finding{{display:block}}.claim-score{{text-align:left;min-width:0;margin-top:12px}}}}
</style>
</head>
<body><main>
<header>
<p class="muted">Исходный запрос</p><h1>{esc(inp.get('raw'))}</h1><p>{esc(summary.get('headline'))}</p>
<div class="grid">
<div class="fact"><span>Тип</span><strong>{esc(inp.get('type'))}</strong></div>
<div class="fact"><span>ФИО</span><strong>{esc(summary.get('fio'))}</strong></div>
<div class="fact"><span>Email</span><strong>{esc(summary.get('email'))}</strong></div>
<div class="fact"><span>Полезных сущностей</span><strong>{esc(deep_stats.get('useful_entities', len(useful_entities)))}</strong></div>
</div>
</header>
<section class='card'><h2>Что реально найдено</h2><p class='muted'>{esc(result_note)}</p>{result_html}</section>
<section class='card'><h2>Глубокая проверка публичных страниц</h2><div class='grid'>
<div class='fact'><span>Страницы с точным номером</span><strong>{esc(deep_stats.get('pages_with_exact_phone', 0))}</strong></div>
<div class='fact'><span>ФИО-кандидаты</span><strong>{esc(deep_stats.get('person_candidates', 0))}</strong></div>
<div class='fact'><span>Email</span><strong>{esc(deep_stats.get('email_candidates', 0))}</strong></div>
<div class='fact'><span>Организации</span><strong>{esc(deep_stats.get('organization_candidates', 0))}</strong></div>
<div class='fact'><span>Публичные профили</span><strong>{esc(deep_stats.get('username_candidates', 0))}</strong></div>
</div></section>
{verification_section}
<details open><summary>Доказательства и первоисточники</summary>{evidence_html or '<p class="muted">Публичные первоисточники с точным совпадением не найдены.</p>'}</details>
<details><summary>Технически отработавшие источники</summary>{active_run_html or '<p class="muted">Нет отработавших источников.</p>'}</details>
{('<details><summary>Источники, которые не были подключены</summary><p class="muted">Они не участвовали в результате.</p>' + unavailable_run_html + '</details>') if unavailable_run_html else ''}
<details><summary>Отброшенные совпадения</summary><ul>{rejected_html or '<li>Нет отброшенных кандидатов.</li>'}</ul></details>
</main></body></html>"""

    (output_dir / "report.html").write_text(html_doc, encoding="utf-8")
    (output_dir / "person_card.html").write_text(html_doc, encoding="utf-8")
