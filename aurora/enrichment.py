from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from urllib.parse import urlparse

SOCIAL_HOSTS = {
    "vk.com", "ok.ru", "t.me", "telegram.me", "github.com",
    "instagram.com", "facebook.com", "linkedin.com", "x.com", "twitter.com",
}

MAX_USERNAMES = 2
MAX_EMAILS = 2
GLOBAL_TIMEOUT_SECONDS = 35
TOOL_TIMEOUT_SECONDS = 28


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:80]


def _run(command: list[str], timeout: int) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, output + "\n[TIMEOUT]"
    except Exception as exc:
        return 1, str(exc)


def extract_usernames(findings: list[dict]) -> list[str]:
    result: list[str] = []
    seen = set()

    for item in findings:
        if item.get("kind") not in {"social_profile", "username"}:
            continue

        if item.get("kind") == "username":
            candidate = str(item.get("value", "")).strip().lstrip("@")
        else:
            parsed = urlparse(str(item.get("value", "")))
            host = parsed.netloc.lower().removeprefix("www.")
            if host not in SOCIAL_HOSTS:
                continue
            parts = [part for part in parsed.path.split("/") if part]
            if not parts:
                continue
            candidate = parts[0].strip().lstrip("@")

        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", candidate):
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)

    return result[:MAX_USERNAMES]


def extract_emails(findings: list[dict]) -> list[str]:
    result: list[str] = []
    seen = set()
    for item in findings:
        if item.get("kind") != "email":
            continue
        value = str(item.get("value", "")).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result[:MAX_EMAILS]


def run_sherlock(username: str, output_dir: Path) -> dict:
    binary = _tool("sherlock")
    if not binary:
        return {"tool": "sherlock", "target": username, "status": "missing", "profiles": []}

    code, output = _run([binary, username, "--print-found"], TOOL_TIMEOUT_SECONDS)
    (output_dir / f"sherlock_{_safe_name(username)}.txt").write_text(output, encoding="utf-8", errors="ignore")
    profiles = sorted(set(re.findall(r"https?://[^\s\]\)]+", output)))
    return {
        "tool": "sherlock",
        "target": username,
        "status": "timeout" if code == 124 else "ok" if code == 0 else "error",
        "profiles": profiles[:80],
    }


def run_maigret(username: str, output_dir: Path) -> dict:
    binary = _tool("maigret")
    if not binary:
        return {"tool": "maigret", "target": username, "status": "missing", "profiles": []}

    code, output = _run([binary, username, "--no-progressbar"], TOOL_TIMEOUT_SECONDS)
    (output_dir / f"maigret_{_safe_name(username)}.txt").write_text(output, encoding="utf-8", errors="ignore")
    profiles = sorted(set(re.findall(r"https?://[^\s\]\)]+", output)))
    return {
        "tool": "maigret",
        "target": username,
        "status": "timeout" if code == 124 else "ok" if code == 0 else "error",
        "profiles": profiles[:100],
    }


def run_holehe(email: str, output_dir: Path) -> dict:
    binary = _tool("holehe")
    if not binary:
        return {"tool": "holehe", "target": email, "status": "missing", "services": []}

    code, output = _run([binary, email, "--only-used"], TOOL_TIMEOUT_SECONDS)
    (output_dir / f"holehe_{_safe_name(email)}.txt").write_text(output, encoding="utf-8", errors="ignore")
    services = []
    for line in output.splitlines():
        text = line.strip()
        if text.startswith("[+]") or text.startswith("[+"):
            services.append(text)
    return {
        "tool": "holehe",
        "target": email,
        "status": "timeout" if code == 124 else "ok" if code == 0 else "error",
        "services": services[:80],
    }


def enrich_findings(findings: list[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    usernames = extract_usernames(findings)
    emails = extract_emails(findings)

    jobs = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        for username in usernames:
            jobs.append(executor.submit(run_sherlock, username, output_dir))
            jobs.append(executor.submit(run_maigret, username, output_dir))
        for email in emails:
            jobs.append(executor.submit(run_holehe, email, output_dir))

        done, pending = wait(jobs, timeout=GLOBAL_TIMEOUT_SECONDS)
        results = []
        for future in done:
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"tool": "unknown", "status": "error", "error": str(exc)})

        for future in pending:
            future.cancel()

    profiles = set()
    registered_services = []
    for item in results:
        profiles.update(item.get("profiles", []))
        target = item.get("target")
        for service in item.get("services", []):
            registered_services.append({"email": target, "service": service})

    payload = {
        "usernames": usernames,
        "emails": emails,
        "profiles": sorted(profiles),
        "registered_services": registered_services,
        "modules": results,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "timed_out_modules": len(pending),
        "global_timeout_seconds": GLOBAL_TIMEOUT_SECONDS,
    }

    (output_dir / "enrichment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
