import json
import urllib.request
import urllib.error
from datetime import datetime
from .config import AUTH_FILE, USAGE_URL
from .utils import now_iso

def read_auth():
    if not AUTH_FILE.exists():
        raise RuntimeError(
            f"Codex auth file not found: {AUTH_FILE}"
        )

    with AUTH_FILE.open("r", encoding="utf-8") as f:
        auth = json.load(f)

    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token") or auth.get("access_token")
    account_id = tokens.get("account_id") or auth.get("account_id")

    if not access_token:
        raise RuntimeError("No OAuth access token found in auth.json")

    return access_token, account_id

def fetch_usage():
    access_token, account_id = read_auth()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "codex-cli",
    }

    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    request = urllib.request.Request(
        USAGE_URL,
        headers=headers,
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("Codex token rejected (401)")
        if e.code == 403:
            raise RuntimeError("Codex usage API returned 403")
        raise RuntimeError(f"Codex usage HTTP error: {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")

def format_reset(timestamp, window_seconds):
    if not timestamp:
        return None

    dt = datetime.fromtimestamp(timestamp)

    if window_seconds <= 6 * 60 * 60:
        return dt.strftime("%I:%M%p").lstrip("0")

    return dt.strftime("%d %b,%I:%M%p").lstrip("0").replace(",0", ",")

def parse_window(window):
    if not window:
        return None

    used_percent = window.get("used_percent")
    if used_percent is None:
        return None

    used_percent = float(used_percent)
    left_percent = max(0, min(100, 100 - used_percent))

    if float(left_percent).is_integer():
        left_percent = int(left_percent)

    reset_at = window.get("reset_at") or window.get("resets_at")
    window_seconds = window.get("limit_window_seconds") or window.get("window_seconds")
    if not window_seconds and window.get("window_minutes"):
        window_seconds = window["window_minutes"] * 60

    return {
        "used_percent": used_percent,
        "left_percent": left_percent,
        "reset_at": reset_at,
        "reset": format_reset(reset_at, window_seconds or 0),
        "window_seconds": window_seconds,
    }

def parse_limits(api_data):
    rate_limit = api_data.get("rate_limit") or api_data.get("rate_limits") or api_data or {}
    primary = parse_window(rate_limit.get("primary_window") or rate_limit.get("primary"))
    secondary = parse_window(rate_limit.get("secondary_window") or rate_limit.get("secondary"))

    five_hour = None
    seven_day = None

    for window in [primary, secondary]:
        if not window:
            continue

        seconds = window.get("window_seconds") or 0

        if 4 * 3600 <= seconds <= 6 * 3600:
            five_hour = window
        elif 6 * 86400 <= seconds <= 8 * 86400:
            seven_day = window

    if not five_hour:
        five_hour = primary
    if not seven_day:
        seven_day = secondary

    credits_data = api_data.get("credits") or {}

    return {
        "5h": five_hour,
        "7d": seven_day,
        "plan": rate_limit.get("plan_type") or api_data.get("plan_type"),
        "credits": {
            "balance": credits_data.get("balance"),
            "has_credits": credits_data.get("has_credits"),
            "unlimited": credits_data.get("unlimited"),
        },
        "fetched_at": now_iso(),
    }
