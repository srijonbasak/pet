#!/usr/bin/env python3

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# ============================================================
# CONFIG
# ============================================================

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

CACHE_FILE = Path(__file__).resolve().parent / "codex_cache.json"
OUTPUT_FILE = Path(__file__).resolve().parent / "codex_live.json"

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

# Remote quota refresh.
# Local session/context updates do NOT wait for this.
QUOTA_REFRESH_SECONDS = 300  # 5 minutes

# Avoid processing many filesystem events from the same write burst.
LOCAL_EVENT_DEBOUNCE_SECONDS = 0.35


# ============================================================
# SHARED STATE
# ============================================================

STATE_LOCK = threading.Lock()
LAST_LOCAL_UPDATE = 0.0


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_json_load(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def now_iso():
    return datetime.now().isoformat(
        timespec="seconds"
    )


def read_json_file(path):
    if not path.exists():
        return None

    try:
        with path.open(
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)
    except Exception:
        return None


def write_json_file(path, data):
    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    temp_path.replace(path)


def normalize_path(value):
    if not value:
        return None

    try:
        return str(Path(value))
    except Exception:
        return str(value)


def project_name_from_path(path):
    if not path:
        return None

    try:
        p = Path(path)

        if p.name:
            return p.name

        return str(p)

    except Exception:
        return str(path)


# ============================================================
# SESSION FILE DISCOVERY
# ============================================================

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


# ============================================================
# SESSION PARSER
# ============================================================

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

                payload = (
                    event.get("payload")
                    or {}
                )

                event_type = (
                    event.get("type")
                )

                payload_type = (
                    payload.get("type")
                )

                # --------------------------------------------
                # Session metadata
                # --------------------------------------------

                if event_type == "session_meta":
                    thread_id = (
                        payload.get("id")
                        or payload.get("session_id")
                        or thread_id
                    )

                    cwd = (
                        payload.get("cwd")
                        or payload.get(
                            "working_directory"
                        )
                        or cwd
                    )

                    session_created_at = (
                        payload.get("timestamp")
                        or payload.get("created_at")
                        or session_created_at
                    )

                if payload_type == "session_meta":
                    thread_id = (
                        payload.get("id")
                        or payload.get("session_id")
                        or thread_id
                    )

                    cwd = (
                        payload.get("cwd")
                        or payload.get(
                            "working_directory"
                        )
                        or cwd
                    )

                # --------------------------------------------
                # Turn/task context
                # --------------------------------------------

                if payload_type in {
                    "turn_context",
                    "task_started",
                    "turn_started",
                }:
                    cwd = (
                        payload.get("cwd")
                        or payload.get(
                            "working_directory"
                        )
                        or cwd
                    )

                    cw = payload.get(
                        "model_context_window"
                    )

                    if isinstance(
                        cw,
                        (int, float)
                    ):
                        context_window = int(cw)

                # --------------------------------------------
                # Token count events
                # --------------------------------------------

                if payload_type == "token_count":
                    info = (
                        payload.get("info")
                        or {}
                    )

                    cw = info.get(
                        "model_context_window"
                    )

                    if isinstance(
                        cw,
                        (int, float)
                    ):
                        context_window = int(cw)

                    usage = (
                        info.get(
                            "last_token_usage"
                        )
                        or info.get(
                            "total_token_usage"
                        )
                        or {}
                    )

                    value = usage.get(
                        "total_tokens"
                    )

                    if isinstance(
                        value,
                        (int, float)
                    ):
                        total_tokens = int(value)

                    value = usage.get(
                        "input_tokens"
                    )

                    if isinstance(
                        value,
                        (int, float)
                    ):
                        input_tokens = int(value)

                    value = usage.get(
                        "output_tokens"
                    )

                    if isinstance(
                        value,
                        (int, float)
                    ):
                        output_tokens = int(value)

                    value = usage.get(
                        "cached_input_tokens"
                    )

                    if isinstance(
                        value,
                        (int, float)
                    ):
                        cached_input_tokens = int(
                            value
                        )

                    value = usage.get(
                        "reasoning_output_tokens"
                    )

                    if isinstance(
                        value,
                        (int, float)
                    ):
                        reasoning_output_tokens = int(
                            value
                        )

                timestamp = (
                    event.get("timestamp")
                    or payload.get("timestamp")
                )

                if timestamp:
                    last_event_timestamp = (
                        timestamp
                    )

    except Exception as e:
        return {
            "error": str(e),
            "session_file": str(path),
        }

    context_left_percent = None
    context_used_percent = None

    if (
        context_window
        and total_tokens is not None
    ):
        remaining = max(
            context_window - total_tokens,
            0
        )

        context_left_percent = round(
            remaining
            / context_window
            * 100
        )

        context_used_percent = round(
            total_tokens
            / context_window
            * 100
        )

    try:
        mtime = path.stat().st_mtime

        file_updated_at = (
            datetime.fromtimestamp(
                mtime
            ).isoformat(
                timespec="seconds"
            )
        )

    except Exception:
        file_updated_at = None

    cwd = normalize_path(cwd)

    return {
        "thread": thread_id,

        "project": (
            project_name_from_path(cwd)
        ),

        "project_path": cwd,

        "context": {
            "used": total_tokens,
            "max": context_window,

            "left_percent":
                context_left_percent,

            "used_percent":
                context_used_percent,

            "input_tokens":
                input_tokens,

            "output_tokens":
                output_tokens,

            "cached_input_tokens":
                cached_input_tokens,

            "reasoning_output_tokens":
                reasoning_output_tokens,
        },

        "created_at":
            session_created_at,

        "last_event_at":
            last_event_timestamp,

        "file_updated_at":
            file_updated_at,

        "session_file":
            str(path),
    }


# ============================================================
# THREAD NAME - session_index.jsonl
# ============================================================

def load_thread_names_from_index():
    result = {}

    if not SESSION_INDEX_FILE.exists():
        return result

    try:
        with SESSION_INDEX_FILE.open(
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as f:

            for raw_line in f:
                line = raw_line.strip()

                if not line:
                    continue

                item = safe_json_load(line)

                if not item:
                    continue

                thread_id = (
                    item.get("thread_id")
                    or item.get("id")
                    or item.get("session_id")
                )

                name = (
                    item.get("thread_name")
                    or item.get("title")
                    or item.get("name")
                )

                if (
                    thread_id
                    and isinstance(name, str)
                    and name.strip()
                ):
                    result[str(thread_id)] = (
                        name.strip()
                    )

    except Exception:
        pass

    return result


# ============================================================
# THREAD NAME - SQLITE
# ============================================================

def load_thread_names_from_sqlite():
    result = {}

    sqlite_files = list(
        CODEX_HOME.glob("*.sqlite")
    )

    if not sqlite_files:
        return result

    preferred = [
        CODEX_HOME / "state_5.sqlite",
        CODEX_HOME / "state.sqlite",
    ]

    ordered_files = []

    for db in preferred:
        if db.exists():
            ordered_files.append(db)

    for db in sqlite_files:
        if db not in ordered_files:
            ordered_files.append(db)

    possible_id_columns = {
        "id",
        "thread_id",
        "session_id",
        "conversation_id",
    }

    possible_name_columns = {
        "thread_name",
        "title",
        "name",
        "display_name",
    }

    for db_path in ordered_files:

        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro",
                uri=True,
                timeout=1
            )

            cursor = conn.cursor()

            tables = cursor.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                """
            ).fetchall()

            for table_row in tables:
                table = table_row[0]

                try:
                    columns = cursor.execute(
                        f'PRAGMA table_info("{table}")'
                    ).fetchall()

                except Exception:
                    continue

                column_names = [
                    row[1]
                    for row in columns
                ]

                id_columns = [
                    col
                    for col in column_names
                    if col.lower()
                    in possible_id_columns
                ]

                name_columns = [
                    col
                    for col in column_names
                    if col.lower()
                    in possible_name_columns
                ]

                if not id_columns:
                    continue

                if not name_columns:
                    continue

                for id_col in id_columns:

                    for name_col in name_columns:

                        query = (
                            f'SELECT '
                            f'"{id_col}", '
                            f'"{name_col}" '
                            f'FROM "{table}"'
                        )

                        try:
                            rows = cursor.execute(
                                query
                            ).fetchall()

                        except Exception:
                            continue

                        for row in rows:
                            if len(row) < 2:
                                continue

                            thread_id = row[0]
                            name = row[1]

                            if (
                                thread_id
                                and isinstance(
                                    name,
                                    str
                                )
                                and name.strip()
                            ):
                                result[
                                    str(thread_id)
                                ] = (
                                    name.strip()
                                )

            conn.close()

        except Exception:
            continue

    return result


def get_thread_title_map():
    titles = {}

    # SQLite fallback first
    titles.update(
        load_thread_names_from_sqlite()
    )

    # Index gets precedence
    titles.update(
        load_thread_names_from_index()
    )

    return titles


# ============================================================
# LOCAL PROJECT / CHAT INDEX
# ============================================================

def build_local_project_index():
    title_map = get_thread_title_map()

    projects = {}

    for session_file in get_all_session_files():

        session = inspect_session(
            session_file
        )

        if not session:
            continue

        if session.get("error"):
            continue

        thread_id = session.get(
            "thread"
        )

        if not thread_id:
            continue

        project_path = session.get(
            "project_path"
        )

        project_name = (
            session.get("project")
            or "Unknown Project"
        )

        project_key = (
            project_path
            or project_name
        )

        if project_key not in projects:
            projects[project_key] = {
                "name": project_name,
                "path": project_path,
                "chats": [],
            }

        chat_name = title_map.get(
            str(thread_id)
        )

        if not chat_name:
            chat_name = (
                f"Thread {str(thread_id)[:8]}"
            )

        projects[
            project_key
        ]["chats"].append(
            {
                "name": chat_name,

                "thread": thread_id,

                "context":
                    session.get(
                        "context"
                    ),

                "last_event_at":
                    session.get(
                        "last_event_at"
                    ),

                "file_updated_at":
                    session.get(
                        "file_updated_at"
                    ),

                "session_file":
                    session.get(
                        "session_file"
                    ),
            }
        )

    result = list(
        projects.values()
    )

    def chat_timestamp(chat):
        try:
            return Path(
                chat["session_file"]
            ).stat().st_mtime
        except Exception:
            return 0

    for project in result:
        project["chats"].sort(
            key=chat_timestamp,
            reverse=True
        )

    def project_timestamp(project):
        if not project["chats"]:
            return 0

        return chat_timestamp(
            project["chats"][0]
        )

    result.sort(
        key=project_timestamp,
        reverse=True
    )

    return result


# ============================================================
# ACTIVE LOCAL SESSION
# ============================================================

def get_active_local_state():
    latest_file = (
        find_latest_session()
    )

    if not latest_file:
        return None

    session = inspect_session(
        latest_file
    )

    if not session:
        return None

    title_map = (
        get_thread_title_map()
    )

    thread_id = session.get(
        "thread"
    )

    chat_name = None

    if thread_id:
        chat_name = title_map.get(
            str(thread_id)
        )

    if (
        not chat_name
        and thread_id
    ):
        chat_name = (
            f"Thread {str(thread_id)[:8]}"
        )

    return {
        "project":
            session.get("project"),

        "project_path":
            session.get(
                "project_path"
            ),

        "chat":
            chat_name,

        "thread":
            thread_id,

        "context":
            session.get(
                "context"
            ),

        "last_event_at":
            session.get(
                "last_event_at"
            ),

        "file_updated_at":
            session.get(
                "file_updated_at"
            ),

        "session_file":
            session.get(
                "session_file"
            ),
    }


# ============================================================
# AUTH
# ============================================================

def read_auth():
    if not AUTH_FILE.exists():
        raise RuntimeError(
            f"Codex auth file not found: "
            f"{AUTH_FILE}"
        )

    with AUTH_FILE.open(
        "r",
        encoding="utf-8"
    ) as f:
        auth = json.load(f)

    tokens = (
        auth.get("tokens")
        or {}
    )

    access_token = (
        tokens.get("access_token")
        or auth.get("access_token")
    )

    account_id = (
        tokens.get("account_id")
        or auth.get("account_id")
    )

    if not access_token:
        raise RuntimeError(
            "No OAuth access token "
            "found in auth.json"
        )

    return (
        access_token,
        account_id
    )


# ============================================================
# REMOTE QUOTA
# ============================================================

def fetch_usage():
    access_token, account_id = (
        read_auth()
    )

    headers = {
        "Authorization":
            f"Bearer {access_token}",

        "Accept":
            "application/json",

        "User-Agent":
            "codex-cli",
    }

    if account_id:
        headers[
            "ChatGPT-Account-Id"
        ] = account_id

    request = urllib.request.Request(
        USAGE_URL,
        headers=headers,
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            body = (
                response
                .read()
                .decode("utf-8")
            )

            return json.loads(body)

    except urllib.error.HTTPError as e:

        if e.code == 401:
            raise RuntimeError(
                "Codex token rejected (401)"
            )

        if e.code == 403:
            raise RuntimeError(
                "Codex usage API returned 403"
            )

        raise RuntimeError(
            f"Codex usage HTTP error: "
            f"{e.code}"
        )

    except urllib.error.URLError as e:

        raise RuntimeError(
            f"Network error: {e.reason}"
        )


def format_reset(
    timestamp,
    window_seconds
):
    if not timestamp:
        return None

    dt = datetime.fromtimestamp(
        timestamp
    )

    if (
        window_seconds
        <= 6 * 60 * 60
    ):
        return (
            dt.strftime("%I:%M %p")
            .lstrip("0")
        )

    return dt.strftime(
        "%b %d"
    )


def parse_window(window):
    if not window:
        return None

    used_percent = window.get(
        "used_percent"
    )

    if used_percent is None:
        return None

    used_percent = float(
        used_percent
    )

    left_percent = max(
        0,
        min(
            100,
            100 - used_percent
        )
    )

    if float(
        left_percent
    ).is_integer():
        left_percent = int(
            left_percent
        )

    reset_at = window.get(
        "reset_at"
    )

    window_seconds = window.get(
        "limit_window_seconds"
    )

    return {
        "used_percent":
            used_percent,

        "left_percent":
            left_percent,

        "reset_at":
            reset_at,

        "reset":
            format_reset(
                reset_at,
                window_seconds or 0
            ),

        "window_seconds":
            window_seconds,
    }


def parse_limits(api_data):
    rate_limit = (
        api_data.get("rate_limit")
        or {}
    )

    primary = parse_window(
        rate_limit.get(
            "primary_window"
        )
    )

    secondary = parse_window(
        rate_limit.get(
            "secondary_window"
        )
    )

    five_hour = None
    seven_day = None

    for window in [
        primary,
        secondary
    ]:
        if not window:
            continue

        seconds = (
            window.get(
                "window_seconds"
            )
            or 0
        )

        if (
            4 * 3600
            <= seconds
            <= 6 * 3600
        ):
            five_hour = window

        elif (
            6 * 86400
            <= seconds
            <= 8 * 86400
        ):
            seven_day = window

    if not five_hour:
        five_hour = primary

    if not seven_day:
        seven_day = secondary

    credits_data = (
        api_data.get("credits")
        or {}
    )

    return {
        "5h": five_hour,

        "7d": seven_day,

        "plan":
            api_data.get(
                "plan_type"
            ),

        "credits": {
            "balance":
                credits_data.get(
                    "balance"
                ),

            "has_credits":
                credits_data.get(
                    "has_credits"
                ),

            "unlimited":
                credits_data.get(
                    "unlimited"
                ),
        },

        "fetched_at":
            now_iso(),
    }


# ============================================================
# CACHE
# ============================================================

def load_cache():
    cache = read_json_file(
        CACHE_FILE
    )

    if not isinstance(
        cache,
        dict
    ):
        cache = {}

    return cache


def save_cache(cache):
    write_json_file(
        CACHE_FILE,
        cache
    )


def quota_cache_is_fresh(cache):
    quota = cache.get(
        "limits"
    )

    if not quota:
        return False

    timestamp = cache.get(
        "limits_fetched_epoch"
    )

    if not timestamp:
        return False

    age = (
        time.time()
        - timestamp
    )

    return (
        age
        < QUOTA_REFRESH_SECONDS
    )


def refresh_quota_if_needed(
    cache,
    force=False
):
    if (
        not force
        and quota_cache_is_fresh(
            cache
        )
    ):
        return cache

    try:
        raw = fetch_usage()

        limits = parse_limits(
            raw
        )

        cache["limits"] = limits

        cache[
            "limits_fetched_epoch"
        ] = time.time()

        cache["quota_error"] = None

        save_cache(cache)

    except Exception as e:
        cache["quota_error"] = str(e)

    return cache


# ============================================================
# BUILD CURRENT OUTPUT
# ============================================================

def build_snapshot(
    include_projects=True,
    refresh_quota=False
):
    cache = load_cache()

    cache = refresh_quota_if_needed(
        cache,
        force=refresh_quota
    )

    active = (
        get_active_local_state()
    )

    snapshot = {
        "active":
            active,

        "limits":
            cache.get(
                "limits"
            ),

        "quota_error":
            cache.get(
                "quota_error"
            ),

        "updated_at":
            now_iso(),
    }

    if include_projects:
        snapshot[
            "local_projects"
        ] = (
            build_local_project_index()
        )

    write_json_file(
        OUTPUT_FILE,
        snapshot
    )

    return snapshot


# ============================================================
# DISPLAY
# ============================================================

def progress_bar(
    percent,
    length=30
):
    if percent is None:
        return ""

    percent = max(
        0,
        min(
            100,
            float(percent)
        )
    )

    filled = round(
        length
        * percent
        / 100
    )

    return (
        "█" * filled
        + "░" * (
            length - filled
        )
    )


def print_snapshot(snapshot):
    active = (
        snapshot.get("active")
        or {}
    )

    print()
    print("Project:")
    print(
        active.get("project")
        or "Unknown"
    )

    if active.get(
        "project_path"
    ):
        print(
            "Path:",
            active["project_path"]
        )

    print()
    print("Chat:")
    print(
        active.get("chat")
        or "Unknown"
    )

    if active.get("thread"):
        print(
            "Thread:",
            active["thread"]
        )

    print()

    context = (
        active.get("context")
        or {}
    )

    print("Context:")

    left = context.get(
        "left_percent"
    )

    used = context.get(
        "used"
    )

    maximum = context.get(
        "max"
    )

    if (
        left is not None
        and used is not None
        and maximum is not None
    ):
        print(
            f"{left}% left "
            f"({used:,} used / "
            f"{maximum:,})"
        )

        print(
            progress_bar(left)
        )

    else:
        print("Unavailable")

    limits = (
        snapshot.get("limits")
        or {}
    )

    print()

    five = limits.get("5h")

    print("5h limit:")

    if five:
        print(
            progress_bar(
                five.get(
                    "left_percent"
                )
            )
        )

        print(
            f'{five.get("left_percent")}% left '
            f'(resets {five.get("reset")})'
        )

    else:
        print("Unavailable")

    print()

    seven = limits.get("7d")

    print("7d limit:")

    if seven:
        print(
            progress_bar(
                seven.get(
                    "left_percent"
                )
            )
        )

        print(
            f'{seven.get("left_percent")}% left '
            f'(resets {seven.get("reset")})'
        )

    else:
        print("Unavailable")

    if limits.get("plan"):
        print()
        print(
            "Plan:",
            limits["plan"]
        )

    credits = (
        limits.get("credits")
        or {}
    )

    if (
        credits.get("balance")
        is not None
    ):
        print(
            "Credits:",
            credits["balance"]
        )

    projects = (
        snapshot.get(
            "local_projects"
        )
        or []
    )

    print()
    print(
        f"Local projects detected: "
        f"{len(projects)}"
    )

    for project in projects:
        chats = (
            project.get(
                "chats"
            )
            or []
        )

        print(
            f'  - {project["name"]} '
            f'({len(chats)} chats)'
        )

    if snapshot.get(
        "quota_error"
    ):
        print()
        print(
            "Quota warning:",
            snapshot[
                "quota_error"
            ]
        )

    print()

    print(
        "Updated:",
        snapshot[
            "updated_at"
        ]
    )

    print(
        "JSON output:",
        OUTPUT_FILE
    )


# ============================================================
# FILE WATCHER
# ============================================================

class CodexFileHandler(
    FileSystemEventHandler
):
    def on_modified(
        self,
        event
    ):
        self.handle_event(
            event
        )

    def on_created(
        self,
        event
    ):
        self.handle_event(
            event
        )

    def handle_event(
        self,
        event
    ):
        global LAST_LOCAL_UPDATE

        if event.is_directory:
            return

        path = Path(
            event.src_path
        )

        relevant = False

        if (
            path.suffix.lower()
            == ".jsonl"
        ):
            relevant = True

        if (
            path.suffix.lower()
            == ".sqlite"
        ):
            relevant = True

        if not relevant:
            return

        now = time.time()

        if (
            now - LAST_LOCAL_UPDATE
            < LOCAL_EVENT_DEBOUNCE_SECONDS
        ):
            return

        LAST_LOCAL_UPDATE = now

        try:
            with STATE_LOCK:
                snapshot = build_snapshot(
                    include_projects=True,
                    refresh_quota=False
                )

            print()
            print(
                "[local update]"
            )

            active = (
                snapshot.get("active")
                or {}
            )

            print(
                "Project:",
                active.get(
                    "project"
                )
            )

            print(
                "Chat:",
                active.get(
                    "chat"
                )
            )

            context = (
                active.get(
                    "context"
                )
                or {}
            )

            print(
                "Context left:",
                context.get(
                    "left_percent"
                )
            )

        except Exception as e:
            print(
                "Local update error:",
                e
            )


# ============================================================
# QUOTA BACKGROUND LOOP
# ============================================================

def quota_worker(
    stop_event
):
    while not stop_event.wait(
        QUOTA_REFRESH_SECONDS
    ):
        try:
            with STATE_LOCK:
                snapshot = build_snapshot(
                    include_projects=True,
                    refresh_quota=True
                )

            limits = (
                snapshot.get(
                    "limits"
                )
                or {}
            )

            five = (
                limits.get("5h")
                or {}
            )

            seven = (
                limits.get("7d")
                or {}
            )

            print()
            print(
                "[quota refresh]"
            )

            print(
                "5h:",
                five.get(
                    "left_percent"
                )
            )

            print(
                "7d:",
                seven.get(
                    "left_percent"
                )
            )

        except Exception as e:
            print(
                "Quota refresh error:",
                e
            )


# ============================================================
# WATCH MODE
# ============================================================

def run_watch_mode():
    print(
        "Starting Codex local monitor..."
    )

    print(
        "Codex home:",
        CODEX_HOME
    )

    print(
        "Output JSON:",
        OUTPUT_FILE
    )

    print(
        "Quota refresh:",
        f"{QUOTA_REFRESH_SECONDS} seconds"
    )

    with STATE_LOCK:
        snapshot = build_snapshot(
            include_projects=True,
            refresh_quota=False
        )

    print_snapshot(
        snapshot
    )

    event_handler = (
        CodexFileHandler()
    )

    observer = Observer()

    watched_anything = False

    if SESSIONS_DIR.exists():
        observer.schedule(
            event_handler,
            str(SESSIONS_DIR),
            recursive=True
        )

        watched_anything = True

    if ARCHIVED_DIR.exists():
        observer.schedule(
            event_handler,
            str(ARCHIVED_DIR),
            recursive=True
        )

        watched_anything = True

    if CODEX_HOME.exists():
        observer.schedule(
            event_handler,
            str(CODEX_HOME),
            recursive=False
        )

        watched_anything = True

    if not watched_anything:
        raise RuntimeError(
            "Could not find Codex folders."
        )

    observer.start()

    stop_event = threading.Event()

    quota_thread = threading.Thread(
        target=quota_worker,
        args=(stop_event,),
        daemon=True
    )

    quota_thread.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print()
        print("Stopping monitor...")

    finally:
        stop_event.set()

        observer.stop()
        observer.join()


# ============================================================
# PROJECT LIST
# ============================================================

def print_projects():
    projects = (
        build_local_project_index()
    )

    print()

    for index, project in enumerate(
        projects,
        start=1
    ):
        print(
            f"{index}. "
            f'{project["name"]}'
        )

        if project.get("path"):
            print(
                "   Path:",
                project["path"]
            )

        chats = (
            project.get(
                "chats"
            )
            or []
        )

        for chat_index, chat in enumerate(
            chats,
            start=1
        ):
            context = (
                chat.get(
                    "context"
                )
                or {}
            )

            left = context.get(
                "left_percent"
            )

            extra = ""

            if left is not None:
                extra = (
                    f" | {left}% left"
                )

            print(
                f"   {chat_index}. "
                f'{chat["name"]}'
                f"{extra}"
            )

        print()


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Local-first Codex desktop "
            "monitor."
        )
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Watch Codex local files "
            "and update automatically"
        )
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print current state as JSON"
        )
    )

    parser.add_argument(
        "--projects",
        action="store_true",
        help=(
            "Show detected local projects "
            "and chats"
        )
    )

    parser.add_argument(
        "--refresh-quota",
        action="store_true",
        help=(
            "Force refresh 5h/7d quota"
        )
    )

    args = parser.parse_args()

    if args.watch:
        run_watch_mode()
        return

    if args.projects:
        print_projects()
        return

    with STATE_LOCK:
        snapshot = build_snapshot(
            include_projects=True,
            refresh_quota=(
                args.refresh_quota
            )
        )

    if args.json:
        print(
            json.dumps(
                snapshot,
                indent=2,
                ensure_ascii=False
            )
        )

    else:
        print_snapshot(
            snapshot
        )


if __name__ == "__main__":
    main()