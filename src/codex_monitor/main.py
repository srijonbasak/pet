import argparse
import json

from .monitor import (
    run_watch_mode, print_projects, build_snapshot, print_snapshot, STATE_LOCK
)
from .gui import run_gui
from .wifi_transport import run_wifi_client

def main():
    parser = argparse.ArgumentParser(
        description="Local-first Codex usage monitor."
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch Codex local files and update automatically"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print current state as JSON"
    )

    parser.add_argument(
        "--projects",
        action="store_true",
        help="Show detected local projects and chats"
    )

    parser.add_argument(
        "--refresh-quota",
        action="store_true",
        help="Force refresh 5h/7d quota"
    )

    parser.add_argument(
        "--gui",
        action="store_true",
        help="Run the floating GUI widget"
    )

    parser.add_argument(
        "--ble",
        action="store_true",
        help="Run the BLE client in the background"
    )

    parser.add_argument("--wifi", nargs="?", const="255.255.255.255", metavar="ESP32_IP",
                        help="Send updates over Wi-Fi UDP (broadcast if IP is omitted)")

    args = parser.parse_args()

    if args.ble:
        from .bluetooth import run_bluetooth_client
        run_bluetooth_client()

    if args.wifi or args.gui:
        run_wifi_client(args.wifi or "255.255.255.255")
    if args.gui and not args.ble:
        from .bluetooth import run_bluetooth_client
        run_bluetooth_client()

    if args.gui:
        # Start file watching in a background thread without blocking
        import threading
        t = threading.Thread(target=run_watch_mode, kwargs={"run_event_loop": False}, daemon=True)
        t.start()
        # Start GUI on main thread
        return run_gui()

    if args.watch:
        run_watch_mode()
        return

    if args.projects:
        print_projects()
        return

    with STATE_LOCK:
        snapshot = build_snapshot(
            include_projects=True,
            refresh_quota=args.refresh_quota
        )

    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print_snapshot(snapshot)

if __name__ == "__main__":
    main()
