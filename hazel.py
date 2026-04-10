#!/usr/bin/env python3
"""
Hazel OS - Your local computer AI assistant.
Runs on Raspberry Pi. No cloud. No telemetry. Yours.
"""

import subprocess
import json
import os
import sys
import re
import psutil
import socket
import time
import readline
import shutil
import glob as globmod
from pathlib import Path
from datetime import datetime

# === CONFIG ===
HAZEL_DIR = Path.home() / ".hazel"
CONFIG_FILE = Path(__file__).parent / "config.yaml"
LLAMA_BIN = Path.home() / "llama.cpp" / "build" / "bin" / "llama-completion"
HISTORY_FILE = HAZEL_DIR / "history"
PROMPT_FILE = HAZEL_DIR / "prompt.txt"

# Defaults (overridden by config.yaml)
MAX_TOKENS = 120
MAX_TOKENS_DEEP = 300
TIMEOUT = 30
TIMEOUT_DEEP = 60
THREADS = 4
TEMPERATURE = 0.7
HUMANIZE = True
SHOW_RAW = True
MEMORY_SIZE = 6

# Model paths
MODEL_TINYLLAMA = Path.home() / "models" / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
MODEL_PHI3 = Path.home() / "models" / "Phi-3-mini-4k-instruct-q4.gguf"
MODEL_DEFAULT = MODEL_TINYLLAMA
MODEL_DEEP = MODEL_TINYLLAMA  # Changes to PHI3 if available and configured


def load_config():
    """Load config.yaml and apply settings."""
    global MAX_TOKENS, MAX_TOKENS_DEEP, TIMEOUT, TIMEOUT_DEEP
    global THREADS, TEMPERATURE, HUMANIZE, SHOW_RAW, MEMORY_SIZE
    global MODEL_DEFAULT, MODEL_DEEP

    if not CONFIG_FILE.exists():
        return

    # Simple YAML parser (no pyyaml dependency needed)
    config = {}
    current_section = None
    try:
        for line in CONFIG_FILE.read_text().split("\n"):
            line = line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            # Section header
            if not line.startswith(" ") and line.endswith(":"):
                current_section = line[:-1].strip()
                config[current_section] = {}
                continue
            # Key-value
            if ":" in line and current_section:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # Strip inline comments
                if "#" in val:
                    val = val[:val.index("#")].strip()
                # Type conversion
                if val.lower() == "true":
                    val = True
                elif val.lower() == "false":
                    val = False
                elif val.isdigit():
                    val = int(val)
                else:
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                config[current_section][key] = val
    except Exception:
        return

    # Apply config
    perf = config.get("performance", {})
    MAX_TOKENS = perf.get("tokens_normal", MAX_TOKENS)
    MAX_TOKENS_DEEP = perf.get("tokens_deep", MAX_TOKENS_DEEP)
    TIMEOUT = perf.get("timeout_normal", TIMEOUT)
    TIMEOUT_DEEP = perf.get("timeout_deep", TIMEOUT_DEEP)
    THREADS = perf.get("threads", THREADS)
    TEMPERATURE = perf.get("temperature", TEMPERATURE)

    beh = config.get("behavior", {})
    HUMANIZE = beh.get("humanize_responses", HUMANIZE)
    SHOW_RAW = beh.get("show_raw_data", SHOW_RAW)
    try:
        MEMORY_SIZE = int(beh.get("conversation_memory", MEMORY_SIZE))
    except (ValueError, TypeError):
        pass

    mdl = config.get("model", {})
    # Resolve model paths
    if "path_tinyllama" in mdl:
        p = Path(mdl["path_tinyllama"]).expanduser()
        if p.exists():
            global MODEL_TINYLLAMA
            MODEL_TINYLLAMA = p
    if "path_phi3" in mdl:
        p = Path(mdl["path_phi3"]).expanduser()
        if p.exists():
            global MODEL_PHI3
            MODEL_PHI3 = p

    default_model = mdl.get("default", "tinyllama")
    deep_model = mdl.get("deep", "tinyllama")

    MODEL_DEFAULT = MODEL_PHI3 if default_model == "phi3" and MODEL_PHI3.exists() else MODEL_TINYLLAMA
    MODEL_DEEP = MODEL_PHI3 if deep_model == "phi3" and MODEL_PHI3.exists() else MODEL_TINYLLAMA


load_config()

DEEP_KEYWORDS = [
    "explain", "why", "how does", "how do", "what is", "what are",
    "teach", "learn", "understand", "describe", "compare",
    "difference between", "help me understand", "tell me about",
    "write", "create", "build", "design", "plan",
    "debug", "fix", "solve", "troubleshoot", "diagnose",
    "analyze", "review", "evaluate",
]

# Known desktop apps (command: display name)
APPS = {
    "chromium-browser": "Browser",
    "firefox": "Firefox",
    "pcmanfm": "File Manager",
    "lxterminal": "Terminal",
    "x-terminal-emulator": "Terminal",
    "mousepad": "Text Editor",
    "geany": "Geany Editor",
    "libreoffice": "LibreOffice",
    "libreoffice --writer": "Writer",
    "libreoffice --calc": "Spreadsheet",
    "gimp": "GIMP",
    "vlc": "VLC Player",
    "code": "VS Code",
    "thunar": "File Manager",
}

# === COLORS ===
G = "\033[92m"
B = "\033[94m"
Y = "\033[93m"
R = "\033[91m"
D = "\033[2m"
BD = "\033[1m"
X = "\033[0m"

# === CONVERSATION MEMORY ===
conversation_history = []

def remember(role, content):
    """Store conversation turn for context."""
    if MEMORY_SIZE == 0:
        return
    conversation_history.append({"role": role, "content": content})
    while len(conversation_history) > MEMORY_SIZE:
        conversation_history.pop(0)

