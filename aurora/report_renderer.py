from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

ENTITY_LABELS = {
    "person": "Личность",
    "phone": "Телефон",
    "email": "Email",
    "username": "Псевдоним",
    "social_profile": "Публичный профиль",
    "organization": "Организация",
    "domain": "Домен",
    "url": "Страница",
    "ip_address": "IP-адрес",
    "location": "Локация",
}
STATUS_CLASS = {
    "Подтверждено": "confirmed",
    "Вероятно": "probable",
    "Гипотеза": "hypothesis",
    "Не подтверждено": "unconfirmed",
    "Конфликт данных": "conflict",
}


def esc(value: Any) -> str:
    return html.escape(str(value)) if value not in (None, "") else "—"


def _claims(case: dict, entity_type: str) -> list[dict]:
    result = []
    for entity in case.get("entities", []):
        if entity.get("type") != entity_type:
            continue
        for claim in entity.get("claims", []):
            result.append({**claim, "entity_id": entity.get("id", "")})
    return sorted(result, key=lambda claim: (-int(claim.get("confidence", 0)), claim.get("value", "")))


def build_report_view(case: dict) -> dict:
    inp = case["input"]
    people = _claims(case, "person")
    organizations = _claims(case, "organization")
    contacts = _claims(case, "phone") + _claims(case, "email") + _claims(case, "username")
    profiles = _claims(case, "social_profile")
    runs = case.get("connector_runs", [])
    successful = sum(run.get("status") == "OK" for run in runs)
    unavailable = sum(run.get("status") in {"ERROR", "TIMEOUT", "RATE_LIMITED"} for run in runs)
    configuration = sum(run.get("status") == "CONFIGURATION_REQUIRED" for run in runs)

    if people:
        subject = people[0]["value"]
        identity_status = people[0].get("verification_status", "Вероятно")
        headline = f"Публичная связь номера с {subject} подтверждается сохранёнными доказательствами."
    elif inp.get("claimed_name"):
        subject = inp["claimed_name"]
        identity_status = "Не подтверждено"
        headline = "Заявленное ФИО не получило достаточного независимого подтверждения."
    else:
        subject = "Личность не установлена"
        identity_status = "Не подтверждено"
        headline = "Надёжных данных для установления личности по этому идентификатору не найдено."

    conclusions = []
    if people:
        top = people[0]
        conclusions.append(f"ФИО: {top['value']} — {top.get('verification_status', 'Вероятно').lower()}, независимых подтверждений: {top.get('independent_source_count', 0)}.")
    else:
        conclusions.append("ФИО: не подтверждено; заголовки, формы и телефонные каталоги отброшены.")
    if organizations:
        conclusions.append("Организации: " + ", ".join(claim["value"] for claim in organizations[:3]) + ".")
    else:
        conclusions.append("Связь с организацией: не подтверждена.")
    email_claims = _claims(case, "email")
    conclusions.append("Email: " + (", ".join(claim["value"] for claim in email_claims[:3]) if email_claims else "не подтвержден") + ".")
    if unavailable:
        conclusions.append(f"Источники с ошибкой или timeout: {unavailable}; вывод может быть неполным.")

    return {
        "subject": subject,
        "identity_status": identity_status,
        "headline": headline,
        "conclusions": conclusions,
        "people": people,
        "organizations": organizations,
        "contacts": contacts,
        "profiles": profiles,
        "relationships": case.get("relationships", []),
        "evidence": case.get("evidence", []),
        "rejected": case.get("rejected_candidates", []),
        "runs": runs,
        "source_stats": {"successful": successful, "unavailable": unavailable, "configuration": configuration, "total": len(runs)},
    }


