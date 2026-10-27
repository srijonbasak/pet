"""Fast, local-only access to the newest Codex session."""

from .session_parser import find_latest_session, inspect_session
from .thread_metadata import get_thread_title_map


def get_codex_snapshot():
    path = find_latest_session()
    if not path:
        return None
    session = inspect_session(path)
    if not session or session.get("error"):
        return None
    thread_id = session.get("thread")
    title = get_thread_title_map().get(str(thread_id)) if thread_id else None
    return {
        "provider": "codex",
        "project": session.get("project"),
        "project_path": session.get("project_path"),
        "chat": title or (f"Thread {str(thread_id)[:8]}" if thread_id else "Codex"),
        "thread": thread_id,
        "context": session.get("context"),
        "last_event_at": session.get("last_event_at"),
        "file_updated_at": session.get("file_updated_at"),
        "session_file": session.get("session_file"),
        "_rate_limits": session.get("rate_limits"),
    }


def get_provider_snapshot(provider="codex"):
    return get_codex_snapshot()


def watch_roots():
    from .config import ARCHIVED_DIR, CODEX_HOME, SESSIONS_DIR
    return [path for path in (SESSIONS_DIR, ARCHIVED_DIR, CODEX_HOME) if path.exists()]
