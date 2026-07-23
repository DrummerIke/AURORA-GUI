from __future__ import annotations
import html, json
from pathlib import Path
from typing import Any

def esc(v:Any)->str: return html.escape(str(v)) if v not in (None,"") else "—"
def render_report(case:dict, output_dir:Path)->None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'aurora_case.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
    inp=case['input']; summary=case['summary']; entities=case['entities']; evidence=case['evidence']; runs=case['connector_runs']; rejected=case['rejected_candidates']
    entity_cards=[]
    for ent in entities:
        for cl in ent.get('claims',[]):
            entity_cards.append(f"<article class='item'><div><span class='tag'>{esc(ent['type'])}</span><h3>{esc(cl['field'])}: {esc(cl['value'])}</h3><p>{esc(cl.get('reasoning_summary'))}</p></div><b>{esc(cl.get('verification_status'))}</b></article>")
    ev_html=''.join(f"<article class='evidence'><a href='{esc(e.get('source_url'))}' target='_blank' rel='noreferrer'>{esc(e.get('title') or e.get('source'))}</a><p>{esc(e.get('excerpt'))}</p><small>{esc(e.get('source'))} · reliability {esc(e.get('reliability'))}</small></article>" for e in evidence[:40])
    run_html=''.join(f"<div class='source'><span>{esc(r['connector_id'])}</span><b class='{esc(r['status']).lower()}'>{esc(r['status'])}</b><small>{esc('; '.join(r.get('warnings') or r.get('errors') or []))}</small></div>" for r in runs)
    rej_html=''.join(f"<li><b>{esc(x['kind'])}</b>: {esc(x['value'])} — {esc(x['reason'])}</li>" for x in rejected[:80])
    html_doc=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA report</title><style>
:root{{--background:#0D1113;--surface:#141A1D;--surfaceElevated:#192125;--border:#2A3338;--textPrimary:#F3F5F6;--textSecondary:#9BA8AE;--accent:#EF6F2E;--success:#58D6A9;--warning:#F2C14E;--danger:#FF6B6B}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--background);color:var(--textPrimary);font-family:Inter,system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:18px 14px 48px}}header,.card,.item,.evidence{{background:var(--surface);border:1px solid var(--border);border-radius:22px;padding:18px;margin:12px 0}}header{{background:linear-gradient(135deg,var(--surfaceElevated),var(--surface));padding:22px}}h1,h2,h3{{margin:.1rem 0 .7rem}}p,small,.muted{{color:var(--textSecondary);line-height:1.5}}a{{color:var(--accent);overflow-wrap:anywhere}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}.fact{{background:var(--surfaceElevated);border:1px solid var(--border);border-radius:16px;padding:14px}}.fact span,.tag{{color:var(--textSecondary);font-size:12px}}.fact strong{{display:block;margin-top:5px;font-size:18px}}.item{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}.item b,.ok{{color:var(--success)}}.configuration_required,.timeout,.rate_limited{{color:var(--warning)}}.error{{color:var(--danger)}}.source{{display:grid;grid-template-columns:1fr auto;gap:6px;background:var(--surfaceElevated);border:1px solid var(--border);border-radius:14px;padding:12px;margin:8px 0}}.source small{{grid-column:1/-1;overflow-wrap:anywhere}}details{{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:14px;margin:12px 0}}summary{{cursor:pointer;color:var(--accent);min-height:44px}}ul{{padding-left:20px}}@media(max-width:640px){{main{{padding:10px 8px 32px}}header,.card,.item,.evidence{{border-radius:16px;padding:14px}}.grid{{grid-template-columns:1fr}}.item{{display:block}}button,a{{min-height:44px}}}}
</style></head><body><main><header><p class="muted">Исходный запрос</p><h1>{esc(inp.get('raw'))}</h1><p>{esc(summary['headline'])}</p><div class="grid"><div class="fact"><span>Тип</span><strong>{esc(inp.get('type'))}</strong></div><div class="fact"><span>Нормализация</span><strong>{esc(inp.get('normalized'))}</strong></div><div class="fact"><span>ФИО</span><strong>{esc(summary['fio'])}</strong></div><div class="fact"><span>Email</span><strong>{esc(summary['email'])}</strong></div></div></header>
<section class='card'><h2>Подтвержденные сущности</h2>{''.join(entity_cards) or '<p class="muted">Надежные связанные сущности не подтверждены.</p>'}</section>
<section class='card'><h2>Наиболее важные сигналы</h2><p>Прямые совпадения и источники с API/локальной проверкой учитываются отдельно от SEO-заголовков. Одинаковая фиксированная оценка не используется.</p></section>
<section class='card'><h2>Карта связей</h2><p class='muted'>Исходный идентификатор связан только с сущностями, где сохранены доказательства и контекст.</p></section>
<section class='card'><h2>Хронология</h2><p class='muted'>Время получения доказательств указано в JSON-отчете.</p></section>
<section class='card'><h2>Доказательства</h2>{ev_html or '<p class="muted">Доказательства не найдены.</p>'}</section>
<section class='card'><h2>Проверенные источники</h2>{run_html}</section>
<details><summary>Отброшенные совпадения — технический блок</summary><ul>{rej_html or '<li>Нет отброшенных кандидатов.</li>'}</ul></details></main></body></html>'''
    (output_dir/'report.html').write_text(html_doc,encoding='utf-8')
    (output_dir/'person_card.html').write_text(html_doc,encoding='utf-8')
