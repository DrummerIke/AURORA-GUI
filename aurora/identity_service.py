from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from ddgs import DDGS

from .jobs import append_log, finish_job, jobs

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
URL_RE = re.compile(r"https?://[^\s\]\)>'\"]+")

PLATFORMS = {
    "t.me": "Telegram",
    "telegram.me": "Telegram",
    "vk.com": "VK",
    "ok.ru": "Одноклассники",
    "instagram.com": "Instagram",
    "tiktok.com": "TikTok",
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "reddit.com": "Reddit",
    "x.com": "X",
    "twitter.com": "X",
    "facebook.com": "Facebook",
    "linkedin.com": "LinkedIn",
    "twitch.tv": "Twitch",
    "pinterest.com": "Pinterest",
    "medium.com": "Medium",
    "habr.com": "Habr",
    "steamcommunity.com": "Steam",
}

DIRECT_SEARCH_DOMAINS = [
    "t.me", "vk.com", "ok.ru", "instagram.com", "tiktok.com",
    "github.com", "gitlab.com", "youtube.com", "reddit.com",
    "x.com", "twitter.com", "facebook.com", "linkedin.com",
    "twitch.tv", "pinterest.com", "medium.com", "habr.com",
    "steamcommunity.com",
]


def _run(command: list[str], timeout: int = 75) -> dict:
    binary = shutil.which(command[0])
    if not binary:
        return {"tool": command[0], "status": "missing", "output": "", "urls": []}
    command[0] = binary
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        output = (result.stdout or "") + (result.stderr or "")
        return {
            "tool": Path(binary).name,
            "status": "ok" if result.returncode == 0 else "error",
            "output": output,
            "urls": sorted(set(URL_RE.findall(output)))[:300],
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {"tool": Path(binary).name, "status": "timeout", "output": output, "urls": sorted(set(URL_RE.findall(output)))[:300]}
    except Exception as exc:
        return {"tool": Path(binary).name, "status": "error", "output": str(exc), "urls": []}


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _platform(url: str) -> str:
    domain = _domain(url)
    for host, label in PLATFORMS.items():
        if domain == host or domain.endswith("." + host):
            return label
    return "Другое"


def _web_search(queries: list[str], max_results: int = 8) -> tuple[list[dict], list[dict]]:
    results: list[dict] = []
    errors: list[dict] = []
    seen = set()
    with DDGS(timeout=10) as ddgs:
        for query in queries:
            try:
                for item in ddgs.text(query, max_results=max_results) or []:
                    url = str(item.get("href") or item.get("url") or "").strip()
                    key = url.rstrip("/").casefold()
                    if not url or key in seen:
                        continue
                    seen.add(key)
                    results.append({
                        "title": str(item.get("title") or "").strip(),
                        "url": url,
                        "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
                        "platform": _platform(url),
                        "source": "web",
                    })
            except Exception as exc:
                errors.append({"query": query, "error": str(exc)})
    return results, errors


def _merge_profiles(modules: list[dict], web_results: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for module in modules:
        for url in module.get("urls", []):
            key = url.rstrip("/").casefold()
            merged.setdefault(key, {
                "url": url,
                "platform": _platform(url),
                "title": "",
                "snippet": "",
                "sources": [],
            })["sources"].append(module.get("tool", "module"))
    for item in web_results:
        url = item.get("url", "")
        if not url:
            continue
        key = url.rstrip("/").casefold()
        current = merged.setdefault(key, {
            "url": url,
            "platform": item.get("platform") or _platform(url),
            "title": "",
            "snippet": "",
            "sources": [],
        })
        current["title"] = current["title"] or item.get("title", "")
        current["snippet"] = current["snippet"] or item.get("snippet", "")
        current["sources"].append("web")
    output = []
    for item in merged.values():
        item["sources"] = sorted(set(item["sources"]))
        item["confidence"] = min(95, 45 + 15 * len(item["sources"]))
        output.append(item)
    return sorted(output, key=lambda item: (-item["confidence"], item["platform"], item["url"]))


def _write_report(case_dir: Path, kind: str, target: str, modules: list[dict], profiles: list[dict], debug: dict) -> None:
    payload = {
        "kind": kind,
        "target": target,
        "profiles": profiles,
        "module_status": [{"tool": m["tool"], "status": m["status"], "result_count": len(m.get("urls", []))} for m in modules],
    }
    (case_dir / "identity_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_dir / "debug.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")

    groups: dict[str, list[dict]] = {}
    for profile in profiles:
        groups.setdefault(profile["platform"], []).append(profile)

    sections = []
    for platform, items in sorted(groups.items(), key=lambda pair: (pair[0] == "Другое", pair[0])):
        cards = []
        for item in items:
            title = item.get("title") or item["url"]
            sources = ", ".join(item.get("sources", []))
            snippet = item.get("snippet", "")[:500]
            cards.append(
                f'<article><a href="{html.escape(item["url"])}" target="_blank"><strong>{html.escape(title)}</strong></a>'
                f'<div class="meta">{item["confidence"]}% · подтверждение: {html.escape(sources)}</div>'
                f'<p>{html.escape(snippet)}</p></article>'
            )
        sections.append(f'<section><h2>{html.escape(platform)} <span>{len(items)}</span></h2>{"".join(cards)}</section>')

    module_line = " · ".join(f'{html.escape(m["tool"])}: {html.escape(m["status"])}' for m in modules)
    document = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURORA</title><style>body{{margin:0;background:#0b0d0f;color:#edf2f5;font-family:system-ui}}main{{max-width:1050px;margin:auto;padding:24px}}section,article{{background:#151a1e;border:1px solid #293139;border-radius:18px;padding:16px;margin:12px 0}}article{{background:#0e1215}}a{{color:#86a8ff;text-decoration:none}}.meta{{color:#8d9aa4;font-size:12px;margin-top:6px}}.tag{{color:#69f0c0}}h2 span{{color:#8d9aa4;font-size:14px}}</style></head><body><main><div class="tag">AURORA · SOCIAL INTELLIGENCE</div><h1>{html.escape(target)}</h1><p>Найденные публичные профили и связанные страницы. Технические запросы скрыты в debug.json.</p><div class="meta">{module_line}</div>{''.join(sections) if sections else '<section>Подтверждённых публичных профилей не найдено.</section>'}</main></body></html>'''
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
            append_log(job_id, "[1/4] Проверка email на публичных сервисах...")
            modules.append(_run(["holehe", target, "--only-used"]))
            queries = [f'"{target}"'] + [f'"{target}" site:{domain}' for domain in DIRECT_SEARCH_DOMAINS]
            if USERNAME_RE.fullmatch(username):
                append_log(job_id, "[2/4] Поиск username, полученного из email...")
                modules.append(_run(["sherlock", username, "--print-found"]))
                modules.append(_run(["maigret", username, "--no-progressbar"]))
                modules.append(_run(["socialscan", username]))
                queries += [f'"{username}" site:{domain}' for domain in DIRECT_SEARCH_DOMAINS]
        elif kind == "username":
            username = target.lstrip("@").strip()
            if not USERNAME_RE.fullmatch(username):
                raise ValueError("Некорректный username")
            target = username
            queries = [f'"{username}" site:{domain}' for domain in DIRECT_SEARCH_DOMAINS]
            append_log(job_id, "[1/4] Sherlock...")
            modules.append(_run(["sherlock", username, "--print-found"]))
            append_log(job_id, "[2/4] Maigret...")
            modules.append(_run(["maigret", username, "--no-progressbar"]))
            append_log(job_id, "[3/4] Socialscan...")
            modules.append(_run(["socialscan", username]))
        else:
            raise ValueError("Неизвестный тип расследования")

        append_log(job_id, "[4/4] Адресный поиск по соцсетям и мессенджерам...")
        web_results, errors = _web_search(queries, max_results=5)
        profiles = _merge_profiles(modules, web_results)
        debug = {"queries": queries, "modules": modules, "web_results": web_results, "errors": errors}
        _write_report(case_dir, kind, target, modules, profiles, debug)
        append_log(job_id, f"Найдено публичных профилей и страниц: {len(profiles)}")
        append_log(job_id, "Открой итоговый отчёт — технические запросы в нём не показываются.")
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {exc}")
        finish_job(job_id, "error")
