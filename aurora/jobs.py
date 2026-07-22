import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import CASES

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def append_log(job_id: str, text: str) -> None:
    with jobs_lock:
        jobs[job_id]["log"] += text.rstrip() + "\n"


def create_job(kind: str, target: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    case_dir = CASES / job_id
    case_dir.mkdir(parents=True, exist_ok=True)
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "target": target,
            "status": "running",
            "created": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "log": "",
            "files": [],
            "dir": str(case_dir),
        }
    return job_id


def finish_job(job_id: str, status: str = "done") -> None:
    with jobs_lock:
        job = jobs[job_id]
        case_dir = Path(job["dir"])
        manifest = {
            "id": job_id,
            "kind": job["kind"],
            "target": job["target"],
            "status": status,
            "created": job["created"],
        }
    manifest["files"] = sorted(p.name for p in case_dir.iterdir() if p.is_file())
    (case_dir / "case.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with jobs_lock:
        jobs[job_id].update(status=status, files=sorted(p.name for p in case_dir.iterdir() if p.is_file()))


def load_recent(limit: int = 12) -> list[dict]:
    recent = []
    for path in CASES.glob("*/case.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            recent.append(data)
            with jobs_lock:
                jobs.setdefault(data["id"], {**data, "log": "", "dir": str(path.parent)})
        except (OSError, ValueError, KeyError):
            continue
    recent.sort(key=lambda item: item.get("created", ""))
    return list(reversed(recent[-limit:]))
