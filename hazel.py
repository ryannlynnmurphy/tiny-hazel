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
try:
    import readline
except ImportError:
    readline = None  # Windows
import shutil
import glob as globmod
from pathlib import Path
from datetime import datetime

# === CONFIG ===
HAZEL_DIR = Path.home() / ".hazel"
CONFIG_FILE = Path(__file__).parent / "config.yaml"
import platform as _platform
_IS_WINDOWS = _platform.system() == "Windows"
_EXE = ".exe" if _IS_WINDOWS else ""

# Prefer GPU-accelerated binary if available
_VULKAN_BIN = Path.home() / "llama.cpp" / "build" / "bin" / "vulkan" / f"llama-completion{_EXE}"
_CPU_BIN = Path.home() / "llama.cpp" / "build" / "bin" / f"llama-completion{_EXE}"
LLAMA_BIN = _VULKAN_BIN if _VULKAN_BIN.exists() else _CPU_BIN
GPU_LAYERS = 99 if _VULKAN_BIN.exists() else 0

# Three-tier model routing
MODEL_TIER1 = None  # TinyLlama: only for humanizing raw data
MODEL_TIER2 = None  # Phi-3: default inference (normal questions)
MODEL_TIER3 = None  # Mistral/Llama3: deep reasoning
HISTORY_FILE = HAZEL_DIR / "history"
PROMPT_FILE = HAZEL_DIR / "prompt.txt"

# Defaults (overridden by config.yaml)
MAX_TOKENS = 200
MAX_TOKENS_DEEP = 500
TIMEOUT = 90
TIMEOUT_DEEP = 180
THREADS = 4
TEMPERATURE = 0.7
HUMANIZE = True
SHOW_RAW = True
MEMORY_SIZE = 6

# Model registry: name → (filename, url, size_gb, min_ram_gb, description)
MODEL_REGISTRY = {
    "tinyllama": (
        "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        0.6, 2, "1.1B - Fast, basic (any machine)"
    ),
    "phi3": (
        "Phi-3-mini-4k-instruct-q4.gguf",
        "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        2.3, 4, "3.8B - Good reasoning, moderate speed"
    ),
    "mistral": (
        "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        4.1, 8, "7B - Strong all-round, needs 8GB+"
    ),
    "llama3": (
        "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        4.9, 8, "8B - Meta's best small model, needs 8GB+"
    ),
    "deepseek": (
        "DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf",
        "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF/resolve/main/DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf",
        4.9, 8, "8B - Reasoning/chain-of-thought, needs 8GB+"
    ),
    "qwen": (
        "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
        4.4, 8, "7B - Best multilingual, needs 8GB+"
    ),
}

MODEL_DIR = Path.home() / "models"
MODEL_DEFAULT = None  # Set by auto_select_models()
MODEL_DEEP = None


def get_available_ram_gb():
    """Total system RAM in GB."""
    return round(psutil.virtual_memory().total / 1e9, 1)


