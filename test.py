#!/usr/bin/env python3

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error

from pathlib import Path
from datetime import datetime


# ============================================================
# Configuration
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

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


# ============================================================
# Helpers
# ============================================================

def safe_json_load(line):
    try:
        return json.loads(line)
    except Exception:
        return None


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
        return Path(path).name or path
    except Exception:
        return path


# ============================================================
# Find all session files
# ============================================================

def get_all_session_files():
    files = []

    if SESSIONS_DIR.exists():
        files.extend(
            SESSIONS_DIR.rglob("rollout-*.jsonl")
        )

    if ARCHIVED_DIR.exists():
        files.extend(
            ARCHIVED_DIR.rglob("rollout-*.jsonl")
        )

    return list(files)


def find_latest_session():
    files = get_all_session_files()

    if not files:
        raise RuntimeError(
            f"No Codex session files found under: {CODEX_HOME}"
        )

    return max(
        files,
        key=lambda p: p.stat().st_mtime
    )


# ============================================================
# Read session information
# ============================================================

def inspect_session(path):
    thread_id = None
    cwd = None

    context_window = None
    total_tokens = None
    input_tokens = None
    output_tokens = None
    cached_input_tokens = None
    reasoning_output_tokens = None

    created_at = None
    updated_at = None

    with path.open(
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as f:

        for line in f:
            line = line.strip()

            if not line:
                continue

            event = safe_json_load(line)

            if not event:
                continue

            payload = event.get("payload") or {}

            # -----------------------------------------------
            # Session metadata
            # -----------------------------------------------

            if event.get("type") == "session_meta":
                thread_id = (
                    payload.get("id")
                    or payload.get("session_id")
                    or thread_id
                )

                cwd = (
                    payload.get("cwd")
                    or payload.get("working_directory")
                    or cwd
                )

                created_at = (
                    payload.get("timestamp")
                    or payload.get("created_at")
                    or created_at
                )

            # Some versions may nest session_meta
            if payload.get("type") == "session_meta":
                thread_id = (
                    payload.get("id")
                    or payload.get("session_id")
                    or thread_id
                )

                cwd = (
                    payload.get("cwd")
                    or payload.get("working_directory")
                    or cwd
                )

            # -----------------------------------------------
            # Turn/task context
            # -----------------------------------------------

            if payload.get("type") in {
                "turn_context",
                "task_started",
                "turn_started"
            }:

                cwd = (
                    payload.get("cwd")
                    or payload.get("working_directory")
                    or cwd
                )

                cw = payload.get(
                    "model_context_window"
                )

                if isinstance(cw, (int, float)):
                    context_window = int(cw)

            # -----------------------------------------------
            # Token usage
            # -----------------------------------------------

            if payload.get("type") == "token_count":

                info = payload.get("info") or {}

                cw = info.get(
                    "model_context_window"
                )

                if isinstance(cw, (int, float)):
                    context_window = int(cw)

                usage = (
                    info.get("last_token_usage")
                    or info.get("total_token_usage")
                    or {}
                )

                value = usage.get("total_tokens")

                if isinstance(value, (int, float)):
                    total_tokens = int(value)

                value = usage.get("input_tokens")

                if isinstance(value, (int, float)):
                    input_tokens = int(value)

                value = usage.get("output_tokens")

                if isinstance(value, (int, float)):
                    output_tokens = int(value)

                value = usage.get(
                    "cached_input_tokens"
                )

                if isinstance(value, (int, float)):
                    cached_input_tokens = int(value)

                value = usage.get(
                    "reasoning_output_tokens"
                )

                if isinstance(value, (int, float)):
                    reasoning_output_tokens = int(value)

            timestamp = (
                event.get("timestamp")
                or payload.get("timestamp")
            )

            if timestamp:
                updated_at = timestamp

    # Filesystem timestamps are useful fallback
    try:
        stat = path.stat()

        if created_at is None:
            created_at = datetime.fromtimestamp(
                stat.st_ctime
            ).isoformat(
                timespec="seconds"
            )

        if updated_at is None:
            updated_at = datetime.fromtimestamp(
                stat.st_mtime
            ).isoformat(
                timespec="seconds"
            )

    except Exception:
        pass

    context_left_percent = None

    if (
        context_window
        and total_tokens is not None
    ):
        remaining = max(
            context_window - total_tokens,
            0
        )

        context_left_percent = round(
            remaining / context_window * 100
        )

    cwd = normalize_path(cwd)

    return {
        "thread": thread_id,

        "cwd": cwd,

        "project_name":
            project_name_from_path(cwd),

        "context": {
            "used": total_tokens,
            "max": context_window,
            "left_percent":
                context_left_percent,

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
            created_at,

        "updated_at":
            updated_at,

        "session_file":
            str(path),
    }


# ============================================================
# Thread titles from session_index.jsonl
# ============================================================

def load_thread_names_from_index():
    result = {}

    index_file = (
        CODEX_HOME / "session_index.jsonl"
    )

    if not index_file.exists():
        return result

    try:
        with index_file.open(
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as f:

            for line in f:
                line = line.strip()

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
                    result[thread_id] = (
                        name.strip()
                    )

    except Exception:
        pass

    return result


# ============================================================
# Thread titles from SQLite
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
                uri=True
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
                    c[1]
                    for c in columns
                ]

                id_columns = [
                    c
                    for c in column_names
                    if c.lower()
                    in possible_id_columns
                ]

                name_columns = [
                    c
                    for c in column_names
                    if c.lower()
                    in possible_name_columns
                ]

                if (
                    not id_columns
                    or not name_columns
                ):
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
                            title = row[1]

                            if (
                                thread_id
                                and isinstance(
                                    title,
                                    str
                                )
                                and title.strip()
                            ):
                                result[
                                    str(thread_id)
                                ] = title.strip()

            conn.close()

        except Exception:
            continue

    return result


# ============================================================
# Combined title map
# ============================================================

def get_thread_title_map():
    titles = {}

    # SQLite first
    titles.update(
        load_thread_names_from_sqlite()
    )

    # session_index takes precedence
    titles.update(
        load_thread_names_from_index()
    )

    return titles


# ============================================================
# Build all projects + chats
# ============================================================

def get_projects_and_chats():
    title_map = get_thread_title_map()

    projects = {}

    for file in get_all_session_files():

        try:
            session = inspect_session(file)
        except Exception:
            continue

        thread_id = session.get("thread")

        if not thread_id:
            continue

        cwd = session.get("cwd")

        project_name = (
            session.get("project_name")
            or "Unknown Project"
        )

        project_key = (
            cwd
            or project_name
        )

        if project_key not in projects:
            projects[project_key] = {
                "name": project_name,
                "path": cwd,
                "chats": [],
            }

        chat_name = title_map.get(
            thread_id
        )

        if not chat_name:
            chat_name = (
                f"Thread {thread_id[:8]}"
            )

        projects[
            project_key
        ]["chats"].append(
            {
                "name":
                    chat_name,

                "thread":
                    thread_id,

                "context":
                    session["context"],

                "updated_at":
                    session["updated_at"],

                "session_file":
                    session["session_file"],
            }
        )

    # Sort chats by session file modification time
    for project in projects.values():

        def sort_key(chat):
            try:
                return Path(
                    chat["session_file"]
                ).stat().st_mtime
            except Exception:
                return 0

        project["chats"].sort(
            key=sort_key,
            reverse=True
        )

    # Sort projects by newest chat
    project_list = list(
        projects.values()
    )

    def project_sort_key(project):

        if not project["chats"]:
            return 0

        try:
            return Path(
                project["chats"][0][
                    "session_file"
                ]
            ).stat().st_mtime

        except Exception:
            return 0

    project_list.sort(
        key=project_sort_key,
        reverse=True
    )

    return project_list


# ============================================================
# Authentication
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

    tokens = auth.get("tokens") or {}

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
            "No OAuth access token found "
            "in auth.json"
        )

    return access_token, account_id


# ============================================================
# Usage API
# ============================================================

def fetch_usage():
    access_token, account_id = (
        read_auth()
    )

    headers = {
        "Authorization":
            f"Bearer {access_token}",

        "User-Agent":
            "codex-cli",

        "Accept":
            "application/json",
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
                "OAuth token rejected (401). "
                "Open Codex/ChatGPT and "
                "login again."
            )

        if e.code == 403:
            raise RuntimeError(
                "Usage API returned 403."
            )

        raise RuntimeError(
            f"Usage API HTTP error: "
            f"{e.code}"
        )

    except urllib.error.URLError as e:

        raise RuntimeError(
            f"Could not reach usage API: "
            f"{e.reason}"
        )


# ============================================================
# Rate limit parsing
# ============================================================

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

    used = window.get(
        "used_percent"
    )

    reset_at = window.get(
        "reset_at"
    )

    seconds = window.get(
        "limit_window_seconds"
    )

    if used is None:
        return None

    used = float(used)

    left = max(
        0,
        min(
            100,
            100 - used
        )
    )

    if float(left).is_integer():
        left = int(left)

    return {
        "used_percent":
            used,

        "left_percent":
            left,

        "reset_at":
            reset_at,

        "reset":
            format_reset(
                reset_at,
                seconds or 0
            ),

        "window_seconds":
            seconds,
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

    windows = [
        w
        for w in [
            primary,
            secondary
        ]
        if w
    ]

    for window in windows:

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
        "plan":
            api_data.get(
                "plan_type"
            ),

        "5h":
            five_hour,

        "7d":
            seven_day,

        "credits": {
            "has_credits":
                credits_data.get(
                    "has_credits"
                ),

            "unlimited":
                credits_data.get(
                    "unlimited"
                ),

            "balance":
                credits_data.get(
                    "balance"
                ),
        },
    }


# ============================================================
# Build status
# ============================================================

def get_status(
    include_projects=False
):
    session_file = (
        find_latest_session()
    )

    session = inspect_session(
        session_file
    )

    title_map = (
        get_thread_title_map()
    )

    thread_id = (
        session["thread"]
    )

    chat_name = (
        title_map.get(
            thread_id
        )
    )

    if not chat_name and thread_id:
        chat_name = (
            f"Thread {thread_id[:8]}"
        )

    try:
        raw_usage = fetch_usage()

        limits = parse_limits(
            raw_usage
        )

        quota_error = None

    except Exception as e:

        limits = {
            "plan": None,
            "5h": None,
            "7d": None,
            "credits": {},
        }

        quota_error = str(e)

    result = {
        "active": {
            "project":
                session[
                    "project_name"
                ],

            "project_path":
                session["cwd"],

            "chat":
                chat_name,

            "thread":
                thread_id,

            "context":
                session["context"],

            "session_file":
                session[
                    "session_file"
                ],
        },

        "limits":
            limits,

        "quota_error":
            quota_error,

        "updated_at":
            datetime.now().isoformat(
                timespec="seconds"
            ),
    }

    if include_projects:

        result["projects"] = (
            get_projects_and_chats()
        )

    return result


# ============================================================
# Progress bar
# ============================================================

def progress_bar(
    percent,
    length=32
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
        length * percent / 100
    )

    return (
        "█" * filled
        +
        "░" * (
            length - filled
        )
    )


# ============================================================
# Human output
# ============================================================

def print_human(data):
    active = data["active"]

    print()

    print("Project:")
    print(
        active.get("project")
        or "Unknown"
    )

    if active.get("project_path"):
        print(
            f"Path: "
            f'{active["project_path"]}'
        )

    print()

    print("Chat:")
    print(
        active.get("chat")
        or "Unknown"
    )

    print(
        f'Thread: '
        f'{active.get("thread")}'
    )

    print()

    context = active["context"]

    print("Context:")

    if (
        context[
            "left_percent"
        ] is not None
        and
        context[
            "used"
        ] is not None
        and
        context[
            "max"
        ] is not None
    ):

        print(
            f'{context["left_percent"]}% left '
            f'({context["used"]:,} used / '
            f'{context["max"] / 1000:.0f}K)'
        )

        print(
            progress_bar(
                context[
                    "left_percent"
                ]
            )
        )

    else:
        print("Unavailable")

    print()

    five = (
        data["limits"]
        .get("5h")
    )

    print("5h limit:")

    if five:

        print(
            progress_bar(
                five[
                    "left_percent"
                ]
            )
        )

        print(
            f'{five["left_percent"]}% left '
            f'(resets {five["reset"]})'
        )

    else:
        print("Unavailable")

    print()

    seven = (
        data["limits"]
        .get("7d")
    )

    print("7d limit:")

    if seven:

        print(
            progress_bar(
                seven[
                    "left_percent"
                ]
            )
        )

        print(
            f'{seven["left_percent"]}% left '
            f'(resets {seven["reset"]})'
        )

    else:
        print("Unavailable")

    plan = (
        data["limits"]
        .get("plan")
    )

    if plan:
        print()
        print(
            f"Plan: {plan}"
        )

    credits = (
        data["limits"]
        .get("credits")
        or {}
    )

    if (
        credits.get(
            "balance"
        )
        is not None
    ):
        print(
            f'Credits: '
            f'{credits["balance"]}'
        )

    if data.get(
        "quota_error"
    ):
        print()

        print(
            "Quota warning:",
            data["quota_error"]
        )

    print()

    print(
        "Updated:",
        data["updated_at"]
    )


# ============================================================
# Print projects
# ============================================================

def print_projects(
    projects
):
    print()

    print(
        "Detected Codex projects:"
    )

    print()

    for project in projects:

        print(
            f'PROJECT: '
            f'{project["name"]}'
        )

        if project.get("path"):

            print(
                f'Path: '
                f'{project["path"]}'
            )

        chats = (
            project.get(
                "chats"
            )
            or []
        )

        for index, chat in enumerate(
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

            suffix = ""

            if left is not None:
                suffix = (
                    f" — "
                    f"{left}% context left"
                )

            print(
                f"  {index}. "
                f'{chat["name"]}'
                f"{suffix}"
            )

            print(
                f"     "
                f'{chat["thread"]}'
            )

        print()


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Codex desktop session, "
            "project, context and "
            "quota monitor."
        )
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Output machine-readable JSON"
        )
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Continuously refresh status"
        )
    )

    parser.add_argument(
        "--projects",
        action="store_true",
        help=(
            "Show all detected projects "
            "and chats"
        )
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help=(
            "Refresh interval in seconds "
            "(default: 60)"
        )
    )

    args = parser.parse_args()

    while True:

        try:

            data = get_status(
                include_projects=(
                    args.projects
                    or args.json
                )
            )

            if (
                args.watch
                and not args.json
            ):
                os.system(
                    "cls"
                    if os.name == "nt"
                    else "clear"
                )

            if args.json:

                print(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False
                    )
                )

            else:

                print_human(
                    data
                )

                if args.projects:

                    print_projects(
                        data.get(
                            "projects",
                            []
                        )
                    )

        except KeyboardInterrupt:
            break

        except Exception as e:

            print(
                f"Error: {e}",
                file=sys.stderr
            )

        if not args.watch:
            break

        try:

            time.sleep(
                max(
                    args.interval,
                    5
                )
            )

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()