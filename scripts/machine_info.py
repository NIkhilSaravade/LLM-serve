"""Print machine details as JSON. Published next to every benchmark (docs/04-methodology)."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys

import torch


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def cpu_name() -> str:
    if sys.platform == "win32":
        return _run(["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Processor).Name"]) or platform.processor()
    return _run(["sh", "-c", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2"]) or platform.processor()


def ram_gib() -> float | None:
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        return round(int(out) / 2**30, 1) if out.isdigit() else None
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError):
        return None


if __name__ == "__main__":
    print(json.dumps({
        "cpu": cpu_name(), "logical_cores": os.cpu_count(), "ram_gib": ram_gib(),
        "torch": torch.__version__, "torch_threads_used_by_server": int(os.environ.get("LLM_SERVE_THREADS", "4")),
        "python": platform.python_version(), "os": platform.platform(),
        "go": _run(["go", "version"]),
    }, indent=2))
