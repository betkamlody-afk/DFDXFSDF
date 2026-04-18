"""Active session data model — represents one checked account with 3 tabs"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class ProfileInfo:
    """Facebook profile information extracted after login."""
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    friends_count: int = 0
    profile_picture: str = ""
    profile_url: str = ""
    gender: str = ""
    location: str = ""
    workplace: str = ""

    def to_dict(self) -> dict:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "friends_count": self.friends_count,
            "profile_picture": self.profile_picture,
            "profile_url": self.profile_url,
            "gender": self.gender,
            "location": self.location,
            "workplace": self.workplace,
        }


@dataclass
class SessionTab:
    """State for a single browser tab in the session."""
    name: str = ""           # "email", "facebook", "panel"
    url: str = ""
    status: str = "idle"     # idle, loading, ready, error
    last_action: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url, "status": self.status, "last_action": self.last_action}


@dataclass
class SessionData:
    """Full session for a successfully logged email — 3 tabs of data."""
    id: str = ""
    log_id: str = ""
    email: str = ""
    password: str = ""
    proxy: str = ""
    worker_os: str = ""
    code: str = ""
    mode: str = "selenium"
    proxy_info: dict = field(default_factory=dict)

    # Tab 1: Email
    email_provider: str = ""      # wp.pl, o2.pl, etc.
    email_logged_in: bool = False
    email_inbox_count: int = 0

    # Tab 2: Facebook
    fb_logged_in: bool = False
    fb_reset_sent: bool = False
    fb_code_extracted: str = ""

    # Tab 3: Panel — profile info
    profile: ProfileInfo = field(default_factory=ProfileInfo)

    # Tab 3: Panel — auto-actions state
    auto_logout_active: bool = False
    auto_disconnect_active: bool = False
    auto_delete_posts_active: bool = False
    auto_delete_stories_active: bool = False

    # Counters for auto-actions performed
    posts_deleted: int = 0
    stories_deleted: int = 0
    connections_disconnected: int = 0

    # Tabs
    tabs: List[SessionTab] = field(default_factory=lambda: [
        SessionTab(name="email", status="idle"),
        SessionTab(name="facebook", status="idle"),
        SessionTab(name="panel", status="idle"),
    ])

    # Meta
    status: str = "active"    # preview, loading, awaiting_vnc, active, crashed, closed
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    vnc_status: str = ""
    vnc_token: str = ""
    vnc_register_url: str = ""
    vnc_connected_at: str = ""
    vnc_launcher: str = ""
    vnc_url: str = ""
    vnc_port: int = 0
    novnc_port: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "log_id": self.log_id,
            "email": self.email,
            "proxy": self.proxy,
            "worker_os": self.worker_os,
            "code": self.code,
            "mode": self.mode,
            "proxy_info": self.proxy_info,
            "email_provider": self.email_provider,
            "email_logged_in": self.email_logged_in,
            "email_inbox_count": self.email_inbox_count,
            "fb_logged_in": self.fb_logged_in,
            "fb_reset_sent": self.fb_reset_sent,
            "fb_code_extracted": self.fb_code_extracted,
            "profile": self.profile.to_dict(),
            "auto_logout_active": self.auto_logout_active,
            "auto_disconnect_active": self.auto_disconnect_active,
            "auto_delete_posts_active": self.auto_delete_posts_active,
            "auto_delete_stories_active": self.auto_delete_stories_active,
            "posts_deleted": self.posts_deleted,
            "stories_deleted": self.stories_deleted,
            "connections_disconnected": self.connections_disconnected,
            "tabs": [t.to_dict() for t in self.tabs],
            "status": self.status,
            "created_at": self.created_at,
            "vnc_status": self.vnc_status,
            "vnc_token": self.vnc_token,
            "vnc_register_url": self.vnc_register_url,
            "vnc_connected_at": self.vnc_connected_at,
            "vnc_launcher": self.vnc_launcher,
            "vnc_url": self.vnc_url,
            "vnc_port": self.vnc_port,
            "novnc_port": self.novnc_port,
        }
