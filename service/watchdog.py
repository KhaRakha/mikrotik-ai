"""
Auto-Recovery Watchdog Supervisor (PRD Section 19).
Monitors the bot process and automatically restarts it if it crashes or terminates.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ENTRYPOINT = PROJECT_ROOT / "service" / "run_bot.py"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
WATCHDOG_LOG = LOG_DIR / "watchdog.log"

# Safely route stdout/stderr to watchdog.log so headless wscript/pythonw execution never crashes
try:
    log_fp = open(WATCHDOG_LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_fp
    sys.stderr = log_fp
except Exception:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")



def get_python_executable() -> str:
    """Find the best Python executable."""
    # 1. Project local virtual environments (.venv or venv)
    for venv_name in (".venv", "venv"):
        unix_py = PROJECT_ROOT / venv_name / "bin" / "python"
        if unix_py.exists():
            return str(unix_py)
        win_py = PROJECT_ROOT / venv_name / "Scripts" / "python.exe"
        if win_py.exists():
            return str(win_py)

    # 2. Current sys.executable
    if sys.executable and "python" in sys.executable.lower():
        return sys.executable

    # 3. Direct Python 3.14 installed path (Windows)
    py314 = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Programs" / "Python" / "Python314" / "python.exe"
    if py314.exists():
        return str(py314)

    # 4. Check Hermes venv
    hermes_win = Path(os.path.expanduser("~")) / "AppData" / "Local" / "hermes" / "hermes-agent" / "venv" / "Scripts" / "python.exe"
    if hermes_win.exists():
        return str(hermes_win)

    # 5. Default python
    return "python"


def run_supervisor():
    python_exe = get_python_executable()
    max_restarts = 50
    restart_count = 0
    backoff_delay = 5.0

    print("================================================================")
    print(" MikroTik AI Agent - Auto-Recovery Watchdog Supervisor")
    print(f" Target script: {BOT_ENTRYPOINT}")
    print(f" Python binary: {python_exe}")
    print("================================================================")

    while restart_count < max_restarts:
        print(f"\n[Watchdog] [{time.strftime('%Y-%m-%d %H:%M:%S')}] Memulai bot (run #{restart_count + 1})...")
        start_time = time.time()

        try:
            process = subprocess.Popen(
                [python_exe, str(BOT_ENTRYPOINT)],
                cwd=str(PROJECT_ROOT),
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            ret_code = process.wait()
            uptime = time.time() - start_time
            print(f"[Watchdog] Proses bot berhenti dengan kode exit: {ret_code} (Uptime: {uptime:.1f}s)")

            # If process ran for more than 2 minutes, reset restart count
            if uptime > 120:
                restart_count = 0

            restart_count += 1
            print(f"[Watchdog] Auto-recovery: Mempersiapkan restart dalam {backoff_delay} detik...")
            time.sleep(backoff_delay)

        except KeyboardInterrupt:
            print("\n[Watchdog] Menerima sinyal keyboard interrupt. Menghentikan supervisor.")
            break
        except Exception as e:
            print(f"[Watchdog] Error tidak terduga pada supervisor: {e}")
            time.sleep(10.0)


if __name__ == "__main__":
    run_supervisor()
