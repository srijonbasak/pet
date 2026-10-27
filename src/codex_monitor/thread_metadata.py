import sqlite3
from .config import SESSION_INDEX_FILE, CODEX_HOME
from .utils import safe_json_load

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

                if thread_id and isinstance(name, str) and name.strip():
                    result[str(thread_id)] = name.strip()

    except Exception:
        pass

    return result

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
        "id", "thread_id", "session_id", "conversation_id",
    }

    possible_name_columns = {
        "thread_name", "title", "name", "display_name",
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

                column_names = [row[1] for row in columns]

                id_columns = [
                    col for col in column_names
                    if col.lower() in possible_id_columns
                ]

                name_columns = [
                    col for col in column_names
                    if col.lower() in possible_name_columns
                ]

                if not id_columns or not name_columns:
                    continue

                for id_col in id_columns:
                    for name_col in name_columns:
                        query = f'SELECT "{id_col}", "{name_col}" FROM "{table}"'
                        try:
                            rows = cursor.execute(query).fetchall()
                        except Exception:
                            continue

                        for row in rows:
                            if len(row) < 2:
                                continue

                            thread_id = row[0]
                            name = row[1]

                            if thread_id and isinstance(name, str) and name.strip():
                                result[str(thread_id)] = name.strip()

            conn.close()

        except Exception:
            continue

    return result

def get_thread_title_map():
    titles = {}

    # SQLite fallback first
    titles.update(load_thread_names_from_sqlite())

    # Index gets precedence
    titles.update(load_thread_names_from_index())

    return titles
