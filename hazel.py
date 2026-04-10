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
from pathlib import Path
from datetime import datetime

# === CONFIG ===
HAZEL_DIR = Path.home() / ".hazel"
LLAMA_BIN = Path.home() / "llama.cpp" / "build" / "bin" / "llama-completion"
MODEL_PATH = Path.home() / "models" / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
HISTORY_FILE = HAZEL_DIR / "history"
PROMPT_FILE = HAZEL_DIR / "prompt.txt"
MAX_TOKENS = 120
MAX_TOKENS_DEEP = 300
TIMEOUT = 30
TIMEOUT_DEEP = 60

# Keywords that trigger deep thinking (more tokens, more time)
DEEP_KEYWORDS = [
    "explain", "why", "how does", "how do", "what is", "what are",
    "teach", "learn", "understand", "describe", "compare",
    "difference between", "help me understand", "tell me about",
    "write", "create", "build", "design", "plan",
    "debug", "fix", "solve", "troubleshoot", "diagnose",
    "analyze", "review", "evaluate",
]

# === COLORS ===
G = "\033[92m"   # green (hazel accent)
B = "\033[94m"   # blue (responses)
Y = "\033[93m"   # yellow (warnings)
R = "\033[91m"   # red (errors)
D = "\033[2m"    # dim
BD = "\033[1m"   # bold
X = "\033[0m"    # reset


# =============================================
# PART 1: SYSTEM READING (grounding layer)
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
    """Quick one-line system summary."""
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


# =============================================
# PART 2: INSTANT COMMANDS (no LLM needed)
# =============================================

def handle_instant(query):
    """
    Pattern-match common queries and answer instantly.
    Returns (response_string, ran_command) or None if no match.
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
        return "  Couldn't read temperature.", False

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
    if re.search(r"(ip|address|network|wifi|internet|online|connected)", q):
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
        return f"  {now.strftime('%A, %B %d, %Y at %I:%M %p')}", False

    # --- Help ---
    if q in ("help", "?", "commands"):
        return (
            f"  {BD}Hazel OS - What I can do{X}\n\n"
            f"  {G}Ask naturally:{X}\n"
            f"    \"how much disk space do I have?\"\n"
            f"    \"what's my IP address?\"\n"
            f"    \"show me running processes\"\n"
            f"    \"why is the system slow?\"\n"
            f"    \"explain what chmod does\"\n"
            f"    \"install htop\"\n\n"
            f"  {G}Quick commands:{X}\n"
            f"    status     System overview\n"
            f"    files      List home folders\n"
            f"    temp       CPU temperature\n"
            f"    top        Running processes\n\n"
            f"  {G}Power:{X}\n"
            f"    ! <cmd>    Run bash directly\n"
            f"    exit       Quit Hazel"
        ), False

    # --- Install package ---
    m = re.match(r"install\s+(\S+)", q)
    if m:
        pkg = m.group(1)
        return f"  To install {pkg}:\n  COMMAND: sudo apt install -y {pkg}", True

    # --- Update system ---
    if re.search(r"(update|upgrade).*(system|packages|apt|software)", q):
        return "  Updating package list and upgrading:\n  COMMAND: sudo apt update && sudo apt upgrade -y", True

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

    return None


# =============================================
# PART 3: LLM (for novel/complex queries)
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

    # For general queries, add overview
    if len(parts) <= 1:
        t = sys_temp()
        c = sys_cpu()
        m = sys_mem()
        parts.append(f"cpu={c['cpu_percent']}%")
        if t:
            parts.append(f"temp={t}C")
        parts.append(f"ram={m['ram_free_gb']}GB free")

    return ", ".join(parts)


def is_deep_query(query):
    """Check if query needs extended thinking."""
    q = query.lower()
    return any(kw in q for kw in DEEP_KEYWORDS)


def ask_llm(user_input, context):
    """Query TinyLlama. Only used for questions instant handler can't answer."""
    deep = is_deep_query(user_input)
    tokens = MAX_TOKENS_DEEP if deep else MAX_TOKENS
    timeout = TIMEOUT_DEEP if deep else TIMEOUT

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

    HAZEL_DIR.mkdir(exist_ok=True)
    PROMPT_FILE.write_text(prompt)

    cmd_str = (
        f'"{LLAMA_BIN}" '
        f'-m "{MODEL_PATH}" '
        f'-f "{PROMPT_FILE}" '
        f'-n {tokens} '
        f'-t 4 --temp 0.7 --top-p 0.9 --no-display-prompt '
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


# =============================================
# PART 4: COMMAND EXECUTION + SAFETY
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
    """Find COMMAND: lines in text."""
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
    """Run extracted commands with safety checks."""
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
# PART 5: MAIN INTERFACE
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


def main():
    HAZEL_DIR.mkdir(exist_ok=True)

    # History
    try:
        readline.read_history_file(str(HISTORY_FILE))
    except FileNotFoundError:
        pass
    readline.set_history_length(500)

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

        # === Try instant handler first (no LLM) ===
        instant = handle_instant(user_input)
        if instant is not None:
            response_text, has_commands = instant
            display, commands = extract_commands(response_text)
            if display:
                print(f"\n{B}{display}{X}")
            if commands:
                execute_commands(commands)
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

        print()


if __name__ == "__main__":
    main()
