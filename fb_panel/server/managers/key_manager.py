"""Key manager — authentication key generation & session management"""

import hashlib
import secrets
import time
import json
import logging
from typing import Optional, Dict, Tuple

from server.config import KEYS_FILE, DATA_DIR

log = logging.getLogger("fb_panel.key_manager")


class KeyManager:
    """Generates and validates auth keys, tracks sessions."""

    def __init__(self):
        self.keys: Dict[str, dict] = {}
        self.sessions: Dict[str, dict] = {}
        self._load()

    # ── persistence ────────────────────────────────────────────
    def _load(self):
        if KEYS_FILE.exists():
            try:
                data = json.loads(KEYS_FILE.read_text())
                self.keys = data.get("keys", {})
            except Exception as e:
                log.error(f"Failed to load keys: {e}")

    def _save(self):
        try:
            DATA_DIR.mkdir(exist_ok=True)
            data = {"keys": self.keys}
            KEYS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Failed to save keys: {e}")

    # ── key generation ─────────────────────────────────────────
    def generate_key(self) -> str:
        raw = secrets.token_hex(8).upper()
        key = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"
        self.keys[key] = {
            "created_at": time.time(),
            "used": False,
            "used_at": None,
        }
        self._save()
        log.info(f"Generated key: {key}")
        return key

    # ── validation ─────────────────────────────────────────────
    def validate_key(self, key: str) -> Tuple[bool, str, Optional[str]]:
        """Returns (is_valid, message, session_id | None)."""
        key = key.strip().upper()
        if key not in self.keys:
            return False, "Nieprawidłowy klucz!", None
        entry = self.keys[key]
        if entry.get("used"):
            return False, "Klucz już wykorzystany!", None
        entry["used"] = True
        entry["used_at"] = time.time()
        self._save()
        session_id = self._create_session(key)
        return True, "Autoryzacja pomyślna!", session_id

    # ── sessions ───────────────────────────────────────────────
    def _create_session(self, key: str) -> str:
        sid = hashlib.sha256(f"{key}:{time.time()}:{secrets.token_hex(8)}".encode()).hexdigest()[:32]
        self.sessions[sid] = {"key": key, "created_at": time.time()}
        return sid

    def is_session_valid(self, session_id: str) -> bool:
        if not session_id:
            return False
        session = self.sessions.get(session_id)
        if not session:
            return False
        # 24-hour expiry
        if time.time() - session["created_at"] > 86400:
            del self.sessions[session_id]
            return False
        return True

    def logout(self, session_id: str):
        self.sessions.pop(session_id, None)