def get_memory_context():
    """Format recent conversation for LLM."""
    if not conversation_history:
        return ""
    lines = []
    for turn in conversation_history[-4:]:  # last 2 exchanges
        if turn["role"] == "user":
            lines.append(f"User said: {turn['content']}")
        else:
            lines.append(f"You said: {turn['content'][:80]}")
    return "Recent conversation: " + ". ".join(lines)


# =============================================
# PART 1: SYSTEM READING
# =============================================

def sys_cpu():
    pct = psutil.cpu_percent(interval=0.3)
    freq = psutil.cpu_freq()
    mhz = round(freq.current) if freq else "?"
    return {"cpu_percent": pct, "cpu_cores": psutil.cpu_count(), "cpu_mhz": mhz}

def sys_temp():
    try:
        r = subprocess.run(["vcgencmd", "measure_temp"],
                          capture_output=True, text=True, timeout=2)
        return float(r.stdout.strip().split("=")[1].split("'")[0])
    except Exception:
        return None

def sys_mem():
    m = psutil.virtual_memory()
    return {
        "ram_total_gb": round(m.total / 1e9, 1),
        "ram_free_gb": round(m.available / 1e9, 1),
        "ram_percent": m.percent,
    }

def sys_disk():
    d = psutil.disk_usage("/")
    return {
        "disk_total_gb": round(d.total / 1e9, 1),
        "disk_free_gb": round(d.free / 1e9, 1),
        "disk_percent": round(d.percent, 1),
    }

def sys_net():
    info = {}
    for iface, addrs in psutil.net_if_addrs().items():
        if iface == "lo":
            continue
        for a in addrs:
            if a.family == socket.AF_INET:
                info[iface] = a.address
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        info["internet"] = True
    except OSError:
        info["internet"] = False
    return info

def sys_procs(n=5):
    procs = sorted(
        psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
        key=lambda p: p.info.get("cpu_percent") or 0,
        reverse=True,
    )[:n]
    return [
        {"name": p.info["name"], "pid": p.info["pid"],
         "cpu": p.info.get("cpu_percent", 0),
         "mem": round(p.info.get("memory_percent", 0), 1)}
        for p in procs
    ]

def sys_uptime():
    s = time.time() - psutil.boot_time()
    h, m = int(s // 3600), int((s % 3600) // 60)
    return f"{h}h {m}m"

def sys_dirs():
    home = Path.home()
    return sorted([
        d.name for d in home.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])

def sys_overview():
    t = sys_temp()
    c = sys_cpu()
    m = sys_mem()
    d = sys_disk()
    temp_str = f"{t}C" if t else "?"
    return (
        f"CPU {c['cpu_percent']}% | {temp_str} | "
        f"RAM {m['ram_free_gb']}GB free | "
        f"Disk {d['disk_free_gb']}GB free"
    )

# --- Deep system info (Pi-specific) ---

def sys_pi_info():
    """Raspberry Pi hardware info."""
    info = {}
    try:
        r = subprocess.run(["cat", "/proc/device-tree/model"],
                          capture_output=True, text=True, timeout=2)
        info["model"] = r.stdout.strip().rstrip("\x00")
    except Exception:
        pass
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"],
                          capture_output=True, text=True, timeout=2)
        val = r.stdout.strip().split("=")[1]
        if val == "0x0":
            info["throttled"] = "no (healthy)"
        else:
            info["throttled"] = f"yes ({val}) - check power supply"
    except Exception:
        pass
    try:
        r = subprocess.run(["vcgencmd", "measure_volts"],
                          capture_output=True, text=True, timeout=2)
        info["voltage"] = r.stdout.strip().split("=")[1]
    except Exception:
        pass
    try:
        r = subprocess.run(["vcgencmd", "measure_clock", "arm"],
                          capture_output=True, text=True, timeout=2)
        freq = int(r.stdout.strip().split("=")[1]) // 1000000
        info["arm_clock_mhz"] = freq
    except Exception:
        pass
    return info

def sys_usb():
    """Connected USB devices."""
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        devices = []
        for line in r.stdout.strip().split("\n"):
            if line:
                # Parse "Bus 001 Device 002: ID xxxx:xxxx Name"
                parts = line.split("ID ")
                if len(parts) > 1:
                    devices.append(parts[1].strip())
        return devices
    except Exception:
        return []

def sys_services():
    """Failed systemd services."""
    try:
        r = subprocess.run(
            ["systemctl", "--failed", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=5,
        )
        if r.stdout.strip():
            return r.stdout.strip().split("\n")
        return []
    except Exception:
        return []

def sys_users():
    """Logged in users."""
    return [u.name for u in psutil.users()]

def sys_mounts():
    """Mounted external drives."""
    mounts = []
    for p in psutil.disk_partitions():
        if p.mountpoint in ("/", "/boot", "/boot/firmware"):
            continue
        if "loop" in p.device:
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
            mounts.append({
                "device": p.device,
                "mount": p.mountpoint,
                "total_gb": round(usage.total / 1e9, 1),
                "free_gb": round(usage.free / 1e9, 1),
            })
        except Exception:
            mounts.append({"device": p.device, "mount": p.mountpoint})
    return mounts

def sys_bluetooth():
    """Bluetooth devices."""
    try:
        r = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True, text=True, timeout=5,
        )
        devices = []
        for line in r.stdout.strip().split("\n"):
            if line.startswith("Device"):
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    devices.append(parts[2])
        return devices
    except Exception:
        return []

def sys_display():
    """Display info."""
    try:
        r = subprocess.run(
            ["wlr-randr"],
            capture_output=True, text=True, timeout=5,
        )
        displays = []
        for line in r.stdout.strip().split("\n"):
            if "current" in line.lower():
                displays.append(line.strip())
        return displays if displays else [r.stdout.strip().split("\n")[0]]
    except Exception:
        return []

def sys_kernel():
    """Kernel and OS info."""
    import platform
    return {
        "kernel": platform.release(),
        "os": platform.platform(),
        "arch": platform.machine(),
    }