def has_gpu():
    """Check if a usable GPU is available."""
    # NVIDIA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True
    except (FileNotFoundError, Exception):
        pass
    # Vulkan binary exists = we can use whatever GPU is present (Intel Arc, AMD, etc.)
    if _VULKAN_BIN.exists():
        return True
    # macOS Metal (Apple Silicon)
    try:
        r = subprocess.run(["sysctl", "-n", "hw.memsize"],
                          capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            if _platform.machine() == "arm64":
                return True
    except (FileNotFoundError, Exception):
        pass
    return False


def get_installed_models():
    """List models that are already downloaded."""
    installed = {}
    MODEL_DIR.mkdir(exist_ok=True)
    for name, (filename, url, size, min_ram, desc) in MODEL_REGISTRY.items():
        path = MODEL_DIR / filename
        if path.exists():
            installed[name] = path
    return installed


def auto_select_models():
    """Pick the best models for this machine. Three tiers:
    Tier 1 (TinyLlama): Only humanizes raw data into plain English
    Tier 2 (Phi-3): Default inference for normal questions
    Tier 3 (Mistral+): Deep reasoning, complex queries
    """
    global MODEL_DEFAULT, MODEL_DEEP, MODEL_TIER1, MODEL_TIER2, MODEL_TIER3

    ram = get_available_ram_gb()
    gpu = has_gpu()
    installed = get_installed_models()

    # Tier 1: Always TinyLlama (fast, for humanizing data only)
    MODEL_TIER1 = installed.get("tinyllama", MODEL_DIR / MODEL_REGISTRY["tinyllama"][0])

    # Tier 2: Mid-size model for normal inference
    if "phi3" in installed:
        MODEL_TIER2 = installed["phi3"]
    elif "tinyllama" in installed:
        MODEL_TIER2 = installed["tinyllama"]
    else:
        MODEL_TIER2 = MODEL_TIER1

    # Tier 3: Largest available for deep reasoning (GPU preferred)
    if gpu and ram >= 12 and "deepseek" in installed:
        MODEL_TIER3 = installed["deepseek"]
    elif gpu and ram >= 12 and "llama3" in installed:
        MODEL_TIER3 = installed["llama3"]
    elif gpu and ram >= 12 and "mistral" in installed:
        MODEL_TIER3 = installed["mistral"]
    elif gpu and ram >= 12 and "qwen" in installed:
        MODEL_TIER3 = installed["qwen"]
    elif "phi3" in installed:
        MODEL_TIER3 = installed["phi3"]
    else:
        MODEL_TIER3 = MODEL_TIER2

    # Set legacy aliases
    MODEL_DEFAULT = MODEL_TIER2
    MODEL_DEEP = MODEL_TIER3

    return ram, gpu, installed


def recommend_models():
    """Suggest models the user should download."""
    ram = get_available_ram_gb()
    installed = get_installed_models()
    recs = []

    if ram >= 12:
        for name in ["mistral", "llama3", "deepseek", "qwen"]:
            if name not in installed:
                _, _, size, _, desc = MODEL_REGISTRY[name]
                recs.append((name, desc, size))
    if ram >= 4 and "phi3" not in installed:
        _, _, size, _, desc = MODEL_REGISTRY["phi3"]
        recs.append(("phi3", desc, size))
    if "tinyllama" not in installed:
        _, _, size, _, desc = MODEL_REGISTRY["tinyllama"]
        recs.append(("tinyllama", desc, size))

    return recs


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

    # Model selection from config (overrides auto-select unless "auto")
    mdl = config.get("model", {})
    default_name = mdl.get("default", "auto")
    deep_name = mdl.get("deep", "auto")

    installed = get_installed_models()
    if default_name != "auto" and default_name in installed:
        MODEL_DEFAULT = installed[default_name]
    if deep_name != "auto" and deep_name in installed:
        MODEL_DEEP = installed[deep_name]


# Auto-select models first, then config can override
auto_select_models()
load_config()

# Load user profile
from importlib import import_module as _imp
try:
    _profiler = _imp("hazel-profile".replace("-", "_"))
    USER_PROFILE = _profiler.load_profile()
    USER_SUMMARY = _profiler.get_profile_summary()
except Exception:
    # Inline fallback
    USER_PROFILE = None
    USER_SUMMARY = ""
    _profile_path = HAZEL_DIR / "profile.json"
    if _profile_path.exists():
        try:
            import json as _json
            USER_PROFILE = _json.loads(_profile_path.read_text())
            USER_SUMMARY = USER_PROFILE.get("summary", "")
        except Exception:
            pass

DEEP_KEYWORDS = [
    "explain", "why does", "why is", "why do",
    "how does", "how do", "how is",
    "teach me", "help me understand", "tell me about",
    "describe how", "compare",  "difference between",
    "write a", "write me", "create a",
    "debug", "troubleshoot", "diagnose",
    "analyze", "evaluate",
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
NOTES_FILE = HAZEL_DIR / "notes.json"

def remember(role, content):
    """Store conversation turn for context."""
    if MEMORY_SIZE == 0:
        return
    conversation_history.append({"role": role, "content": content})
    while len(conversation_history) > MEMORY_SIZE:
        conversation_history.pop(0)

def get_memory_context():
    """Format recent conversation for LLM."""
    parts = []
    if conversation_history:
        lines = []
        for turn in conversation_history[-4:]:
            if turn["role"] == "user":
                lines.append(f"User said: {turn['content']}")
            else:
                lines.append(f"You said: {turn['content'][:80]}")
        parts.append("Recent conversation: " + ". ".join(lines))
    # Add persistent notes
    notes = load_notes()
    if notes:
        parts.append("Things I know: " + ". ".join(notes))
    return ". ".join(parts)

def load_notes():
    """Load persistent user notes."""
    if NOTES_FILE.exists():
        try:
            return json.loads(NOTES_FILE.read_text())
        except Exception:
            pass
    return []

def save_note(note):
    """Save a persistent note about the user."""
    notes = load_notes()
    notes.append(note)
    # Keep last 50 notes
    notes = notes[-50:]
    HAZEL_DIR.mkdir(exist_ok=True)
    NOTES_FILE.write_text(json.dumps(notes, indent=2))


# =============================================
# PART 1: SYSTEM READING
# =============================================

def sys_cpu():
    pct = psutil.cpu_percent(interval=0.3)
    freq = psutil.cpu_freq()
    mhz = round(freq.current) if freq else "?"
    return {"cpu_percent": pct, "cpu_cores": psutil.cpu_count(), "cpu_mhz": mhz}

def sys_temp():
    # Pi
    try:
        r = subprocess.run(["vcgencmd", "measure_temp"],
                          capture_output=True, text=True, timeout=2)
        return float(r.stdout.strip().split("=")[1].split("'")[0])
    except (FileNotFoundError, Exception):
        pass
    # Linux thermal zone
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries:
                    return round(entries[0].current, 1)
    except Exception:
        pass
    # macOS
    try:
        r = subprocess.run(["osx-cpu-temp"], capture_output=True, text=True, timeout=2)
        return float(r.stdout.strip().split("°")[0])
    except (FileNotFoundError, Exception):
        pass
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

def sys_gpu():
    """Detect GPU(s)."""
    gpus = []
    # NVIDIA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.strip().split("\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    gpus.append({
                        "name": parts[0],
                        "vram_total_mb": parts[1],
                        "vram_free_mb": parts[2],
                        "temp_c": parts[3],
                        "usage_pct": parts[4],
                        "type": "nvidia",
                    })
    except (FileNotFoundError, Exception):
        pass

    # AMD (ROCm)
    try:
        r = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--showtemp"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpus.append({"name": "AMD GPU (ROCm)", "raw": r.stdout.strip()[:200], "type": "amd"})
    except (FileNotFoundError, Exception):
        pass

    # Raspberry Pi VideoCore
    try:
        r = subprocess.run(["vcgencmd", "measure_clock", "v3d"],
                          capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            freq = int(r.stdout.strip().split("=")[1]) // 1000000
            gpus.append({"name": "VideoCore VII", "clock_mhz": freq, "type": "videocore"})
    except (FileNotFoundError, Exception):
        pass

    # macOS Metal
    try:
        r = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                          capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if "Chipset Model" in line:
                name = line.split(":")[1].strip()
                gpus.append({"name": name, "type": "metal"})
            elif "VRAM" in line:
                if gpus:
                    gpus[-1]["vram"] = line.split(":")[1].strip()
    except (FileNotFoundError, Exception):
        pass

    return gpus


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
    """Search file contents."""
    home = str(Path.home())
    matches = []
    exts = {".txt", ".md", ".py", ".json", ".csv", ".sh", ".html", ".css", ".yaml", ".yml"}
    try:
        for root, dirs, files in os.walk(home):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "llama.cpp")]
            for f in files:
                if Path(f).suffix.lower() in exts:
                    fp = os.path.join(root, f)
                    try:
                        with open(fp, "r", errors="ignore") as fh:
                            if term.lower() in fh.read(50000).lower():
                                matches.append(os.path.relpath(fp, home))
                                if len(matches) >= 10:
                                    return matches
                    except Exception:
                        pass
    except Exception:
        pass
    return matches


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
        "browser": "firefox" if shutil.which("firefox") else "chromium-browser",
        "web": "firefox" if shutil.which("firefox") else "chromium-browser",
        "chrome": "chrome" if shutil.which("chrome") else "chromium-browser",
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

    # --- Model info (must be before hardware which also matches "model") ---
    if q in ("model", "models", "what model", "which model"):
        ram = get_available_ram_gb()
        gpu = has_gpu()
        installed = get_installed_models()
        recs = recommend_models()

        lines = [f"  {BD}Models:{X}"]
        lines.append(f"    System: {ram}GB RAM{', GPU detected' if gpu else ''}")
        lines.append(f"")
        lines.append(f"    Routing:")
        t1 = MODEL_TIER1.name if MODEL_TIER1 and hasattr(MODEL_TIER1, 'name') else "none"
        t2 = MODEL_TIER2.name if MODEL_TIER2 and hasattr(MODEL_TIER2, 'name') else "none"
        t3 = MODEL_TIER3.name if MODEL_TIER3 and hasattr(MODEL_TIER3, 'name') else "none"
        lines.append(f"      Tier 1 (humanize): {t1}")
        lines.append(f"      Tier 2 (default):  {t2}")
        lines.append(f"      Tier 3 (deep):     {t3}")
        lines.append(f"")
        lines.append(f"    Installed:")
        if installed:
            for name, path in installed.items():
                desc = MODEL_REGISTRY[name][4]
                size = MODEL_REGISTRY[name][2]
                active = ""
                if MODEL_DEFAULT and path == MODEL_DEFAULT:
                    active = " (active: default)"
                elif MODEL_DEEP and path == MODEL_DEEP:
                    active = " (active: deep)"
                lines.append(f"      {name}: {desc} [{size}GB]{active}")
        else:
            lines.append(f"      none")

        if recs:
            lines.append(f"")
            lines.append(f"    Recommended downloads:")
            for name, desc, size in recs[:3]:
                lines.append(f"      {G}download {name}{X} - {desc} [{size}GB]")

        return "\n".join(lines), "skip"

    # --- Download models ---
    dm = re.match(r"download\s+(\S+)", q)
    if dm:
        name = dm.group(1).lower()
        if name in MODEL_REGISTRY:
            filename, url, size, min_ram, desc = MODEL_REGISTRY[name]
            ram = get_available_ram_gb()
            path = MODEL_DIR / filename

            if path.exists():
                return f"  {name} is already downloaded.", "skip"

            warn = ""
            if ram < min_ram:
                warn = f"\n  {Y}Warning: You have {ram}GB RAM, this model needs {min_ram}GB+{X}"

            return (
                f"  Downloading {name} ({size}GB) - {desc}{warn}\n"
                f"  COMMAND: mkdir -p {MODEL_DIR} && wget -q --show-progress -O {path} {url}"
            ), True
        else:
            available = ", ".join(MODEL_REGISTRY.keys())
            return f"  Unknown model '{name}'. Available: {available}", "skip"

    # --- Profile ---
    if q in ("profile", "who am i", "about me", "what do you know about me"):
        if USER_PROFILE:
            lines = [f"  {BD}User Profile:{X}"]
            lines.append(f"    {USER_PROFILE.get('summary', 'No summary')}")
            lines.append(f"")
            if USER_PROFILE.get("roles"):
                lines.append(f"    Roles: {', '.join(USER_PROFILE['roles'])}")
            if USER_PROFILE.get("languages"):
                langs = ", ".join(l["name"] for l in USER_PROFILE["languages"][:6])
                lines.append(f"    Languages: {langs}")
            if USER_PROFILE.get("git_repos"):
                repos = ", ".join(r["name"] for r in USER_PROFILE["git_repos"][:5])
                lines.append(f"    Projects: {repos}")
            if USER_PROFILE.get("recent_files"):
                recent = ", ".join(f["name"] for f in USER_PROFILE["recent_files"][:5])
                lines.append(f"    Recent work: {recent}")
            if USER_PROFILE.get("frequent_commands"):
                cmds = ", ".join(c["cmd"] for c in USER_PROFILE["frequent_commands"][:8])
                lines.append(f"    Frequent commands: {cmds}")
            lines.append(f"")
            lines.append(f"    {D}Rescan: scan profile{X}")
            return "\n".join(lines), "skip"
        else:
            return (
                f"  I don't know you yet! Let me scan your machine.\n"
                f"  COMMAND: python3 {Path(__file__).parent}/hazel-profile.py"
            ), True

    # --- Rescan profile ---
    if q in ("scan profile", "rescan", "learn about me", "scan me", "scan"):
        return (
            f"  Scanning your machine to learn about you...\n"
            f"  COMMAND: python3 {Path(__file__).parent}/hazel-profile.py"
        ), True

    # --- Remember / my name is ---
    m = re.match(r"(?:my name is|i'm|im|i am|call me)\s+(.+)", q)
    if m:
        name = m.group(1).strip().title()
        save_note(f"User's name is {name}")
        return f"  Got it! I'll remember your name is {name}.", "skip"

    m = re.match(r"(?:remember|note|save)\s+(?:that\s+)?(.+)", q)
    if m:
        note = m.group(1).strip()
        save_note(note)
        return f"  Noted: {note}", "skip"

    # --- Recall notes ---
    if q in ("notes", "what do you remember", "memories"):
        notes = load_notes()
        if notes:
            lines = [f"  {BD}Things I remember:{X}"]
            for n in notes:
                lines.append(f"    - {n}")
            return "\n".join(lines), "skip"
        return "  I don't have any notes yet. Tell me things with 'remember <fact>'.", "skip"

    # --- Forget ---
    if q in ("forget everything", "clear notes", "forget"):
        if NOTES_FILE.exists():
            NOTES_FILE.unlink()
        return "  Notes cleared.", "skip"

    # --- Config ---
    if q in ("config", "settings", "preferences"):
        if CONFIG_FILE.exists():
            lines = [f"  {BD}Config:{X} {CONFIG_FILE}"]
            lines.append(f"    Model (default): {MODEL_DEFAULT.name if MODEL_DEFAULT else 'none'}")
            lines.append(f"    Model (deep): {MODEL_DEEP.name if MODEL_DEEP else 'none'}")
            lines.append(f"    Tokens (normal/deep): {MAX_TOKENS}/{MAX_TOKENS_DEEP}")
            lines.append(f"    Timeout (normal/deep): {TIMEOUT}s/{TIMEOUT_DEEP}s")
            lines.append(f"    Humanize: {HUMANIZE}")
            lines.append(f"    Show raw data: {SHOW_RAW}")
            lines.append(f"    Memory turns: {MEMORY_SIZE}")
            lines.append(f"\n    Edit: {G}! nano {CONFIG_FILE}{X}")
            return "\n".join(lines), "skip"
        return f"  No config file found at {CONFIG_FILE}", "skip"

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

    # --- Hardware info ---
    if re.search(r"(hardware|board|pi info|about this|what (computer|pi|device)|specs)", q):
        pi = sys_pi_info()
        k = sys_kernel()
        c = sys_cpu()
        m = sys_mem()
        gpus = sys_gpu()

        lines = ["  Hardware:"]
        if "model" in pi:
            lines.append(f"    Model: {pi['model']}")
        lines.append(f"    OS: {k['os']}")
        lines.append(f"    Kernel: {k['kernel']}")
        lines.append(f"    Arch: {k['arch']}")
        lines.append(f"    CPU: {c['cpu_cores']} cores, {c['cpu_mhz']} MHz")
        lines.append(f"    RAM: {m['ram_total_gb']}GB")
        if "throttled" in pi:
            lines.append(f"    Throttled: {pi['throttled']}")
        if "voltage" in pi:
            lines.append(f"    Voltage: {pi['voltage']}")
        if gpus:
            for g in gpus:
                gpu_str = f"    GPU: {g['name']}"
                if "vram_total_mb" in g:
                    gpu_str += f" ({g['vram_total_mb']}MB VRAM)"
                elif "vram" in g:
                    gpu_str += f" ({g['vram']})"
                lines.append(gpu_str)
        return "\n".join(lines), False

    # --- GPU ---
    if re.search(r"(gpu|graphics|video card|nvidia|amd|radeon|metal|cuda)", q):
        gpus = sys_gpu()
        if gpus:
            lines = [f"  GPU ({len(gpus)}):"]
            for g in gpus:
                lines.append(f"    {g['name']}")
                if "vram_total_mb" in g:
                    lines.append(f"      VRAM: {g['vram_free_mb']}MB free / {g['vram_total_mb']}MB")
                if "temp_c" in g:
                    lines.append(f"      Temp: {g['temp_c']}C")
                if "usage_pct" in g:
                    lines.append(f"      Usage: {g['usage_pct']}%")
                if "vram" in g:
                    lines.append(f"      VRAM: {g['vram']}")
                if "clock_mhz" in g:
                    lines.append(f"      Clock: {g['clock_mhz']} MHz")
            return "\n".join(lines), False
        return "  No GPU detected (or no drivers installed).", "skip"

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

    # --- Smart open: files, folders, or apps ---
    m = re.match(r"(?:open|pull up|show me|go to|launch|start|run)\s+(?:the\s+|my\s+)?(.+)", q)
    if m:
        target = m.group(1).strip().strip("'\"")

        # 1. Exact file with extension
        if "." in target and not target.endswith("."):
            result = open_file(target)
            return f"  {result}", "skip"

        # 2. Check if it's a known app first (before file search)
        app_result = launch_app(target)
        if app_result:
            return f"  {app_result}", "skip"

        # 3. Check if it's a folder in home
        home = Path.home()
        for d in home.iterdir():
            if d.is_dir() and d.name.lower() == target.lower():
                result = open_file(str(d))
                return f"  Opened folder: {d.name}/", "skip"

        # 4. Search for matching files/folders
        matches = find_file(target)
        if matches:
            if len(matches) == 1:
                # Only one match - open it directly
                full_path = home / matches[0][0]
                result = open_file(str(full_path))
                return f"  {result}", "skip"
            else:
                lines = [f"  Found {len(matches)} matches for '{target}':"]
                for i, (rel, size) in enumerate(matches[:8], 1):
                    lines.append(f"    {i}. ~/{rel}  ({format_size(size)})")
                lines.append(f"\n  Say 'open <filename>' to open one.")
                return "\n".join(lines), "skip"

        return f"  Couldn't find '{target}' as a file, folder, or app.", "skip"

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
            f"    ! <cmd>    Run bash command\n"
            f"    bash       Drop to full bash shell\n"
            f"    clear      Clear screen\n"
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

    # Add user profile
    if USER_SUMMARY:
        parts.append(USER_SUMMARY)

    # Add conversation memory
    mem = get_memory_context()
    if mem:
        parts.append(mem)

    return ", ".join(parts)


