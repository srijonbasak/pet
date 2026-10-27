import threading
import time
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import (
    CODEX_HOME, SESSIONS_DIR, ARCHIVED_DIR, OUTPUT_FILE, QUOTA_REFRESH_SECONDS, LOCAL_EVENT_DEBOUNCE_SECONDS
)
from .utils import now_iso, write_json_file
from .session_parser import get_all_session_files, inspect_session, find_latest_session
from .thread_metadata import get_thread_title_map
from .cache import load_cache, refresh_quota_if_needed, update_quota_from_session
from .models import MonitorState
from .providers import get_provider_snapshot, watch_roots

STATE_LOCK = threading.Lock()
LAST_LOCAL_UPDATE = 0.0
STATE_CALLBACKS = []
LATEST_SNAPSHOT = None
ACTIVE_PROVIDER = "codex"

def register_state_callback(cb):
    STATE_CALLBACKS.append(cb)

def _snapshot_to_state(snapshot) -> MonitorState:
    active = snapshot.get("active") or {}
    limits = snapshot.get("limits") or {}
    five = limits.get("5h") or {}
    seven = limits.get("7d") or {}
    ctx = active.get("context") or {}

    return MonitorState(
        provider=active.get("provider"),
        project=active.get("project"),
        chat=active.get("chat"),
        thread_id=active.get("thread"),
        context_left=ctx.get("left_percent"),
        context_used=ctx.get("used"),
        context_max=ctx.get("max"),
        limit_5h_left=five.get("left_percent"),
        limit_5h_reset=five.get("reset"),
        limit_7d_left=seven.get("left_percent"),
        limit_7d_reset=seven.get("reset"),
    )

def notify_state_changed(snapshot):
    state = _snapshot_to_state(snapshot)
    for cb in STATE_CALLBACKS:
        try:
            cb(state)
        except Exception as e:
            print(f"Callback error: {e}")

def get_latest_state():
    if LATEST_SNAPSHOT:
        return _snapshot_to_state(LATEST_SNAPSHOT)
    return None

def set_active_provider(provider):
    global ACTIVE_PROVIDER
    ACTIVE_PROVIDER = "codex"
    with STATE_LOCK:
        return build_snapshot(include_projects=False, refresh_quota=False)

def build_local_project_index():
    title_map = get_thread_title_map()
    projects = {}

    for session_file in get_all_session_files():
        session = inspect_session(session_file)
        if not session or session.get("error"):
            continue

        thread_id = session.get("thread")
        if not thread_id:
            continue

        project_path = session.get("project_path")
        project_name = session.get("project") or "Unknown Project"
        project_key = project_path or project_name

        if project_key not in projects:
            projects[project_key] = {
                "name": project_name,
                "path": project_path,
                "chats": [],
            }

        chat_name = title_map.get(str(thread_id))
        if not chat_name:
            chat_name = f"Thread {str(thread_id)[:8]}"

        projects[project_key]["chats"].append({
            "name": chat_name,
            "thread": thread_id,
            "context": session.get("context"),
            "last_event_at": session.get("last_event_at"),
            "file_updated_at": session.get("file_updated_at"),
            "session_file": session.get("session_file"),
        })

    result = list(projects.values())

    def chat_timestamp(chat):
        try:
            return Path(chat["session_file"]).stat().st_mtime
        except Exception:
            return 0

    for project in result:
        project["chats"].sort(key=chat_timestamp, reverse=True)

    def project_timestamp(project):
        if not project["chats"]:
            return 0
        return chat_timestamp(project["chats"][0])

    result.sort(key=project_timestamp, reverse=True)
    return result

def get_active_local_state():
    snapshot = get_provider_snapshot(ACTIVE_PROVIDER)
    if snapshot:
        snapshot.pop("_mtime", None)
    return snapshot

def build_snapshot(include_projects=True, refresh_quota=False):
    global LATEST_SNAPSHOT
    cache = load_cache()
    active = get_active_local_state()
    session_rate_limits = active.pop("_rate_limits", None) if active else None
    if session_rate_limits:
        cache = update_quota_from_session(cache, session_rate_limits)
        limits = cache.get("limits")
    else:
        cache = refresh_quota_if_needed(cache, force=refresh_quota)
        limits = cache.get("limits")

    snapshot = {
        "active": active,
        "limits": limits,
        "quota_error": cache.get("quota_error"),
        "updated_at": now_iso(),
    }

    if include_projects:
        snapshot["local_projects"] = build_local_project_index()

    write_json_file(OUTPUT_FILE, snapshot)
    LATEST_SNAPSHOT = snapshot
    notify_state_changed(snapshot)
    return snapshot

def progress_bar(percent, length=30):
    if percent is None:
        return ""
    percent = max(0, min(100, float(percent)))
    filled = round(length * percent / 100)
    return "█" * filled + "░" * (length - filled)

