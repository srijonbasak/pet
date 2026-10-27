from datetime import datetime
from pathlib import Path

from .config import SESSIONS_DIR, ARCHIVED_DIR
from .utils import safe_json_load, normalize_path, project_name_from_path

def get_all_session_files():
    files = []

    if SESSIONS_DIR.exists():
        files.extend(
            SESSIONS_DIR.rglob(
                "rollout-*.jsonl"
            )
        )

    if ARCHIVED_DIR.exists():
        files.extend(
            ARCHIVED_DIR.rglob(
                "rollout-*.jsonl"
            )
        )

    return list(files)

def find_latest_session():
    files = get_all_session_files()

    if not files:
        return None

    return max(
        files,
        key=lambda p: p.stat().st_mtime
    )

def inspect_session(path):
    if not path or not path.exists():
        return None

    thread_id = None
    cwd = None

    context_window = None

    total_tokens = None
    input_tokens = None
    output_tokens = None
    cached_input_tokens = None
    reasoning_output_tokens = None
    rate_limits = None

    session_created_at = None
    last_event_timestamp = None

    try:
        with path.open(
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue

                event = safe_json_load(line)
                if not event:
                    continue

                payload = event.get("payload") or {}
                event_type = event.get("type")
                payload_type = payload.get("type")

                # Session metadata
                if event_type == "session_meta":
                    thread_id = payload.get("id") or payload.get("session_id") or thread_id
                    cwd = payload.get("cwd") or payload.get("working_directory") or cwd
                    session_created_at = payload.get("timestamp") or payload.get("created_at") or session_created_at

                if payload_type == "session_meta":
                    thread_id = payload.get("id") or payload.get("session_id") or thread_id
                    cwd = payload.get("cwd") or payload.get("working_directory") or cwd

                # Turn/task context
                if payload_type in {"turn_context", "task_started", "turn_started"}:
                    cwd = payload.get("cwd") or payload.get("working_directory") or cwd
                    cw = payload.get("model_context_window")
                    if isinstance(cw, (int, float)):
                        context_window = int(cw)

                # Token count events
                if payload_type == "token_count":
                    info = payload.get("info") or {}
                    cw = info.get("model_context_window")
                    if isinstance(cw, (int, float)):
                        context_window = int(cw)

                    usage = info.get("last_token_usage") or info.get("total_token_usage") or {}
                    
                    value = usage.get("total_tokens")
                    if isinstance(value, (int, float)):
                        total_tokens = int(value)

                    value = usage.get("input_tokens")
                    if isinstance(value, (int, float)):
                        input_tokens = int(value)

                    value = usage.get("output_tokens")
                    if isinstance(value, (int, float)):
                        output_tokens = int(value)

                    value = usage.get("cached_input_tokens")
                    if isinstance(value, (int, float)):
                        cached_input_tokens = int(value)

                    value = usage.get("reasoning_output_tokens")
                    if isinstance(value, (int, float)):
                        reasoning_output_tokens = int(value)

                    current_rate_limits = payload.get("rate_limits")
                    if isinstance(current_rate_limits, dict):
                        rate_limits = current_rate_limits

                timestamp = event.get("timestamp") or payload.get("timestamp")
                if timestamp:
                    last_event_timestamp = timestamp

    except Exception as e:
        return {
            "error": str(e),
            "session_file": str(path),
        }

    context_left_percent = None
    context_used_percent = None

    if context_window and total_tokens is not None:
        remaining = max(context_window - total_tokens, 0)
        context_left_percent = round(remaining / context_window * 100)
        context_used_percent = round(total_tokens / context_window * 100)

    try:
        mtime = path.stat().st_mtime
        file_updated_at = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
    except Exception:
        file_updated_at = None

    cwd = normalize_path(cwd)

    return {
        "thread": thread_id,
        "project": project_name_from_path(cwd),
        "project_path": cwd,
        "context": {
            "used": total_tokens,
            "max": context_window,
            "left_percent": context_left_percent,
            "used_percent": context_used_percent,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
        },
        "rate_limits": rate_limits,
        "created_at": session_created_at,
        "last_event_at": last_event_timestamp,
        "file_updated_at": file_updated_at,
        "session_file": str(path),
    }