def _claim_card(claim: dict, label: str) -> str:
    status = claim.get("verification_status", "Гипотеза")
    breakdown = claim.get("confidence_breakdown") or {}
    breakdown_html = ""
    if breakdown:
        breakdown_html = (
            "<details class='score-details'><summary>Почему такой уровень</summary>"
            f"<p>Надёжность источника: {esc(breakdown.get('source_reliability'))}; "
            f"контекст: {esc(breakdown.get('context_strength'))}; независимое подтверждение: {esc(breakdown.get('independent_confirmation'))}; "
            f"штрафы: {esc(breakdown.get('penalties') or 'нет')}.</p></details>"
        )
    return (
        "<article class='claim'>"
        f"<div><span class='eyebrow'>{esc(label)}</span><h3>{esc(claim.get('value'))}</h3>"
        f"<p>{esc(claim.get('reasoning_summary'))}</p>"
        f"<small>{esc(claim.get('independent_source_count', 0))} независимых подтверждений · {esc(claim.get('source_count', 0))} evidence</small>{breakdown_html}</div>"
        f"<span class='status {STATUS_CLASS.get(status, 'hypothesis')}'>{esc(status)}</span></article>"
    )


def _section(title: str, body: str, empty: str) -> str:
    return f"<section class='panel'><div class='section-title'><h2>{esc(title)}</h2></div>{body or f'<div class="empty">{esc(empty)}</div>'}</section>"


