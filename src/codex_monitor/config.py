import os
from pathlib import Path

CODEX_HOME = Path(
    os.environ.get(
        "CODEX_HOME",
        Path.home() / ".codex"
    )
)

SESSIONS_DIR = CODEX_HOME / "sessions"
ARCHIVED_DIR = CODEX_HOME / "archived_sessions"

AUTH_FILE = CODEX_HOME / "auth.json"
SESSION_INDEX_FILE = CODEX_HOME / "session_index.jsonl"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

CACHE_FILE = PROJECT_ROOT / "codex_cache.json"
OUTPUT_FILE = PROJECT_ROOT / "codex_live.json"

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

QUOTA_REFRESH_SECONDS = 300  # 5 minutes
LOCAL_EVENT_DEBOUNCE_SECONDS = 0.35
