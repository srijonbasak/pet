from dataclasses import dataclass
from typing import Optional

@dataclass
class MonitorState:
    provider: Optional[str] = None
    project: Optional[str] = None
    chat: Optional[str] = None
    thread_id: Optional[str] = None

    context_left: Optional[int] = None
    context_used: Optional[int] = None
    context_max: Optional[int] = None

    limit_5h_left: Optional[int] = None
    limit_5h_reset: Optional[str] = None

    limit_7d_left: Optional[int] = None
    limit_7d_reset: Optional[str] = None
