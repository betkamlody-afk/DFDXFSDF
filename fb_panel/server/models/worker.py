"""Worker data model"""

from dataclasses import dataclass, field
from typing import Optional


WORKER_OS_OPTIONS = ["Linux", "Windows 10", "Windows 11", "MacOS"]


@dataclass
class WorkerInfo:
    id: int
    email: str = ""
    os: str = "Linux"
    proxy: str = ""
    status: str = "idle"
    log_id: str = ""
    current_step: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "os": self.os,
            "proxy": self.proxy,
            "status": self.status,
            "log_id": self.log_id,
            "current_step": self.current_step,
        }