# =============================================
# PART 2: FILE OPERATIONS
# =============================================

def find_file(name):
    """Search for a file by name under home."""
    home = str(Path.home())
    matches = []
    for root, dirs, files in os.walk(home):
        # Skip hidden dirs and large dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "llama.cpp")]
        for f in files:
            if name.lower() in f.lower():
                full = os.path.join(root, f)
                rel = os.path.relpath(full, home)
                size = os.path.getsize(full)
                matches.append((rel, size))
                if len(matches) >= 15:
                    return matches
    return matches


def search_file_contents(term):
    """Search file contents using grep."""
    home = str(Path.home())
    try:
        result = subprocess.run(
            ["grep", "-rl", "--include=*.txt", "--include=*.md",
             "--include=*.py", "--include=*.json", "--include=*.csv",
             "--include=*.sh", "--include=*.html", "--include=*.css",
             "-i", term, home],
            capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().split("\n")[:10]
        return [os.path.relpath(f, home) for f in files if f]
    except Exception:
        return []


def format_size(size_bytes):
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f}MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.1f}GB"


def open_file(filepath):
    """Open a file with the default application."""
    full_path = Path(filepath).expanduser().resolve()
    if not full_path.exists():
        # Try finding it
        home = Path.home()
        candidate = home / filepath
        if candidate.exists():
            full_path = candidate
        else:
            return f"File not found: {filepath}"
    try:
        subprocess.Popen(["xdg-open", str(full_path)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opened {full_path.name}"
    except Exception as e:
        return f"Couldn't open: {e}"


# =============================================
# PART 3: APP LAUNCHING
# =============================================

def find_app(name):
    """Find an app by fuzzy name matching."""
    name_lower = name.lower().strip()

    # Direct aliases
    aliases = {
        "browser": "chromium-browser",
        "web": "chromium-browser",
        "chrome": "chromium-browser",
        "chromium": "chromium-browser",
        "files": "pcmanfm",
        "file manager": "pcmanfm",
        "filemanager": "pcmanfm",
        "terminal": "x-terminal-emulator",
        "term": "x-terminal-emulator",
        "editor": "mousepad",
        "text editor": "mousepad",
        "notepad": "mousepad",
        "writer": "libreoffice --writer",
        "word": "libreoffice --writer",
        "spreadsheet": "libreoffice --calc",
        "excel": "libreoffice --calc",
        "calc": "libreoffice --calc",
        "presentation": "libreoffice --impress",
        "powerpoint": "libreoffice --impress",
        "slides": "libreoffice --impress",
        "image editor": "gimp",
        "photo editor": "gimp",
        "gimp": "gimp",
        "media": "vlc",
        "video": "vlc",
        "music": "vlc",
        "player": "vlc",
        "vlc": "vlc",
        "code": "code",
        "vscode": "code",
        "vs code": "code",
    }

    if name_lower in aliases:
        cmd = aliases[name_lower]
        if shutil.which(cmd.split()[0]):
            return cmd, APPS.get(cmd, cmd)

    # Try direct command
    if shutil.which(name_lower):
        return name_lower, name_lower

    # Search installed .desktop files
    for desktop_dir in ["/usr/share/applications", str(Path.home() / ".local/share/applications")]:
        if not os.path.isdir(desktop_dir):
            continue
        for f in os.listdir(desktop_dir):
            if f.endswith(".desktop"):
                try:
                    with open(os.path.join(desktop_dir, f)) as fh:
                        content = fh.read()
                        # Check Name= line
                        for line in content.split("\n"):
                            if line.startswith("Name=") and name_lower in line.lower():
                                # Found it - get Exec line
                                for eline in content.split("\n"):
                                    if eline.startswith("Exec="):
                                        cmd = eline[5:].split("%")[0].strip()
                                        return cmd, line[5:].strip()
                except Exception:
                    continue

    return None, None


def launch_app(name):
    """Launch an application."""
    cmd, display_name = find_app(name)
    if cmd:
        try:
            subprocess.Popen(
                cmd.split(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Launched {display_name}."
        except Exception as e:
            return f"Couldn't launch {display_name}: {e}"
    return None


# =============================================
# PART 4: SYSTEM CONTROL
# =============================================

def set_volume(level):
    """Set system volume (0-100)."""
    try:
        subprocess.run(
            ["amixer", "set", "Master", f"{level}%"],
            capture_output=True, timeout=5,
        )
        return f"Volume set to {level}%."
    except Exception:
        return "Couldn't set volume."


def set_brightness(level):
    """Set screen brightness (0-100)."""
    # Try backlight
    bl_path = Path("/sys/class/backlight")
    if bl_path.exists():
        for bl in bl_path.iterdir():
            max_br = int((bl / "max_brightness").read_text().strip())
            target = int(max_br * level / 100)
            try:
                (bl / "brightness").write_text(str(target))
                return f"Brightness set to {level}%."
            except PermissionError:
                subprocess.run(
                    ["sudo", "sh", "-c", f"echo {target} > {bl}/brightness"],
                    timeout=5,
                )
                return f"Brightness set to {level}%."
    return "No backlight control found."


# =============================================
# PART 5: TUTORIALS (interactive learning)
# =============================================

TUTORIALS = {
    "permissions": {
        "title": "File Permissions (chmod)",
        "steps": [
            ("Let's learn about file permissions. First, let's create a test file:",
             "touch ~/test_permissions.txt"),
            ("Now let's see its current permissions:",
             "ls -l ~/test_permissions.txt"),
            ("The letters like '-rw-r--r--' mean:\n"
             "  r = read, w = write, x = execute\n"
             "  Owner | Group | Others\n\n"
             "Let's make it executable:",
             "chmod +x ~/test_permissions.txt"),
            ("See the difference? Now it has 'x' permission:",
             "ls -l ~/test_permissions.txt"),
            ("Let's clean up:",
             "rm ~/test_permissions.txt"),
        ]
    },
    "files": {
        "title": "Finding Files",
        "steps": [
            ("Let's learn to find files. First, what's in your home directory?",
             "ls ~"),
            ("Now let's search for all Python files:",
             "find ~ -name '*.py' -not -path '*/llama.cpp/*' 2>/dev/null | head -10"),
            ("You can also search inside files. Let's find files containing 'hazel':",
             "grep -rl 'hazel' ~/hazel-os/ 2>/dev/null"),
            ("The 'find' command searches by name.\n"
             "'grep' searches inside files.\n"
             "In Hazel, just type 'find <name>' or 'search for <term>'.",
             None),
        ]
    },
    "processes": {
        "title": "Managing Processes",
        "steps": [
            ("A 'process' is a running program. Let's see what's running:",
             "ps aux | head -15"),
            ("That's a lot of info. Let's see the top CPU users:",
             "ps aux --sort=-%cpu | head -8"),
            ("To stop a process, you use 'kill' with its PID number.\n"
             "In Hazel, just type 'kill <name>' and I'll handle it.",
             None),
        ]
    },
    "networking": {
        "title": "Networking Basics",
        "steps": [
            ("Let's check your network. What's your IP address?",
             "hostname -I"),
            ("Can you reach the internet?",
             "ping -c 2 1.1.1.1"),
            ("What DNS servers are you using?",
             "cat /etc/resolv.conf"),
            ("Your Pi is at the IP shown above.\n"
             "In Hazel, just type 'network' or 'what's my IP' anytime.",
             None),
        ]
    },
    "gpio": {
        "title": "GPIO Pins (Hardware)",
        "steps": [
            ("Your Raspberry Pi has GPIO pins for connecting hardware.\n"
             "Let's see the pin layout:",
             "pinout 2>/dev/null || echo 'Install with: sudo apt install python3-gpiozero'"),
            ("GPIO lets you:\n"
             "  - Control LEDs\n"
             "  - Read sensors\n"
             "  - Drive motors\n"
             "  - Connect buttons\n\n"
             "This is what makes the Pi special - it's a computer AND a hardware platform.",
             None),
        ]
    },
    "pi": {
        "title": "Your Raspberry Pi",
        "steps": [
            ("Let's explore your Pi! What model is it?",
             "cat /proc/device-tree/model"),
            ("How much RAM?",
             "free -h"),
            ("What's the CPU?",
             "lscpu | head -15"),
            ("How's the temperature?",
             "vcgencmd measure_temp"),
            ("Is it throttling? (undervoltage, overheating)",
             "vcgencmd get_throttled"),
            ("0x0 means healthy. Your Pi is doing great!\n"
             "In Hazel, type 'hardware' anytime to see all this.",
             None),
        ]
    },
}


def run_tutorial(name):
    """Run an interactive tutorial."""
    if name not in TUTORIALS:
        available = ", ".join(TUTORIALS.keys())
        print(f"\n{B}  Available tutorials: {available}{X}")
        print(f"  {D}Type: tutorial <name>{X}\n")
        return

    tut = TUTORIALS[name]
    print(f"\n{BD}{G}  Tutorial: {tut['title']}{X}\n")

    for i, (explanation, command) in enumerate(tut["steps"], 1):
        print(f"  {B}{explanation}{X}")

        if command:
            print(f"\n  {D}$ {command}{X}")
            try:
                proceed = input(f"  {G}Run this? (enter=yes, s=skip, q=quit): {X}").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print(f"\n  {D}Tutorial ended.{X}\n")
                return

            if proceed == "q":
                print(f"  {D}Tutorial ended.{X}\n")
                return
            elif proceed != "s":
                try:
                    result = subprocess.run(
                        command, shell=True,
                        capture_output=True, text=True, timeout=15,
                    )
                    if result.stdout:
                        for line in result.stdout.strip().split("\n")[:20]:
                            print(f"  {line}")
                    if result.stderr and result.returncode != 0:
                        print(f"  {R}{result.stderr.strip()}{X}")
                except subprocess.TimeoutExpired:
                    print(f"  {R}Timed out.{X}")
        print()

    print(f"  {G}Tutorial complete!{X}\n")


# =============================================
# PART 6: INSTANT COMMANDS
# =============================================

def handle_instant(query):
    """
    Pattern-match common queries and answer instantly.
    Returns (response_string, flag) or None.
    flag: False=humanize, True=has commands, "skip"=print as-is
    """
    q = query.lower().strip()

    # --- System status ---
    if q in ("status", "stats", "system", "overview"):
        c = sys_cpu()
        m = sys_mem()
        d = sys_disk()
        t = sys_temp()
        n = sys_net()
        u = sys_uptime()
        net_str = ", ".join(f"{k}={v}" for k, v in n.items())
        return (
            f"  CPU:     {c['cpu_percent']}% ({c['cpu_cores']} cores, {c['cpu_mhz']} MHz)\n"
            f"  Temp:    {t}C\n"
            f"  RAM:     {m['ram_free_gb']}GB free / {m['ram_total_gb']}GB ({m['ram_percent']}% used)\n"
            f"  Disk:    {d['disk_free_gb']}GB free / {d['disk_total_gb']}GB ({d['disk_percent']}% used)\n"
            f"  Network: {net_str}\n"
            f"  Uptime:  {u}"
        ), False

    # --- Temperature ---
    if any(w in q for w in ["temp", "hot", "warm", "cool", "thermal"]) and "cpu" in q or q in ("temp", "temperature"):
        t = sys_temp()
        if t is not None:
            if t < 50:
                status = "cool, running great"
            elif t < 65:
                status = "warm, normal under load"
            elif t < 75:
                status = "getting hot, might throttle soon"
            else:
                status = "too hot! check cooling"
            return f"  CPU temperature: {t}C ({status})", False
        return "  Couldn't read temperature.", "skip"

    # --- Disk ---
    if re.search(r"(disk|storage|space|how (much|many).*(free|left|space|storage))", q):
        d = sys_disk()
        return (
            f"  Disk: {d['disk_free_gb']}GB free out of {d['disk_total_gb']}GB\n"
            f"  {d['disk_percent']}% used"
        ), False

    # --- Memory ---
    if re.search(r"(ram|memory|mem)", q):
        m = sys_mem()
        return (
            f"  RAM: {m['ram_free_gb']}GB free out of {m['ram_total_gb']}GB\n"
            f"  {m['ram_percent']}% used"
        ), False

    # --- CPU ---
    if re.search(r"cpu.*(usage|percent|load|busy)", q) or q == "cpu":
        c = sys_cpu()
        t = sys_temp()
        return (
            f"  CPU: {c['cpu_percent']}% usage\n"
            f"  {c['cpu_cores']} cores at {c['cpu_mhz']} MHz\n"
            f"  Temperature: {t}C"
        ), False

    # --- IP / Network ---
    if re.search(r"\b(ip|address|network|wifi|internet|online|connected)\b", q):
        n = sys_net()
        lines = []
        for k, v in n.items():
            if k == "internet":
                lines.append(f"  Internet: {'connected' if v else 'not connected'}")
            else:
                lines.append(f"  {k}: {v}")
        return "\n".join(lines) if lines else "  No network interfaces found.", False

    # --- Uptime ---
    if re.search(r"(uptime|how long|when.*(boot|start))", q):
        return f"  Uptime: {sys_uptime()}", False

    # --- Pi hardware info ---
    if re.search(r"(hardware|board|model|pi info|about this|what (computer|pi|device)|specs)", q):
        pi = sys_pi_info()
        k = sys_kernel()
        lines = ["  Raspberry Pi Hardware:"]
        if "model" in pi:
            lines.append(f"    Model: {pi['model']}")
        lines.append(f"    Kernel: {k['kernel']}")
        lines.append(f"    Arch: {k['arch']}")
        if "throttled" in pi:
            lines.append(f"    Throttled: {pi['throttled']}")
        if "voltage" in pi:
            lines.append(f"    Voltage: {pi['voltage']}")
        if "arm_clock_mhz" in pi:
            lines.append(f"    ARM Clock: {pi['arm_clock_mhz']} MHz")
        return "\n".join(lines), False

    # --- USB devices ---
    if re.search(r"(usb|plugged|connected device|peripheral)", q):
        devices = sys_usb()
        if devices:
            lines = [f"  USB devices ({len(devices)}):"]
            for d in devices:
                lines.append(f"    {d}")
            return "\n".join(lines), False
        return "  No USB devices found.", "skip"

    # --- Bluetooth ---
    if re.search(r"(bluetooth|bt|paired)", q):
        devices = sys_bluetooth()
        if devices:
            lines = [f"  Bluetooth devices ({len(devices)}):"]
            for d in devices:
                lines.append(f"    {d}")
            return "\n".join(lines), False
        return "  No Bluetooth devices paired.", "skip"

    # --- External drives ---
    if re.search(r"(mount|drive|usb drive|external|thumb)", q):
        mounts = sys_mounts()
        if mounts:
            lines = [f"  Mounted drives ({len(mounts)}):"]
            for m in mounts:
                if "total_gb" in m:
                    lines.append(f"    {m['mount']} ({m['device']}) - {m['free_gb']}GB free / {m['total_gb']}GB")
                else:
                    lines.append(f"    {m['mount']} ({m['device']})")
            return "\n".join(lines), False
        return "  No external drives mounted.", "skip"

    # --- Failed services ---
    if re.search(r"(failed|broken|error).*(service|system)", q) or q == "errors":
        failed = sys_services()
        if failed:
            lines = [f"  {R}Failed services ({len(failed)}):{X}"]
            for s in failed:
                lines.append(f"    {s}")
            return "\n".join(lines), "skip"
        return "  No failed services. System is healthy.", "skip"

    # --- Display ---
    if re.search(r"(display|monitor|screen|resolution)", q):
        displays = sys_display()
        if displays:
            lines = ["  Display:"]
            for d in displays:
                lines.append(f"    {d}")
            return "\n".join(lines), "skip"
        return "  Couldn't read display info.", "skip"

    # --- Who am I ---
    if re.search(r"(who am i|whoami|my name|username|logged in)", q):
        import getpass
        user = getpass.getuser()
        hostname = socket.gethostname()
        return f"  You're {user} on {hostname}.", "skip"

    # --- Processes ---
    if re.search(r"(process|running|what.*(running|open)|top)", q):
        procs = sys_procs(8)
        lines = ["  PID    CPU%  MEM%  Name"]
        lines.append("  " + "-" * 35)
        for p in procs:
            lines.append(f"  {p['pid']:<6} {p['cpu']:<5} {p['mem']:<5} {p['name']}")
        return "\n".join(lines), False

    # --- Files / folders ---
    if re.search(r"(show|list|my).*(file|folder|dir|document)", q) or q in ("ls", "files", "folders"):
        dirs = sys_dirs()
        d = sys_disk()
        lines = [f"  Home folders ({len(dirs)}):"]
        for name in dirs:
            lines.append(f"    {name}/")
        lines.append(f"\n  Disk: {d['disk_free_gb']}GB free")
        return "\n".join(lines), False

    # --- Date/time ---
    if re.search(r"(time|date|day|today|what day)", q):
        now = datetime.now()
        return f"  It's {now.strftime('%A, %B %d, %Y at %I:%M %p')}.", "skip"

    # --- Find file by name ---
    m = re.search(r"(?:find|search|where is|locate)\s+(?:file\s+)?['\"]?(.+?)['\"]?\s*$", q)
    if m:
        term = m.group(1).strip()
        matches = find_file(term)
        if matches:
            lines = [f"  Found {len(matches)} file(s) matching '{term}':"]
            for rel, size in matches:
                lines.append(f"    ~/{rel}  ({format_size(size)})")
            return "\n".join(lines), "skip"
        else:
            return f"  No files found matching '{term}'.", "skip"

    # --- Search file contents ---
    m = re.search(r"(?:grep|search.*(?:for|containing)|files?.*(about|mentioning|with))\s+['\"]?(.+?)['\"]?\s*$", q)
    if m:
        term = m.group(2).strip()
        matches = search_file_contents(term)
        if matches:
            lines = [f"  Files containing '{term}':"]
            for f in matches:
                lines.append(f"    ~/{f}")
            return "\n".join(lines), "skip"
        else:
            return f"  No files containing '{term}' found.", "skip"

    # --- Open file ---
    m = re.match(r"open\s+(?:file\s+)?['\"]?(.+\.\w+)['\"]?", q)
    if m:
        filepath = m.group(1).strip()
        result = open_file(filepath)
        return f"  {result}", "skip"

    # --- Open / launch app ---
    m = re.match(r"(?:open|launch|start|run)\s+(?:the\s+)?(.+)", q)
    if m:
        app_name = m.group(1).strip()
        # Don't match file extensions - those are file opens
        if "." not in app_name or app_name in ("vs code", "v.l.c"):
            result = launch_app(app_name)
            if result:
                return f"  {result}", "skip"

    # --- Close app ---
    m = re.match(r"(?:close|quit|exit)\s+(?:the\s+)?(.+)", q)
    if m:
        app_name = m.group(1).strip()
        return f"  COMMAND: pkill -f {app_name}", True

    # --- Volume ---
    m = re.search(r"(?:volume|vol)\s+(?:to\s+)?(\d+)", q)
    if m:
        level = min(100, max(0, int(m.group(1))))
        result = set_volume(level)
        return f"  {result}", "skip"
    if re.search(r"(mute|silence|quiet)", q):
        result = set_volume(0)
        return f"  {result}", "skip"

    # --- Brightness ---
    m = re.search(r"(?:brightness|bright)\s+(?:to\s+)?(\d+)", q)
    if m:
        level = min(100, max(0, int(m.group(1))))
        result = set_brightness(level)
        return f"  {result}", "skip"

    # --- Install package ---
    m = re.match(r"install\s+(\S+)", q)
    if m:
        pkg = m.group(1)
        return f"  Installing {pkg}:\n  COMMAND: sudo apt install -y {pkg}", True

    # --- Update system ---
    if re.search(r"(update|upgrade).*(system|packages|apt|software)", q):
        return "  Updating system:\n  COMMAND: sudo apt update && sudo apt upgrade -y", True

    # --- Remove package ---
    m = re.match(r"(?:uninstall|remove)\s+(\S+)", q)
    if m:
        pkg = m.group(1)
        return f"  Removing {pkg}:\n  COMMAND: sudo apt remove -y {pkg}", True

    # --- Kill process ---
    m = re.match(r"kill\s+(\S+)", q)
    if m:
        target = m.group(1)
        if target.isdigit():
            return f"  COMMAND: kill {target}", True
        else:
            return f"  COMMAND: pkill {target}", True

    # --- Reboot ---
    if q in ("reboot", "restart"):
        return "  COMMAND: sudo reboot", True

    # --- Shutdown ---
    if q in ("shutdown", "power off", "poweroff"):
        return "  COMMAND: sudo shutdown now", True

    # --- Model info ---
    if q in ("model", "models", "what model", "which model"):
        lines = [f"  {BD}Models:{X}"]
        lines.append(f"    Default: {MODEL_DEFAULT.name}")
        lines.append(f"      {'exists' if MODEL_DEFAULT.exists() else 'NOT FOUND'}")
        lines.append(f"    Deep thinking: {MODEL_DEEP.name}")
        lines.append(f"      {'exists' if MODEL_DEEP.exists() else 'NOT FOUND'}")
        if MODEL_PHI3.exists():
            lines.append(f"\n    Phi-3 available. Edit config.yaml to use it.")
        else:
            lines.append(f"\n    Want smarter answers? Run:")
            lines.append(f"    {G}download phi3{X}")
        return "\n".join(lines), "skip"

    # --- Download models ---
    if q in ("download phi3", "get phi3", "install phi3"):
        return (
            f"  Downloading Phi-3 Mini (2.3GB)...\n"
            f"  COMMAND: wget -q --show-progress -O {MODEL_PHI3} "
            f"https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
        ), True

    # --- Config ---
    if q in ("config", "settings", "preferences"):
        if CONFIG_FILE.exists():
            lines = [f"  {BD}Config:{X} {CONFIG_FILE}"]
            lines.append(f"    Model (default): {MODEL_DEFAULT.name}")
            lines.append(f"    Model (deep): {MODEL_DEEP.name}")
            lines.append(f"    Tokens (normal/deep): {MAX_TOKENS}/{MAX_TOKENS_DEEP}")
            lines.append(f"    Timeout (normal/deep): {TIMEOUT}s/{TIMEOUT_DEEP}s")
            lines.append(f"    Humanize: {HUMANIZE}")
            lines.append(f"    Show raw data: {SHOW_RAW}")
            lines.append(f"    Memory turns: {MEMORY_SIZE}")
            lines.append(f"\n    Edit: {G}! nano {CONFIG_FILE}{X}")
            return "\n".join(lines), "skip"
        return f"  No config file found at {CONFIG_FILE}", "skip"

    # --- Help ---
    if q in ("help", "?", "commands"):
        return (
            f"  {BD}Hazel OS{X} - Your Raspberry Pi assistant\n\n"
            f"  {G}System:{X}\n"
            f"    status, temp, cpu, memory, disk, network, uptime, top\n"
            f"    hardware, usb, bluetooth, drives, display, errors, whoami\n\n"
            f"  {G}Files:{X}\n"
            f"    files, find <name>, search for <term>, open <file>\n\n"
            f"  {G}Apps:{X}\n"
            f"    open browser/editor/terminal/files/writer/vlc\n"
            f"    close <app>\n\n"
            f"  {G}System control:{X}\n"
            f"    install/remove <pkg>, volume <0-100>, brightness <0-100>\n"
            f"    update system, reboot, shutdown\n\n"
            f"  {G}Ask anything:{X}\n"
            f"    explain, why, how, what is... (uses AI)\n\n"
            f"  {G}Learn:{X}\n"
            f"    tutorial permissions/files/processes/networking/gpio/pi\n"
            f"    teach me <topic>\n\n"
            f"  {G}Config:{X}\n"
            f"    config, model, download phi3\n\n"
            f"  {G}Power:{X}\n"
            f"    ! <cmd>    Run bash directly\n"
            f"    exit       Quit Hazel"
        ), "skip"

    return None


# =============================================
# PART 6: LLM
# =============================================

def get_llm_context(query):
    """Build compact context string for LLM."""
    q = query.lower()
    parts = [f"host={socket.gethostname()}"]

    if any(w in q for w in ["cpu", "slow", "fast", "performance"]):
        c = sys_cpu()
        parts.append(f"cpu={c['cpu_percent']}%")
        t = sys_temp()
        if t:
            parts.append(f"temp={t}C")
    if any(w in q for w in ["mem", "ram"]):
        m = sys_mem()
        parts.append(f"ram={m['ram_free_gb']}GB/{m['ram_total_gb']}GB")
    if any(w in q for w in ["disk", "space", "storage"]):
        d = sys_disk()
        parts.append(f"disk={d['disk_free_gb']}GB/{d['disk_total_gb']}GB")

    if len(parts) <= 1:
        t = sys_temp()
        c = sys_cpu()
        m = sys_mem()
        parts.append(f"cpu={c['cpu_percent']}%")
        if t:
            parts.append(f"temp={t}C")
        parts.append(f"ram={m['ram_free_gb']}GB free")

    # Add conversation memory
    mem = get_memory_context()
    if mem:
        parts.append(mem)

    return ", ".join(parts)


def run_llm(prompt_text, model_path, tokens, timeout, temp=None):
    """Core LLM runner. Writes prompt to file, calls llama-completion."""
    HAZEL_DIR.mkdir(exist_ok=True)
    PROMPT_FILE.write_text(prompt_text)

    t = temp if temp is not None else TEMPERATURE
    cmd_str = (
        f'"{LLAMA_BIN}" '
        f'-m "{model_path}" '
        f'-f "{PROMPT_FILE}" '
        f'-n {tokens} '
        f'-t {THREADS} --temp {t} --top-p 0.9 --no-display-prompt '
        f'2>/dev/null'
    )

    try:
        result = subprocess.run(
            cmd_str, shell=True,
            capture_output=True, text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        text = result.stdout.strip()
        for tok in ["</s>", "<|user|>", "<|assistant|>", "<|system|>", "> EOF"]:
            text = text.split(tok)[0]
        return text.strip() if text.strip() else None
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        return f"[error: {e}]"


def humanize(data, query):
    """Make raw data conversational via quick LLM pass."""
    if not HUMANIZE:
        return re.sub(r'\033\[[0-9;]*m', '', data).strip()

    clean = re.sub(r'\033\[[0-9;]*m', '', data).strip()

    prompt = (
        "<|system|>\n"
        "Rewrite the data as one short sentence. Only use the numbers given. Add nothing extra.</s>\n"
        f"<|user|>\n{clean}</s>\n"
        "<|assistant|>\n"
    )

    result = run_llm(prompt, MODEL_DEFAULT, 60, 15, temp=0.5)
    if result and len(result) > 10:
        return result
    return clean

    try:
        result = subprocess.run(
            cmd_str, shell=True,
            capture_output=True, text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
        text = result.stdout.strip()
        for tok in ["</s>", "<|user|>", "<|assistant|>", "<|system|>", "> EOF"]:
            text = text.split(tok)[0]
        text = text.strip()
        if text and len(text) > 10:
            return text
    except Exception:
        pass
    return clean


def is_deep_query(query):
    q = query.lower()
    return any(kw in q for kw in DEEP_KEYWORDS)


def ask_llm(user_input, context):
    """Query LLM for novel/complex queries. Uses bigger model for deep queries."""
    deep = is_deep_query(user_input)
    tokens = MAX_TOKENS_DEEP if deep else MAX_TOKENS
    timeout = TIMEOUT_DEEP if deep else TIMEOUT
    model = MODEL_DEEP if deep else MODEL_DEFAULT

    if deep:
        system_msg = (
            "You are Hazel, a knowledgeable computer assistant on a Raspberry Pi 5. "
            "Give thorough, complete answers. Finish your sentences. "
            "Use the data provided when relevant. "
            "To suggest a bash command write COMMAND: <cmd>"
        )
    else:
        system_msg = (
            "You are Hazel, a computer assistant on a Raspberry Pi 5. "
            "Give short, helpful answers. Finish your sentences. "
            "Use the data provided. "
            "To suggest a bash command write COMMAND: <cmd>"
        )

    prompt = (
        f"<|system|>\n{system_msg}\n"
        f"System: {context}</s>\n"
        f"<|user|>\n{user_input}</s>\n"
        "<|assistant|>\n"
    )

    return run_llm(prompt, model, tokens, timeout)


# =============================================
# PART 7: COMMAND EXECUTION + SAFETY
# =============================================

DANGEROUS = [
    r"rm\s+(-\w*[rf]|--recursive|--force)",
    r"\bmkfs\b", r"\bdd\b\s.*of=", r"\bshutdown\b",
    r"\breboot\b", r"\bsudo\s+rm\b", r"\bfdisk\b",
    r">\s*/dev/", r"\bchmod\s+777\b",
]

def is_dangerous(cmd):
    for pat in DANGEROUS:
        if re.search(pat, cmd):
            return True
    return False

def extract_commands(text):
    cmds = []
    clean = []
    for line in text.split("\n"):
        s = line.strip()
        if s.upper().startswith("COMMAND:"):
            cmd = s[8:].strip().strip("`").strip()
            if cmd:
                cmds.append(cmd)
        else:
            clean.append(line)
    return "\n".join(clean).strip(), cmds

def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        out = ""
        if result.stdout:
            out += result.stdout
        if result.returncode != 0 and result.stderr:
            out += f"\n{R}{result.stderr}{X}"
        return out.strip() if out.strip() else "(done)"
    except subprocess.TimeoutExpired:
        return f"{R}Timed out.{X}"

def execute_commands(commands):
    for cmd in commands:
        print()
        if is_dangerous(cmd):
            print(f"  {Y}{BD}warning:{X} {Y}{cmd}{X}")
            try:
                confirm = input(f"  {Y}run? (yes/no): {X}").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print(f"\n  {D}cancelled{X}")
                continue
            if confirm != "yes":
                print(f"  {D}cancelled{X}")
                continue
        else:
            print(f"  {D}$ {cmd}{X}")

        output = run_cmd(cmd)
        if output:
            for line in output.split("\n")[:25]:
                print(f"  {line}")
            total = len(output.split("\n"))
            if total > 25:
                print(f"  {D}... ({total} lines total){X}")


# =============================================
# PART 8: MAIN INTERFACE
# =============================================

def banner():
    print(f"""
{BD}{G}  _   _               _
 | | | | __ _ ______| |
 | |_| |/ _` |_  / _` |
 |  _  | (_| |/ /  __/ |
 |_| |_|\\__,_/___\\___|_|{X}
 {D}{sys_overview()}
 Type 'help' for commands. '!' for bash.{X}
""")


def first_boot():
    """Show welcome message on first run."""
    marker = HAZEL_DIR / ".welcomed"
    if marker.exists():
        return
    marker.touch()
    print(f"""
{BD}{G}  Welcome to Hazel OS!{X}

  I'm Hazel, your local AI assistant.
  I run entirely on this Raspberry Pi - no cloud, no tracking.

  Try asking me:
    {G}status{X}          - see how your system is doing
    {G}open browser{X}    - launch Chromium
    {G}find readme{X}     - search for files
    {G}explain linux{X}   - I'll teach you
    {G}help{X}            - see everything I can do

  Let's get started!
""")


def main():
    HAZEL_DIR.mkdir(exist_ok=True)

    try:
        readline.read_history_file(str(HISTORY_FILE))
    except FileNotFoundError:
        pass
    readline.set_history_length(500)

    first_boot()
    banner()

    while True:
        try:
            user_input = input(f"{G}hazel>{X} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{D}bye!{X}")
            break

        if not user_input:
            continue

        readline.write_history_file(str(HISTORY_FILE))

        if user_input.lower() in ("exit", "quit", "bye", "q"):
            print(f"{D}bye!{X}")
            break

        # Raw bash
        if user_input.startswith("!"):
            cmd = user_input[1:].strip()
            if cmd:
                print(run_cmd(cmd))
                print()
            continue

        # Tutorials
        if user_input.lower().startswith("tutorial"):
            parts = user_input.lower().split(None, 1)
            name = parts[1] if len(parts) > 1 else ""
            if not name:
                available = ", ".join(TUTORIALS.keys())
                print(f"\n{B}  Tutorials: {available}{X}")
                print(f"  {D}Type: tutorial <name>{X}\n")
            else:
                # Fuzzy match tutorial name
                matched = None
                for key in TUTORIALS:
                    if name in key or key in name:
                        matched = key
                        break
                if matched:
                    run_tutorial(matched)
                else:
                    available = ", ".join(TUTORIALS.keys())
                    print(f"\n{Y}  No tutorial '{name}'. Available: {available}{X}\n")
            continue

        # Learn / teach shortcuts
        if re.match(r"(learn|teach me)\s+(.+)", user_input.lower()):
            topic = re.match(r"(?:learn|teach me)\s+(.+)", user_input.lower()).group(1)
            for key in TUTORIALS:
                if topic in key or key in topic:
                    run_tutorial(key)
                    break
            else:
                # No tutorial, fall through to LLM
                pass
            continue

        # === Try instant handler first ===
        instant = handle_instant(user_input)
        if instant is not None:
            response_text, flag = instant
            display, commands = extract_commands(response_text)

            if flag == "skip":
                if display:
                    print(f"\n{B}{display}{X}")
            elif display and not commands:
                if HUMANIZE:
                    sys.stdout.write(f"{D}...{X}")
                    sys.stdout.flush()
                    natural = humanize(display, user_input)
                    sys.stdout.write("\r" + " " * 20 + "\r")
                    sys.stdout.flush()
                    print(f"\n{B}{natural}{X}")
                    if SHOW_RAW:
                        print(f"{D}({display.strip()}){X}")
                else:
                    print(f"\n{B}{display}{X}")
            elif display:
                print(f"\n{B}{display}{X}")

            if commands:
                execute_commands(commands)

            # Remember the exchange
            remember("user", user_input)
            remember("hazel", display[:100] if display else "")
            print()
            continue

        # === Fall back to LLM ===
        deep = is_deep_query(user_input)
        if deep:
            sys.stdout.write(f"{D}thinking deeply...{X}")
        else:
            sys.stdout.write(f"{D}thinking...{X}")
        sys.stdout.flush()

        context = get_llm_context(user_input)
        start = time.time()
        response = ask_llm(user_input, context)
        elapsed = time.time() - start

        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()

        if response is None:
            print(f"{Y}Hmm, couldn't figure that out. Try rephrasing?{X}\n")
            continue

        display, commands = extract_commands(response)
        if display:
            print(f"\n{B}{display}{X}")
        print(f"{D}({elapsed:.1f}s){X}")

        if commands:
            execute_commands(commands)

        # Remember
        remember("user", user_input)
        remember("hazel", display[:100] if display else "")

        print()


if __name__ == "__main__":
    main()
