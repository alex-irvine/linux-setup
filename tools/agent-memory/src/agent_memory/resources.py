"""Whether this machine has room to run memory work on its own Ollama.

The local Ollama shares the CPU and memory with whatever the user is doing,
so the worker sends it a capture only while there is spare capacity.
"""
from __future__ import annotations

import time
from pathlib import Path


def _cpu_times() -> tuple[int, int]:
    """Return (idle, total) jiffies across all CPUs from /proc/stat."""
    fields = [int(value) for value in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:9]]
    return fields[3] + fields[4], sum(fields)


def cpu_idle_percent(sample: float = 0.5) -> float:
    idle_before, total_before = _cpu_times()
    time.sleep(sample)
    idle_after, total_after = _cpu_times()
    return 100.0 * (idle_after - idle_before) / max(total_after - total_before, 1)


def memory_available_percent() -> float:
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, _, rest = line.partition(":")
        if name in ("MemTotal", "MemAvailable"):
            info[name] = int(rest.split()[0])
    return 100.0 * info["MemAvailable"] / info["MemTotal"]


def on_battery() -> bool:
    """True when a system battery is discharging (a mouse or keyboard battery does not count)."""
    return any((battery / "status").read_text().strip() == "Discharging"
               for battery in Path("/sys/class/power_supply").glob("BAT*") if (battery / "status").exists())


def shortage(min_cpu_idle: float, min_memory: float, allow_battery: bool) -> str | None:
    """Return why the machine cannot spare the local Ollama now, or None when it can."""
    if not allow_battery and on_battery():
        return "the laptop is on battery"
    memory = memory_available_percent()
    if memory < min_memory:
        return f"{memory:.0f}% of memory is free, below {min_memory:.0f}%"
    idle = cpu_idle_percent()
    if idle < min_cpu_idle:
        return f"the CPU is {idle:.0f}% idle, below {min_cpu_idle:.0f}%"
    return None
