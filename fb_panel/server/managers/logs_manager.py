"""Logs manager — email:password queue + persistence"""

import hashlib
import json
import time
import logging
from typing import List, Dict

from server.config import LOGS_FILE
from server.models import LogEntry, LogStatus

log = logging.getLogger("fb_panel.logs_manager")


class LogsManager:
    """Stores email:password queue, persists to JSON."""

    def __init__(self):
        self.logs: Dict[str, LogEntry] = {}
        self._load()

    # ── persistence ────────────────────────────────────────────
    def _load(self):
        if LOGS_FILE.exists():
            try:
                data = json.loads(LOGS_FILE.read_text())
                for item in data.get("logs", []):
                    entry = LogEntry(
                        id=item["id"],
                        email=item["email"],
                        password=item.get("password", ""),
                        status=LogStatus(item.get("status", "pending")),
                        code=item.get("code"),
                        proxy=item.get("proxy"),
                        worker_os=item.get("worker_os"),
                        error=item.get("error"),
                        recover_url=item.get("recover_url"),
                        created_at=item.get("created_at", ""),
                        updated_at=item.get("updated_at", ""),
                    )
                    self.logs[entry.id] = entry
                log.info(f"Loaded {len(self.logs)} logs from file")
            except Exception as e:
                log.error(f"Failed to load logs: {e}")

    def _save(self):
        try:
            rows = []
            for entry in self.logs.values():
                d = entry.to_dict()
                # Keep passwords for entries that may need retry (pending/processing)
                # Clear passwords for finished entries (security)
                if entry.status not in (LogStatus.PENDING, LogStatus.PROCESSING):
                    d["password"] = ""
                else:
                    d["password"] = entry.password
                rows.append(d)
            LOGS_FILE.write_text(json.dumps({"logs": rows}, indent=2))
        except Exception as e:
            log.error(f"Failed to save logs: {e}")

    # ── load from raw lines ────────────────────────────────────
    def load_logs(self, lines: List[str]) -> int:
        loaded = 0
        existing_emails = {e.email for e in self.logs.values() if e.status == LogStatus.PENDING}
        for line in lines:
            line = line.strip()
            if not line or ":" not in line:
                continue
            try:
                email, password = line.split(":", 1)
                email, password = email.strip().lower(), password.strip()
                if not email or not password:
                    continue
                # Skip duplicates (same email already pending)
                if email in existing_emails:
                    continue
                log_id = hashlib.md5(f"{email}:{time.time()}:{loaded}".encode()).hexdigest()[:12]
                self.logs[log_id] = LogEntry(id=log_id, email=email, password=password)
                existing_emails.add(email)
                loaded += 1
            except Exception as e:
                log.warning(f"Invalid log: {line[:30]}… — {e}")
        self._save()
        log.info(f"Loaded {loaded} logs")
        return loaded

    # ── queries ────────────────────────────────────────────────
    def get_pending(self) -> List[LogEntry]:
        return [e for e in self.logs.values() if e.status == LogStatus.PENDING]

    def update_status(self, log_id: str, status: LogStatus, **kw):
        entry = self.logs.get(log_id)
        if not entry:
            return
        entry.status = status
        from datetime import datetime
        entry.updated_at = datetime.now().isoformat()
        for k, v in kw.items():
            if hasattr(entry, k):
                setattr(entry, k, v)
        self._save()

    def get_stats(self) -> dict:
        buckets = {"total": len(self.logs), "pending": 0, "processing": 0, "success": 0, "checkpoint": 0, "invalid": 0, "2fa_required": 0, "error": 0}
        for e in self.logs.values():
            key = e.status.value if isinstance(e.status, LogStatus) else e.status
            if key in buckets:
                buckets[key] += 1
        return buckets

    def get_all(self) -> List[dict]:
        return [e.to_dict() for e in self.logs.values()]

    def delete_single(self, log_id: str) -> bool:
        if log_id in self.logs:
            del self.logs[log_id]
            self._save()
            return True
        return False

    def clear(self):
        self.logs.clear()
        self._save()
