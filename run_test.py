import traceback
import sys
try:
    from src.codex_monitor.gui import run_gui
    sys.exit(run_gui())
except Exception:
    traceback.print_exc()
