"""Log entry data model"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional


class LogStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    CHECKPOINT = "checkpoint"
    INVALID = "invalid"
    TWO_FA = "2fa_required"
    ERROR = "error"


@dataclass
class LogEntry:
    id: str
    email: str
    password: str = ""
    status: LogStatus = LogStatus.PENDING
    code: Optional[str] = None
    proxy: Optional[str] = None
    session_id: Optional[str] = None
    worker_os: Optional[str] = None
    worker_id: Optional[int] = None
    error: Optional[str] = None
    recover_url: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "password": self.password,
            "status": self.status.value if isinstance(self.status, LogStatus) else self.status,
            "code": self.code,
            "proxy": self.proxy,
            "worker_os": self.worker_os,
            "error": self.error,
            "recover_url": self.recover_url,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
