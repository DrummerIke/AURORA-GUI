from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BASE

_LOCK = threading.Lock()
_AUDIT_PATH = Path(os.getenv("AURORA_AUDIT_LOG", BASE / "audit.jsonl"))


def append_audit(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("AURORA_AUDIT_HMAC_KEY", "").encode()
    with _LOCK:
        previous = ""
        if _AUDIT_PATH.exists():
            try:
                previous = json.loads(_AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-1])["hash"]
            except (IndexError, KeyError, ValueError):
                previous = "CORRUPT"
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, "payload": payload, "previous_hash": previous}
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        record["hash"] = hmac.new(key, canonical, hashlib.sha256).hexdigest() if key else hashlib.sha256(canonical).hexdigest()
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record
