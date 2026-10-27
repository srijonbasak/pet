import json
from datetime import datetime
from pathlib import Path

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
