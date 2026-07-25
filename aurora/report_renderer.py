from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    return html.escape(str(value)) if value not in (None, "") else "—"


STATUS_CLASS = {
    "confirmed": "confirmed",
    "partially_confirmed": "partially-confirmed",
    "weak_signal": "weak-signal",
    "conflict": "conflict",
    "insufficient": "insufficient",
}
UNAVAILABLE_STATUSES = {"CONFIGURATION_REQUIRED", "DISABLED"}


def _source_card(run: dict) -> str:
    details = "; ".join(run.get("warnings") or run.get("errors") or [])
    metadata = run.get("metadata") or {}
    counters = []
    if "pages_with_exact_phone" in metadata:
        counters.append(
            f"страниц с точным номером: {metadata['pages_with_exact_phone']}"
        )
    if "email_candidates" in metadata:
        counters.append(f"email-кандидатов: {metadata['email_candidates']}")
    if counters:
        details = "; ".join(filter(None, [details, ", ".join(counters)]))
    return (
        "<div class='source'>"
        f"<span>{esc(run['connector_id'])}</span>"
        f"<b class='{esc(run['status']).lower()}'>"
        f"{esc(run['status'])}</b>"
        f"<small>{esc(details)}</small>"
        "</div>"
    )


def render_report(case: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "aurora_case.json").write_text(
        json.dumps(case, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    inp = case["input"]
    summary = case["summary"]
    entities = case["entities"]
    evidence = case["evidence"]
    runs = case["connector_runs"]
    rejected = case["rejected_candidates"]
    verification = summary.get("context_verification", [])
    deep_stats = summary.get("deep_public", {})

    entity_cards = []
    for entity in entities:
        for claim in entity.get("claims", []):
            entity_cards.append(
                "<article class='item'>"
                "<div>"
                f"<span class='tag'>{esc(entity['type'])}</span>"
                f"<h3>{esc(claim['field'])}: {esc(claim['value'])}</h3>"
                f"<p>{esc(claim.get('reasoning_summary'))}</p>"
                "</div>"
                "<div class='claim-score'>"
                f"<b>{esc(claim.get('verification_status'))}</b>"
                f"<small>{esc(claim.get('confidence'))}% · "
                f"{esc(claim.get('independent_source_count'))} "
                "независимых источника</small>"
                "</div>"
                "</article>"
            )

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

    evidence_html = "".join(
        "<article class='evidence'>"
        f"<a href='{esc(item.get('source_url'))}' "
        "target='_blank' rel='noreferrer'>"
        f"{esc(item.get('title') or item.get('source'))}</a>"
        f"<p>{esc(item.get('excerpt'))}</p>"
        "<small>"
        f"{esc(item.get('source'))} · надёжность "
        f"{esc(item.get('reliability'))} · "
        f"{'прямое совпадение' if item.get('direct_match') else 'косвенный сигнал'}"
        "</small>"
        "</article>"
        for item in evidence[:40]
    )

    active_runs = [
        run for run in runs if run.get("status") not in UNAVAILABLE_STATUSES
    ]
    unavailable_runs = [
        run for run in runs if run.get("status") in UNAVAILABLE_STATUSES
    ]
    active_run_html = "".join(_source_card(run) for run in active_runs)
    unavailable_run_html = "".join(_source_card(run) for run in unavailable_runs)

    rejected_html = "".join(
        f"<li><b>{esc(item['kind'])}</b>: {esc(item['value'])} — "
        f"{esc(item['reason'])}</li>"
        for item in rejected[:80]
    )

    verification_section = (
        "<section class='card'>"
        "<h2>Проверка введённого контекста</h2>"
        "<p class='muted'>Введённые пользователем данные не считаются "
        "доказанными автоматически. Для каждого поля показаны независимые "
        "подтверждения, слабые сигналы или противоречия.</p>"
        "<div class='table-wrap'><table>"
        "<thead><tr>"
        "<th>Поле</th><th>Указано</th><th>Статус</th>"
        "<th>Уверенность</th><th>Источники</th><th>Основание</th>"
        "</tr></thead>"
        f"<tbody>{''.join(verification_rows)}</tbody>"
        "</table></div></section>"
        if verification_rows
        else ""
    )

    deep_section = (
        "<section class='card'>"
        "<h2>Глубокая проверка публичных страниц</h2>"
        "<div class='grid'>"
        "<div class='fact'><span>Страницы с точным номером</span>"
        f"<strong>{esc(deep_stats.get('pages_with_exact_phone', 0))}</strong></div>"
        "<div class='fact'><span>Email-кандидаты на этих страницах</span>"
        f"<strong>{esc(deep_stats.get('email_candidates', 0))}</strong></div>"
        "</div>"
        "<p class='muted'>AURORA открывает доступные результаты поиска и "
        "учитывает сущности только там, где номер присутствует непосредственно "
        "в тексте публичной страницы.</p>"
        "</section>"
    )

    unavailable_section = (
        "<details>"
        "<summary>Источники, которые пока не подключены</summary>"
        "<p class='muted'>Они не участвовали в результате и не должны "
        "восприниматься как проверенные.</p>"
        f"{unavailable_run_html}"
        "</details>"
        if unavailable_run_html
        else ""
    )

    html_doc = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AURORA report</title>
<style>
:root{{
  --background:#0D1113;
  --surface:#141A1D;
  --surfaceElevated:#192125;
  --border:#2A3338;
  --textPrimary:#F3F5F6;
  --textSecondary:#9BA8AE;
  --accent:#EF6F2E;
  --success:#58D6A9;
  --warning:#F2C14E;
  --danger:#FF6B6B;
  --info:#7BB7FF;
}}
*{{box-sizing:border-box}}
body{{
  margin:0;
  background:var(--background);
  color:var(--textPrimary);
  font-family:Inter,system-ui,sans-serif;
}}
main{{max-width:1180px;margin:auto;padding:18px 14px 48px}}
header,.card,.item,.evidence{{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:22px;
  padding:18px;
  margin:12px 0;
}}
header{{
  background:linear-gradient(135deg,var(--surfaceElevated),var(--surface));
  padding:22px;
}}
h1,h2,h3{{margin:.1rem 0 .7rem}}
p,small,.muted{{color:var(--textSecondary);line-height:1.5}}
a{{color:var(--accent);overflow-wrap:anywhere}}
.grid{{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:12px;
}}
.fact{{
  background:var(--surfaceElevated);
  border:1px solid var(--border);
  border-radius:16px;
  padding:14px;
}}
.fact span,.tag{{color:var(--textSecondary);font-size:12px}}
.fact strong{{display:block;margin-top:5px;font-size:18px}}
.item{{
  display:flex;
  justify-content:space-between;
  gap:18px;
  align-items:flex-start;
}}
.claim-score{{text-align:right;min-width:180px}}
.claim-score b{{display:block;color:var(--success)}}
.claim-score small{{display:block;margin-top:5px}}
.configuration_required,.timeout,.rate_limited{{color:var(--warning)}}
.error{{color:var(--danger)}}
.source{{
  display:grid;
  grid-template-columns:1fr auto;
  gap:6px;
  background:var(--surfaceElevated);
  border:1px solid var(--border);
  border-radius:14px;
  padding:12px;
  margin:8px 0;
}}
.source small{{grid-column:1/-1;overflow-wrap:anywhere}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;min-width:900px}}
th,td{{
  text-align:left;
  vertical-align:top;
  padding:12px;
  border-bottom:1px solid var(--border);
}}
th{{color:var(--textSecondary);font-size:12px;font-weight:600}}
.status{{
  display:inline-block;
  padding:5px 9px;
  border-radius:999px;
  font-size:12px;
  font-weight:700;
  white-space:nowrap;
}}
.status.confirmed{{color:var(--success);background:rgba(88,214,169,.12)}}
.status.partially-confirmed{{color:var(--info);background:rgba(123,183,255,.12)}}
.status.weak-signal{{color:var(--warning);background:rgba(242,193,78,.12)}}
.status.conflict{{color:var(--danger);background:rgba(255,107,107,.12)}}
.status.insufficient{{color:var(--textSecondary);background:rgba(155,168,174,.10)}}
.conflict-note{{margin-top:7px;color:var(--danger);font-size:12px}}
details{{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:18px;
  padding:14px;
  margin:12px 0;
}}
summary{{cursor:pointer;color:var(--accent);min-height:44px}}
ul{{padding-left:20px}}
@media(max-width:640px){{
  main{{padding:10px 8px 32px}}
  header,.card,.item,.evidence{{border-radius:16px;padding:14px}}
  .grid{{grid-template-columns:1fr}}
  .item{{display:block}}
  .claim-score{{text-align:left;min-width:0;margin-top:12px}}
  button,a{{min-height:44px}}
}}
</style>
</head>
<body>
<main>
<header>
  <p class="muted">Исходный запрос</p>
  <h1>{esc(inp.get('raw'))}</h1>
  <p>{esc(summary['headline'])}</p>
  <div class="grid">
    <div class="fact"><span>Тип</span><strong>{esc(inp.get('type'))}</strong></div>
    <div class="fact"><span>Нормализация</span><strong>{esc(inp.get('normalized'))}</strong></div>
    <div class="fact"><span>ФИО</span><strong>{esc(summary['fio'])}</strong></div>
    <div class="fact"><span>Email</span><strong>{esc(summary['email'])}</strong></div>
  </div>
</header>
{deep_section}
{verification_section}
<section class='card'>
  <h2>Подтверждённые и проверяемые сущности</h2>
  {''.join(entity_cards) or '<p class="muted">Надёжные связанные сущности не подтверждены.</p>'}
</section>
<section class='card'>
  <h2>Как читать результат</h2>
  <p>Прямые совпадения и независимые источники учитываются отдельно от
  SEO-заголовков. Один источник не превращает гипотезу в установленный факт.</p>
</section>
<section class='card'>
  <h2>Карта связей</h2>
  <p class='muted'>Исходный идентификатор связан только с сущностями,
  для которых сохранены доказательства и контекст.</p>
</section>
<section class='card'>
  <h2>Доказательства</h2>
  {evidence_html or '<p class="muted">Доказательства не найдены.</p>'}
</section>
<section class='card'>
  <h2>Источники, реально участвовавшие в проверке</h2>
  {active_run_html or '<p class="muted">Нет успешно запущенных источников.</p>'}
</section>
{unavailable_section}
<details>
  <summary>Отброшенные совпадения — технический блок</summary>
  <ul>{rejected_html or '<li>Нет отброшенных кандидатов.</li>'}</ul>
</details>
</main>
</body>
</html>"""

    (output_dir / "report.html").write_text(html_doc, encoding="utf-8")
    (output_dir / "person_card.html").write_text(
        html_doc, encoding="utf-8"
    )
