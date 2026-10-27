import time
from .config import CACHE_FILE, QUOTA_REFRESH_SECONDS
from .utils import read_json_file, write_json_file
from .quota import fetch_usage, parse_limits

def load_cache():
    cache = read_json_file(CACHE_FILE)
    if not isinstance(cache, dict):
        cache = {}
    return cache

def save_cache(cache):
    write_json_file(CACHE_FILE, cache)


def update_quota_from_session(cache, raw_rate_limits):
    """Use rate limits embedded in the latest Codex token event."""
    if not isinstance(raw_rate_limits, dict):
        return cache

    limits = parse_limits(raw_rate_limits)
    if not limits.get("5h") and not limits.get("7d"):
        return cache

    previous = cache.get("limits") or {}
    if not limits.get("plan"):
        limits["plan"] = previous.get("plan")
    if not (limits.get("credits") or {}).get("balance"):
        limits["credits"] = previous.get("credits") or limits.get("credits")

    cache["limits"] = limits
    cache["limits_fetched_epoch"] = time.time()
    cache["limits_source"] = "codex_session"
    cache["quota_error"] = None
    save_cache(cache)
    return cache

def quota_cache_is_fresh(cache):
    quota = cache.get("limits")
    if not quota:
        return False

    timestamp = cache.get("limits_fetched_epoch")
    if not timestamp:
        return False

    age = time.time() - timestamp
    return age < QUOTA_REFRESH_SECONDS

def refresh_quota_if_needed(cache, force=False):
    if not force and quota_cache_is_fresh(cache):
        return cache

    try:
        raw = fetch_usage()
        limits = parse_limits(raw)

        cache["limits"] = limits
        cache["limits_fetched_epoch"] = time.time()
        cache["quota_error"] = None
        save_cache(cache)
    except Exception as e:
        cache["quota_error"] = str(e)

    return cache