def render_report(case: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "aurora_case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    view = build_report_view(case)
    inp = case["input"]

    people_html = "".join(_claim_card(claim, "ФИО") for claim in view["people"])
    org_html = "".join(_claim_card(claim, "Компания / организация") for claim in view["organizations"])
    contact_html = "".join(_claim_card(claim, ENTITY_LABELS.get(claim.get("field"), claim.get("field", "Контакт"))) for claim in view["contacts"])
    profile_html = "".join(_claim_card(claim, "Публичный профиль") for claim in view["profiles"])
    conclusions = "".join(f"<li>{esc(item)}</li>" for item in view["conclusions"])

    evidence_by_id = {e.get("id"): e for e in view["evidence"]}
    linked_ids = []
    for entity in case.get("entities", []):
        for claim in entity.get("claims", []):
            linked_ids.extend(claim.get("evidence_ids", []))
    evidence_items = [evidence_by_id[eid] for eid in dict.fromkeys(linked_ids) if eid in evidence_by_id]
    evidence_html = "".join(
        f"<article class='evidence'><div><span class='eyebrow'>{esc(item.get('source_type'))}</span><h3>{esc(item.get('title') or item.get('source'))}</h3>"
        f"<p>{esc(item.get('excerpt'))}</p><small>{esc(item.get('source'))} · получено {esc(item.get('retrieved_at'))}</small></div>"
        f"<a class='source-link' href='{esc(item.get('source_url'))}' target='_blank' rel='noopener noreferrer'>Первоисточник ↗</a></article>"
        for item in evidence_items[:50]
    )
    run_html = "".join(
        f"<div class='connector'><span>{esc(run.get('connector_id'))}</span><b class='{esc(run.get('status', '')).lower()}'>{esc(run.get('status'))}</b>"
        f"<small>{esc('; '.join(run.get('warnings') or run.get('errors') or []))}</small></div>"
        for run in view["runs"]
    )
    rejected_html = "".join(
        f"<li><b>{esc(item.get('kind'))}</b>: {esc(item.get('value'))} — {esc(item.get('reason'))}</li>"
        for item in view["rejected"][:100]
    )
    stats = view["source_stats"]
    status_class = STATUS_CLASS.get(view["identity_status"], "unconfirmed")

    document = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA — сводный отчёт</title><style>
:root{{--bg:#0D1113;--surface:#141A1D;--elev:#192125;--border:#2A3338;--text:#F3F5F6;--muted:#9BA8AE;--accent:#EF6F2E;--success:#58D6A9;--warning:#F2C14E;--danger:#FF6B6B}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 80% 0,#262018 0,transparent 30%),var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:20px 14px 56px}}.hero,.panel{{background:rgba(20,26,29,.97);border:1px solid var(--border);border-radius:22px;padding:22px;margin:14px 0}}.hero{{background:linear-gradient(135deg,#1d2426,#141a1d)}}.topline,.section-title,.claim,.evidence,.connector{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}}.eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}h1{{font-size:clamp(27px,5vw,44px);line-height:1.08;margin:10px 0}}h2{{font-size:19px;margin:0}}h3{{margin:5px 0;font-size:17px}}p,small{{color:var(--muted)}}.status{{display:inline-flex;padding:7px 10px;border-radius:999px;font-size:12px;font-weight:800;white-space:nowrap}}.confirmed{{color:var(--success);background:#142d28}}.probable{{color:#b6efd9;background:#19312c}}.hypothesis,.configuration_required,.timeout,.rate_limited{{color:var(--warning);background:#302817}}.unconfirmed{{color:var(--muted);background:#232a2e}}.conflict,.error{{color:var(--danger);background:#321c1f}}.summary-grid{{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-top:18px}}.summary-card{{background:var(--elev);border:1px solid var(--border);border-radius:17px;padding:16px}}ul{{margin:8px 0;padding-left:20px}}li{{margin:7px 0}}.claim,.evidence{{padding:16px 0;border-top:1px solid var(--border)}}.claim:first-of-type,.evidence:first-of-type{{border-top:0}}.claim>div,.evidence>div{{min-width:0}}.source-link{{color:var(--accent);text-decoration:none;white-space:nowrap}}.empty{{color:var(--muted);background:var(--elev);border:1px dashed var(--border);border-radius:15px;padding:17px;margin-top:15px}}.connector{{display:grid;grid-template-columns:1fr auto;gap:5px;padding:11px 0;border-top:1px solid var(--border)}}.connector small{{grid-column:1/-1;overflow-wrap:anywhere}}.ok{{color:var(--success)}}details{{margin-top:10px}}summary{{color:var(--accent);cursor:pointer;min-height:36px}}.technical{{background:#101517}}a{{overflow-wrap:anywhere}}@media (max-width:680px){{main{{padding:8px 8px 34px}}.hero,.panel{{border-radius:16px;padding:15px}}.summary-grid{{grid-template-columns:1fr}}.topline,.claim,.evidence{{display:block}}.status,.source-link{{margin-top:10px}}.source-link{{display:inline-block;min-height:44px;padding-top:10px}}h1{{font-size:29px}}}}
</style></head><body><main><header class="hero"><div class="topline"><span class="eyebrow">AURORA · сводный отчёт</span><span class="status {status_class}">{esc(view['identity_status'])}</span></div><h1>{esc(view['subject'])}</h1><p>{esc(view['headline'])}</p><div class="summary-grid"><div class="summary-card"><span class="eyebrow">Главные выводы</span><ul>{conclusions}</ul></div><div class="summary-card"><span class="eyebrow">Покрытие</span><h3>{stats['successful']} из {stats['total']} источников ответили</h3><p>{stats['configuration']} требуют настройки · {stats['unavailable']} недоступны</p></div></div><p><small>Запрос: {esc(inp.get('normalized'))} · цель: {esc(case.get('purpose'))} · законное основание: {'подтверждено' if case.get('consent') else 'не подтверждено'}</small></p></header>
{_section('Личность', people_html, 'ФИО не подтверждено. Система не подменяет отсутствие данных поисковыми заголовками.')}
{_section('Компании и профессиональные связи', org_html, 'Подтверждённых организаций или профессиональных связей не найдено.')}
{_section('Контактные данные', contact_html, 'Дополнительные подтверждённые контакты не найдены.')}
{_section('Публичные профили', profile_html, 'Публичные профили, доказанно связанные с исходным идентификатором, не найдены.')}
{_section('Доказательства выводов', evidence_html, 'Для подтверждённых выводов нет сохранённых доказательств.')}
<section class="panel"><h2>Ограничения отчёта</h2><p>Отчёт отражает только доступные публичные данные на момент проверки. Совпадение не заменяет удостоверение личности, согласие кандидата и ручную проверку первоисточника. Отсутствие сведений не является негативным сигналом. AURORA не делает автоматических кадровых решений.</p></section>
<details class="panel technical"><summary>Техническое состояние источников</summary>{run_html or '<p>Нет запусков.</p>'}</details>
<details class="panel technical"><summary>Отброшенные кандидаты</summary><ul>{rejected_html or '<li>Нет отброшенных кандидатов.</li>'}</ul></details>
</main></body></html>'''
    (output_dir / "report.html").write_text(document, encoding="utf-8")
    (output_dir / "person_card.html").write_text(document, encoding="utf-8")
