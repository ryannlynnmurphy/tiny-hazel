#!/usr/bin/env python3
"""
Hazel OS panel widget.
Shows system status in the taskbar and monitors for issues.
Sends notifications for problems.
"""

import subprocess
import psutil
import time
import os
import sys
import socket
from pathlib import Path

HAZEL_DIR = Path.home() / ".hazel"
STATUS_FILE = HAZEL_DIR / "panel_status.txt"
CHECK_INTERVAL = 30  # seconds

# Thresholds for notifications
TEMP_WARN = 70
TEMP_CRIT = 80
DISK_WARN = 85  # percent used
RAM_WARN = 85   # percent used
CPU_WARN = 90   # percent sustained


def notify(title, body, urgency="normal"):
    """Send desktop notification."""
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, "-a", "Hazel OS", title, body],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def get_temp():
    try:
        r = subprocess.run(["vcgencmd", "measure_temp"],
                          capture_output=True, text=True, timeout=2)
        return float(r.stdout.strip().split("=")[1].split("'")[0])
    except Exception:
        return None


def check_health():
    """Check system health and send notifications for issues."""
    issues = []

    # Temperature
    temp = get_temp()
    if temp and temp >= TEMP_CRIT:
        notify("CPU Overheating!", f"Temperature is {temp}C. Check cooling.", "critical")
        issues.append(f"TEMP:{temp}C")
    elif temp and temp >= TEMP_WARN:
        notify("CPU Running Hot", f"Temperature is {temp}C.", "normal")
        issues.append(f"temp:{temp}C")

    # Disk
    disk = psutil.disk_usage("/")
    if disk.percent >= DISK_WARN:
        free_gb = round(disk.free / 1e9, 1)
        notify("Disk Almost Full", f"Only {free_gb}GB free ({disk.percent}% used).", "normal")
        issues.append(f"disk:{disk.percent}%")

    # RAM
    mem = psutil.virtual_memory()
    if mem.percent >= RAM_WARN:
        free_gb = round(mem.available / 1e9, 1)
        notify("Low Memory", f"Only {free_gb}GB RAM free ({mem.percent}% used).", "normal")
        issues.append(f"ram:{mem.percent}%")

    # Failed services
    try:
        r = subprocess.run(
            ["systemctl", "--failed", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=5,
        )
        if r.stdout.strip():
            count = len(r.stdout.strip().split("\n"))
            notify("Failed Services", f"{count} service(s) failed. Run 'hazel' and type 'errors'.", "normal")
            issues.append(f"svc:{count}")
    except Exception:
        pass

    return issues


def write_status():
    """Write current status to file for panel display."""
    temp = get_temp()
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()

    temp_str = f"{temp:.0f}C" if temp else "?"
    status = f"CPU:{cpu:.0f}% {temp_str} RAM:{mem.percent:.0f}%"

    HAZEL_DIR.mkdir(exist_ok=True)
    STATUS_FILE.write_text(status)


def daemon():
    """Run as background daemon, check health periodically."""
    print(f"Hazel panel daemon started (checking every {CHECK_INTERVAL}s)")

    # Initial check
    check_health()
    write_status()

    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            check_health()
            write_status()
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    if "--once" in sys.argv:
        # Run once and exit (for testing)
        issues = check_health()
        write_status()
        print(f"Status: {STATUS_FILE.read_text()}")
        print(f"Issues: {issues if issues else 'none'}")
    else:
        daemon()