def trim_incomplete(text):
    """Remove trailing incomplete sentence if output was cut off."""
    if not text:
        return text
    # If ends with sentence-ending punctuation, it's fine
    if text[-1] in ".!?\"')":
        return text
    # Find last sentence boundary
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ".!?":
            return text[:i + 1]
    # No sentence boundary found - return as-is (short response)
    return text


def run_llm(prompt_text, model_path, tokens, timeout, temp=None):
    """Core LLM runner. Writes prompt to file, calls llama-completion."""
    HAZEL_DIR.mkdir(exist_ok=True)
    PROMPT_FILE.write_text(prompt_text)

    t = temp if temp is not None else TEMPERATURE
    cmd = [
        str(LLAMA_BIN),
        "-m", str(model_path),
        "-f", str(PROMPT_FILE),
        "-n", str(tokens),
        "-t", str(THREADS),
        "--temp", str(t),
        "--top-p", "0.9",
        "--no-display-prompt",
        "-ngl", str(GPU_LAYERS),
    ]

    try:
        # Windows needs CREATE_NO_WINDOW to prevent console issues
        kwargs = {
            "capture_output": True,
            "timeout": timeout,
            "stdin": subprocess.DEVNULL,
        }
        if _IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(cmd, **kwargs)
        # Decode with error handling for Windows
        result.stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout
        result.stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else result.stderr
        text = result.stdout.strip()
        for tok in ["</s>", "<|user|>", "<|assistant|>", "<|system|>", "> EOF"]:
            text = text.split(tok)[0]
        text = text.strip()
        if not text:
            return None
        # Trim trailing incomplete sentence
        text = trim_incomplete(text)
        return text
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

    result = run_llm(prompt, MODEL_TIER1 or MODEL_DEFAULT, 60, 15, temp=0.5)
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
        model = MODEL_TIER3 or MODEL_DEEP
        system_msg = (
            "You are Hazel, a local AI assistant created by Ryann Lynn Murphy. "
            "You run entirely on this computer with no cloud. "
            "Answer the user's question directly and conversationally. "
            "Be thorough but natural. End every response with a complete sentence."
        )
    else:
        model = MODEL_TIER2 or MODEL_DEFAULT
        system_msg = (
            "You are Hazel, a local AI assistant created by Ryann Lynn Murphy. "
            "You run entirely on this computer with no cloud. "
            "Answer the user's question directly in 2-3 sentences. "
            "Be conversational and natural. Do not mention commands or bash unless asked."
        )

    prompt = (
        f"<|system|>\n{system_msg}\n"
        f"About this computer: {context}</s>\n"
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

FACES = {
    "cool": "(^_^)",
    "warm": "(o_o)",
    "hot": "(>_<)",
    "happy": "(^-^)",
    "thinking": "(-_-)",
    "greeting": "(~_^)",
}

def get_face():
    """Hazel's mood based on system state."""
    t = sys_temp()
    if t is None:
        return FACES["happy"]
    if t < 50:
        return FACES["cool"]
    elif t < 65:
        return FACES["warm"]
    else:
        return FACES["hot"]

def banner():
    face = get_face()
    try:
        print(f"""
{BD}{G}  ╦ ╦╔═╗╔═╗╔═╗╦
  ╠═╣╠═╣╔═╝║╣ ║
  ╩ ╩╩ ╩╚═╝╚═╝╩═╝{X}  {face}
 {D}{sys_overview()}
 Type 'help' for commands. '!' for bash.{X}
""")
    except UnicodeEncodeError:
        # Windows fallback
        print(f"""
{BD}{G}  H A Z E L{X}  {face}
 {D}{sys_overview()}
 Type 'help' for commands. '!' for bash.{X}
""")


def first_boot():
    """Show welcome message on first run."""
    marker = HAZEL_DIR / ".welcomed"
    if marker.exists():
        return
    marker.touch()

    hostname = socket.gethostname()
    ram = get_available_ram_gb()
    installed = get_installed_models()
    model_name = list(installed.keys())[0] if installed else "none"

    print(f"""
{BD}{G}  Welcome to Hazel OS! {FACES['greeting']}{X}

  I'm Hazel, your local AI assistant.
  I run entirely on this machine - no cloud, no tracking.

  {D}System: {hostname} | {ram}GB RAM | Model: {model_name}{X}

  Try these:
    {G}status{X}                see how your system is doing
    {G}open browser{X}          launch an app
    {G}find <filename>{X}       search for files
    {G}explain what linux is{X} learn something new
    {G}tutorial pi{X}           interactive walkthrough
    {G}model{X}                 see available AI models
    {G}help{X}                  everything I can do
    {G}! <command>{X}           drop to bash anytime

  {D}Hotkey: Super+H opens Hazel from anywhere on the desktop.{X}
""")


def main():
    HAZEL_DIR.mkdir(exist_ok=True)

    if readline:
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

        if readline:
            readline.write_history_file(str(HISTORY_FILE))

        if user_input.lower() in ("exit", "quit", "bye", "q"):
            print(f"{D}bye! {get_face()}{X}")
            break

        if user_input.lower() in ("clear", "cls"):
            os.system("cls" if _IS_WINDOWS else "clear")
            banner()
            continue

        # Drop to full bash session
        if user_input.lower() in ("bash", "shell", "terminal"):
            print(f"{D}Dropping to bash. Type 'exit' to return to Hazel.{X}\n")
            subprocess.run(
                os.environ.get("SHELL", "/bin/bash"),
                stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
            )
            print(f"\n{G}Welcome back!{X}\n")
            continue

        # Raw bash (single command)
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

        # === Check if it's a file/folder name before LLM ===
        # If someone just types a word, check if it matches something on their machine
        if len(user_input.split()) <= 2 and not is_deep_query(user_input):
            home = Path.home()
            # Check folders first
            for d in home.iterdir():
                if d.is_dir() and d.name.lower() == user_input.lower():
                    result = open_file(str(d))
                    print(f"\n{B}  Opened folder: {d.name}/{X}\n")
                    remember("user", user_input)
                    remember("hazel", f"Opened folder {d.name}")
                    break
            else:
                # Check for file matches
                matches = find_file(user_input)
                if matches and len(matches) <= 5:
                    lines = [f"  Found {len(matches)} match(es) for '{user_input}':"]
                    for rel, size in matches[:5]:
                        lines.append(f"    ~/{rel}  ({format_size(size)})")
                    if len(matches) == 1:
                        full_path = home / matches[0][0]
                        open_file(str(full_path))
                        lines.append(f"\n  Opened: {matches[0][0]}")
                    else:
                        lines.append(f"\n  Say 'open <filename>' to open one.")
                    print(f"\n{B}" + "\n".join(lines) + f"{X}\n")
                    remember("user", user_input)
                    remember("hazel", f"Found files matching {user_input}")
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
