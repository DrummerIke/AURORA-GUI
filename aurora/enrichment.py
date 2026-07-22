from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


SOCIAL_HOSTS = {
    "vk.com", "ok.ru", "t.me", "telegram.me", "github.com",
    "instagram.com", "facebook.com", "linkedin.com", "x.com", "twitter.com",
}


class EnrichmentResult(dict):
    pass


def _run(command: list[str], timeout: int) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:
        return 1, str(exc)


def _tool(name: str) -> str | None:
    return shutil.which(name)


def extract_usernames(findings: list[dict]) -> list[str]:
    usernames: list[str] = []
    seen = set()

    for item in findings:
        if item.get("kind") != "social_profile":
            continue
        url = item.get("value", "")
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        if host not in SOCIAL_HOSTS:
            continue
        parts = [x for x in parsed.path.split("/") if x]
        if not parts:
            continue
        candidate = parts[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", candidate):
            continue
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            usernames.append(candidate)

    return usernames[:4]


def extract_emails(findings: list[dict]) -> list[str]:
    emails: list[str] = []
    seen = set()
    for item in findings:
        if item.get("kind") != "email":
            continue
        value = item.get("value", "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            emails.append(value)
    return emails[:4]


def run_sherlock(username: str, output_dir: Path) -> dict:
    binary = _tool("sherlock")
    if not binary:
        return {"tool": "sherlock", "target": username, "status": "missing", "profiles": []}

    code, output = _run([binary, username, "--print-found"], timeout=90)
    profiles = sorted(set(re.findall(r"https?://\S+", output)))
    path = output_dir / f"sherlock_{username}.txt"
    path.write_text(output, encoding="utf-8", errors="ignore")
    return {"tool": "sherlock", "target": username, "status": "ok" if code == 0 else "error", "profiles": profiles[:100]}


def run_maigret(username: str, output_dir: Path) -> dict:
    binary = _tool("maigret")
    if not binary:
        return {"tool": "maigret", "target": username, "status": "missing", "profiles": []}

    code, output = _run([binary, username, "--no-progressbar"], timeout=120)
    profiles = sorted(set(re.findall(r"https?://\S+", output)))
    path = output_dir / f"maigret_{username}.txt"
    path.write_text(output, encoding="utf-8", errors="ignore")
    return {"tool": "maigret", "target": username, "status": "ok" if code == 0 else "error", "profiles": profiles[:150]}


def run_holehe(email: str, output_dir: Path) -> dict:
    binary = _tool("holehe")
    if not binary:
        return {"tool": "holehe", "target": email, "status": "missing", "services": []}

    code, output = _run([binary, email, "--only-used"], timeout=90)
    services = []
    for line in output.splitlines():
        text = line.strip()
        if text.startswith("[+") or text.startswith("[+]") or "[+" in text:
            services.append(text)
    path = output_dir / f"holehe_{re.sub(r'[^A-Za-z0-9_.-]', '_', email)}.txt"
    path.write_text(output, encoding="utf-8", errors="ignore")
    return {"tool": "holehe", "target": email, "status": "ok" if code == 0 else "error", "services": services[:100]}


def enrich_findings(findings: list[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    usernames = extract_usernames(findings)
    emails = extract_emails(findings)

    results = []
    discovered_profiles = set()
    registered_services = []

    for username in usernames:
        sherlock = run_sherlock(username, output_dir)
        maigret = run_maigret(username, output_dir)
        results.extend([sherlock, maigret])
        discovered_profiles.update(sherlock.get("profiles", []))
        discovered_profiles.update(maigret.get("profiles", []))

    for email in emails:
        holehe = run_holehe(email, output_dir)
        results.append(holehe)
        for service in holehe.get("services", []):
            registered_services.append({"email": email, "service": service})

    payload = {
        "usernames": usernames,
        "emails": emails,
        "profiles": sorted(discovered_profiles),
        "registered_services": registered_services,
        "modules": results,
    }

    (output_dir / "enrichment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
