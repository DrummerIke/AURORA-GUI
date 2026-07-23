from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

from ddgs import DDGS

from .jobs import append_log, finish_job, jobs

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def _run(command: list[str], timeout: int = 45) -> dict:
    binary = shutil.which(command[0])
    if not binary:
        return {"tool": command[0], "status": "missing", "output": ""}
    command[0] = binary
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        output = (result.stdout or "") + (result.stderr or "")
        return {"tool": Path(binary).name, "status": "ok" if result.returncode == 0 else "error", "output": output}
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {"tool": Path(binary).name, "status": "timeout", "output": output}
    except Exception as exc:
        return {"tool": Path(binary).name, "status": "error", "output": str(exc)}


def _web_search(queries: list[str], max_results: int = 8) -> list[dict]:
    results: list[dict] = []
    seen = set()
    with DDGS() as ddgs:
        for query in queries:
            try:
                for item in ddgs.text(query, max_results=max_results):
                    url = str(item.get("href") or item.get("url") or "").strip()
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    results.append({
                        "query": query,
                        "title": str(item.get("title") or ""),
                        "url": url,
                        "snippet": str(item.get("body") or item.get("snippet") or ""),
                    })
            except Exception as exc:
                results.append({"query": query, "title": "Ошибка поиска", "url": "", "snippet": str(exc)})
    return results


def _extract_urls(text: str) -> list[str]:
    return sorted(set(re.findall(r"https?://[^\s\]\)>'\"]+", text or "")))[:200]


def _write_report(case_dir: Path, kind: str, target: str, modules: list[dict], web_results: list[dict]) -> None:
    payload = {"kind": kind, "target": target, "modules": modules, "web_results": web_results}
    (case_dir / "identity_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    module_cards = []
    for module in modules:
        links = "".join(f'<li><a href="{html.escape(url)}" target="_blank">{html.escape(url)}</a></li>' for url in _extract_urls(module.get("output", ""))[:40])
        output = html.escape(module.get("output", "")[:12000])
        module_cards.append(
            f'<section><h2>{html.escape(module["tool"])}</h2><b>{html.escape(module["status"])}</b>'
            f'<ul>{links}</ul><details><summary>Технический вывод</summary><pre>{output}</pre></details></section>'
        )

    web_cards = "".join(
        f'<article><a href="{html.escape(item["url"])}" target="_blank">{html.escape(item["title"] or item["url"])}</a>'
        f'<p>{html.escape(item["snippet"][:700])}</p><small>{html.escape(item["query"])}</small></article>'
        for item in web_results if item.get("url")
    )
    document = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA</title><style>body{{margin:0;background:#0b0d0f;color:#edf2f5;font-family:system-ui}}main{{max-width:1050px;margin:auto;padding:24px}}section,article{{background:#151a1e;border:1px solid #293139;border-radius:18px;padding:16px;margin:12px 0}}a{{color:#86a8ff}}small{{color:#8d9aa4}}pre{{white-space:pre-wrap;word-break:break-word;max-height:420px;overflow:auto}}.tag{{color:#69f0c0}}</style></head><body><main><div class="tag">AURORA · {html.escape(kind.upper())}</div><h1>{html.escape(target)}</h1><p>Отчёт собран из открытых источников. Совпадения требуют ручной проверки.</p>{''.join(module_cards)}<h2>Открытые публикации</h2>{web_cards or '<article>Подтверждённых публикаций не найдено.</article>'}</main></body></html>'''
    (case_dir / "identity_report.html").write_text(document, encoding="utf-8")


def identity_worker(job_id: str, kind: str, target: str) -> None:
    case_dir = Path(jobs[job_id]["dir"])
    try:
        append_log(job_id, f"AURORA {kind.title()} Intelligence")
        append_log(job_id, f"Цель: {target}")
        modules: list[dict] = []

        if kind == "email":
            if not EMAIL_RE.fullmatch(target):
                raise ValueError("Некорректный email")
            username = target.split("@", 1)[0]
            queries = [f'"{target}"', f'"{target}" профиль OR контакты', f'"{target}" filetype:pdf']
            append_log(job_id, "[1/3] Holehe...")
            modules.append(_run(["holehe", target, "--only-used"]))
            append_log(job_id, "[2/3] Поиск username из локальной части email...")
            if USERNAME_RE.fullmatch(username):
                modules.append(_run(["sherlock", username, "--print-found"]))
                modules.append(_run(["maigret", username, "--no-progressbar"]))
        elif kind == "username":
            username = target.lstrip("@").strip()
            if not USERNAME_RE.fullmatch(username):
                raise ValueError("Некорректный username")
            target = username
            queries = [f'"{username}" профиль', f'"{username}" site:github.com OR site:vk.com OR site:t.me', f'"{username}" контакты']
            append_log(job_id, "[1/3] Sherlock...")
            modules.append(_run(["sherlock", username, "--print-found"]))
            append_log(job_id, "[2/3] Maigret...")
            modules.append(_run(["maigret", username, "--no-progressbar"]))
        else:
            raise ValueError("Неизвестный тип расследования")

        append_log(job_id, "[3/3] Поиск открытых публикаций...")
        web_results = _web_search(queries)
        _write_report(case_dir, kind, target, modules, web_results)
        installed = sum(1 for item in modules if item["status"] != "missing")
        append_log(job_id, f"Доступно внешних модулей: {installed}/{len(modules)}")
        append_log(job_id, f"Открытых результатов: {sum(1 for item in web_results if item.get('url'))}")
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {exc}")
        finish_job(job_id, "error")