def print_snapshot(snapshot):
    active = snapshot.get("active") or {}
    print("\nProject:")
    print(active.get("project") or "Unknown")
    if active.get("project_path"):
        print("Path:", active["project_path"])

    print("\nChat:")
    print(active.get("chat") or "Unknown")
    if active.get("thread"):
        print("Thread:", active["thread"])

    print("\nContext:")
    context = active.get("context") or {}
    left = context.get("left_percent")
    used = context.get("used")
    maximum = context.get("max")
    
    if left is not None and used is not None and maximum is not None:
        print(f"{left}% left ({used:,} used / {maximum:,})")
        print(progress_bar(left))
    else:
        print("Unavailable")

    limits = snapshot.get("limits") or {}
    
    print("\n5h limit:")
    five = limits.get("5h")
    if five:
        print(progress_bar(five.get("left_percent")))
        print(f'{five.get("left_percent")}% left (resets {five.get("reset")})')
    else:
        print("Unavailable")

    print("\n7d limit:")
    seven = limits.get("7d")
    if seven:
        print(progress_bar(seven.get("left_percent")))
        print(f'{seven.get("left_percent")}% left (resets {seven.get("reset")})')
    else:
        print("Unavailable")

    if limits.get("plan"):
        print("\nPlan:", limits["plan"])

    credits = limits.get("credits") or {}
    if credits.get("balance") is not None:
        print("Credits:", credits["balance"])

    projects = snapshot.get("local_projects") or []
    print(f"\nLocal projects detected: {len(projects)}")
    for project in projects:
        chats = project.get("chats") or []
        print(f'  - {project["name"]} ({len(chats)} chats)')
        for chat_index, chat in enumerate(chats, start=1):
            ctx = chat.get("context") or {}
            cleft = ctx.get("left_percent")
            extra = f" | {cleft}% left" if cleft is not None else ""
            print(f'   {chat_index}. {chat["name"]}{extra}')

    if snapshot.get("quota_error"):
        print("\nQuota warning:", snapshot["quota_error"])

    print("\nUpdated:", snapshot["updated_at"])
    print("JSON output:", OUTPUT_FILE)

def print_projects():
    projects = build_local_project_index()
    print()
    for index, project in enumerate(projects, start=1):
        print(f'{index}. {project["name"]}')
        if project.get("path"):
            print("   Path:", project["path"])
        chats = project.get("chats") or []
        for chat_index, chat in enumerate(chats, start=1):
            ctx = chat.get("context") or {}
            cleft = ctx.get("left_percent")
            extra = f" | {cleft}% left" if cleft is not None else ""
            print(f'   {chat_index}. {chat["name"]}{extra}')
        print()

class CodexFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        self.handle_event(event)

    def on_created(self, event):
        self.handle_event(event)

    def handle_event(self, event):
        global LAST_LOCAL_UPDATE

        if event.is_directory:
            return

        path = Path(event.src_path)
        relevant = (
            path.suffix.lower() in {".jsonl", ".sqlite", ".vscdb"}
            or path.name == "workspace.json"
            or path.name.startswith("state.vscdb")
        )

        if not relevant:
            return

        now = time.time()
        if now - LAST_LOCAL_UPDATE < LOCAL_EVENT_DEBOUNCE_SECONDS:
            return

        LAST_LOCAL_UPDATE = now

        try:
            with STATE_LOCK:
                snapshot = build_snapshot(include_projects=True, refresh_quota=False)
            
            print("\n[local update]")
            active = snapshot.get("active") or {}
            print("Project:", active.get("project"))
            print("Chat:", active.get("chat"))
            context = active.get("context") or {}
            print("Context left:", context.get("left_percent"))
        except Exception as e:
            print("Local update error:", e)

def quota_worker(stop_event):
    while not stop_event.wait(QUOTA_REFRESH_SECONDS):
        try:
            with STATE_LOCK:
                snapshot = build_snapshot(include_projects=True, refresh_quota=True)
            
            limits = snapshot.get("limits") or {}
            five = limits.get("5h") or {}
            seven = limits.get("7d") or {}
            
            print("\n[quota refresh]")
            print("5h:", five.get("left_percent"))
            print("7d:", seven.get("left_percent"))
        except Exception as e:
            print("Quota refresh error:", e)

def run_watch_mode(run_event_loop=True):
    print("Starting Codex usage monitor...")
    print("Codex home:", CODEX_HOME)
    print("Output JSON:", OUTPUT_FILE)
    print("Quota refresh:", f"{QUOTA_REFRESH_SECONDS} seconds")

    with STATE_LOCK:
        snapshot = build_snapshot(include_projects=True, refresh_quota=False)
    
    print_snapshot(snapshot)

    event_handler = CodexFileHandler()
    observer = Observer()
    watched_anything = False

    scheduled = set()
    for root in watch_roots():
        resolved = str(root.resolve())
        if resolved in scheduled:
            continue
        observer.schedule(event_handler, resolved, recursive=root != CODEX_HOME)
        scheduled.add(resolved)
        watched_anything = True

    if not watched_anything:
        raise RuntimeError("Could not find the Codex data folder.")

    observer.start()
    stop_event = threading.Event()
    quota_thread = threading.Thread(target=quota_worker, args=(stop_event,), daemon=True)
    quota_thread.start()

    if not run_event_loop:
        return observer, stop_event

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping monitor...")
    finally:
        stop_event.set()
        observer.stop()
        observer.join()
