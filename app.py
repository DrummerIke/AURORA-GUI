#!/usr/bin/env python3

import threading
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, url_for
from waitress import serve
from werkzeug.utils import secure_filename

from aurora.jobs import CASES, create_job, jobs, load_recent
from aurora.phone_service import phone_worker

app = Flask(__name__)

INDEX_HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AURORA Control Center</title>
<style>
:root{--bg:#0b0d0f;--panel:#151a1e;--line:#293139;--text:#edf2f5;--muted:#8d9aa4;--accent:#69f0c0;--blue:#86a8ff;--danger:#ff7b7b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#16221f 0,transparent 35%),var(--bg);color:var(--text);font-family:system-ui,sans-serif;min-height:100vh}.shell{max-width:920px;margin:auto;padding:22px 16px 50px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.brand{display:flex;gap:12px;align-items:center}.logo{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;background:#131a19;border:1px solid #31423d;color:var(--accent);font-size:23px}h1{margin:0;letter-spacing:.1em;font-size:22px}.subtitle,.meta{color:var(--muted);font-size:12px}.card,.case{background:rgba(21,26,30,.95);border:1px solid var(--line);border-radius:20px;padding:18px;margin-bottom:14px}.card h2{margin:0 0 8px}.card p{color:var(--muted);line-height:1.5}label{display:block;color:var(--muted);font-size:12px;margin-bottom:7px}input{width:100%;border:1px solid #303941;background:#0e1215;color:var(--text);border-radius:13px;padding:13px 14px;margin-bottom:11px;outline:none}button{width:100%;border:0;border-radius:13px;padding:13px 15px;background:var(--accent);color:#07110d;font-weight:800}.case-top{display:flex;justify-content:space-between;gap:12px}.name{font-weight:700;word-break:break-word}a{color:var(--blue);text-decoration:none}.running{color:#ffd27d}.done{color:var(--accent)}.error{color:var(--danger)}.section{margin:24px 0 12px;font-size:14px}.notice{font-size:12px;color:#c4ced3;line-height:1.5}
</style></head><body><div class="shell">
<header><div class="brand"><div class="logo">◈</div><div><h1>AURORA</h1><div class="subtitle">OPEN-SOURCE PERSON INTELLIGENCE</div></div></div><div class="meta">127.0.0.1</div></header>
<div class="card notice">AURORA формирует карточку человека только по открыто опубликованным данным. Совпадение не доказывает личность текущего владельца номера.</div>
<div class="card"><h2>Phone Intelligence</h2><p>Итог: вероятное ФИО, организация, email, профили, объявления, документы, регион и публичные адреса — без технической выдачи поисковых запросов.</p><form method="post" action="/run/phone"><label>Номер телефона</label><input name="target" required maxlength="32" inputmode="tel" placeholder="+7 999 123-45-67"><button type="submit">Собрать карточку</button></form></div>
<div class="section">Последние расследования</div>
{% if recent %}{% for item in recent %}<div class="case"><div class="case-top"><a class="name" href="/job/{{item.id}}">{{item.target}}</a><span class="{{item.status}}">{{item.status|upper}}</span></div><div class="meta">{{item.kind}} · {{item.created}}</div></div>{% endfor %}{% else %}<div class="case meta">Расследований пока нет.</div>{% endif %}
</div></body></html>'''

JOB_HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA — {{job.target}}</title>
{% if job.status == 'running' %}<meta http-equiv="refresh" content="3">{% endif %}
<style>body{margin:0;background:#0b0d0f;color:#edf2f5;font-family:system-ui}main{max-width:900px;margin:auto;padding:22px 16px 50px}a{color:#86a8ff;text-decoration:none}.card{background:#151a1e;border:1px solid #293139;border-radius:20px;padding:18px;margin-top:16px}.meta{color:#89969f;font-size:12px}.output{white-space:pre-wrap;word-break:break-word;font-family:monospace;background:#090b0d;border:1px solid #293139;border-radius:14px;padding:14px;max-height:450px;overflow:auto;font-size:12px}.running{color:#ffd27d}.done{color:#69f0c0}.error{color:#ff7b7b}.primary{display:block;background:#69f0c0;color:#07110d;padding:14px;border-radius:14px;text-align:center;font-weight:800;margin-bottom:10px}</style></head><body><main>
<a href="/">← Панель</a><h1>{{job.target}}</h1><div class="meta">{{job.kind}} · {{job.created}}</div>
<div class="card">Статус: <strong class="{{job.status}}">{{job.status|upper}}</strong>{% if job.status == 'running' %}<p class="meta">Собираю и сопоставляю открытые данные. Страница обновляется автоматически.</p>{% endif %}</div>
{% if job.status == 'done' %}<div class="card"><h3>Результат</h3>{% if 'person_card.html' in job.files %}<a class="primary" href="/view/{{job.id}}/person_card.html">Открыть карточку человека</a>{% endif %}{% if 'person_card.json' in job.files %}<p><a href="/download/{{job.id}}/person_card.json">Скачать структурированные данные</a></p>{% endif %}</div>{% endif %}
<div class="card"><h3>Журнал</h3><div class="output">{{job.log or 'Ожидание запуска...'}}</div></div>
</main></body></html>'''


@app.get("/")
def index():
    return render_template_string(INDEX_HTML, recent=load_recent())


@app.post("/run/phone")
def run_phone():
    raw_phone = request.form.get("target", "").strip()
    if not raw_phone:
        return "Номер не указан", 400
    job_id = create_job("Phone Intelligence", raw_phone)
    threading.Thread(target=phone_worker, args=(job_id, raw_phone), daemon=True).start()
    return redirect(url_for("job_page", job_id=job_id))


@app.get("/job/<job_id>")
def job_page(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return "Дело не найдено", 404
    return render_template_string(JOB_HTML, job=job)


@app.get("/api/job/<job_id>")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.get("/download/<job_id>/<filename>")
def download(job_id: str, filename: str):
    job = jobs.get(job_id)
    if not job:
        return "Дело не найдено", 404
    return send_from_directory(job["dir"], secure_filename(filename), as_attachment=True)


@app.get("/view/<job_id>/<filename>")
def view_file(job_id: str, filename: str):
    job = jobs.get(job_id)
    if not job:
        return "Дело не найдено", 404
    return send_from_directory(job["dir"], secure_filename(filename), as_attachment=False)


if __name__ == "__main__":
    print("\nAURORA Control Center")
    print("Open: http://127.0.0.1:8080")
    print("Stop: Ctrl+C\n")
    serve(app, host="127.0.0.1", port=8080, threads=6)
