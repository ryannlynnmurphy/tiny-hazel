#!/usr/bin/env python3
"""
Hazel OS - A Raspberry Pi that speaks your language.
Local LLM shell powered by TinyLlama.
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
from pathlib import Path

# === CONFIG ===
HAZEL_DIR = Path.home() / ".hazel"
LLAMA_BIN = Path.home() / "llama.cpp" / "build" / "bin" / "llama-completion"
MODEL_PATH = Path.home() / "models" / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
HISTORY_FILE = HAZEL_DIR / "history"
MAX_RESPONSE_TOKENS = 80
TIMEOUT = 45

# Colors
C = {
    "g": "\033[92m",  # green
    "b": "\033[94m",  # blue
    "y": "\033[93m",  # yellow
    "r": "\033[91m",  # red
    "d": "\033[2m",   # dim
    "B": "\033[1m",   # bold
    "x": "\033[0m",   # reset
}

# Dangerous command patterns
DANGEROUS = [
    r"rm\s+(-\w*[rf]|--recursive|--force)",
    r"\bmkfs\b", r"\bdd\b\s.*of=", r"\bshutdown\b",
    r"\breboot\b", r"\bsudo\s+rm\b", r"\bfdisk\b",
    r">\s*/dev/", r"\bchmod\s+777\b",
]


# === SYSTEM READING ===

def read_cpu():
    pct = psutil.cpu_percent(interval=0.3)
    try:
        r = subprocess.run(["vcgencmd", "measure_temp"],
                          capture_output=True, text=True, timeout=2)
        temp = r.stdout.strip().split("=")[1].split("'")[0]
    except Exception:
        temp = "?"
    return f"cpu={pct}% temp={temp}C cores={psutil.cpu_count()}"


def read_mem():
    m = psutil.virtual_memory()
    return f"ram={round(m.available/1e9,1)}GB free of {round(m.total/1e9,1)}GB ({m.percent}% used)"


def read_disk():
    d = psutil.disk_usage("/")
    return f"disk={round(d.free/1e9,1)}GB free of {round(d.total/1e9,1)}GB ({round(d.percent)}% used)"


def read_net():
    parts = []
    for iface, addrs in psutil.net_if_addrs().items():
        if iface == "lo":
            continue
        for a in addrs:
            if a.family == socket.AF_INET:
                parts.append(f"{iface}={a.address}")
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        parts.append("internet=yes")
    except OSError:
        parts.append("internet=no")
    return " ".join(parts) if parts else "no network"


def read_procs():
    procs = sorted(
        psutil.process_iter(["name", "cpu_percent"]),
        key=lambda p: p.info.get("cpu_percent") or 0,
        reverse=True,
    )[:3]
    return " ".join(
        f"{p.info['name']}={p.info.get('cpu_percent',0)}%"
        for p in procs
    )


def read_dirs():
    home = Path.home()
    dirs = sorted([
        d.name for d in home.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])
    return "folders: " + ", ".join(dirs[:10])


def read_uptime():
    s = time.time() - psutil.boot_time()
    h, m = int(s // 3600), int((s % 3600) // 60)
    return f"uptime={h}h{m}m"


def get_context(query):
    """Build minimal context string based on query topic."""
    q = query.lower()
    parts = [f"host={socket.gethostname()}"]

    if any(w in q for w in ["cpu", "slow", "fast", "hot", "temp", "warm", "performance", "speed"]):
        parts.append(read_cpu())
        parts.append(read_procs())
    elif any(w in q for w in ["mem", "ram", "swap"]):
        parts.append(read_mem())
    elif any(w in q for w in ["disk", "storage", "space", "full"]):
        parts.append(read_disk())
    elif any(w in q for w in ["net", "wifi", "internet", "ip", "connect", "online"]):
        parts.append(read_net())
    elif any(w in q for w in ["file", "folder", "dir", "document", "show", "list"]):
        parts.append(read_dirs())
        parts.append(read_disk())
    elif any(w in q for w in ["process", "running", "kill", "what", "app"]):
        parts.append(read_procs())
        parts.append(read_cpu())
        parts.append(read_mem())
    elif any(w in q for w in ["uptime", "boot", "long", "when"]):
        parts.append(read_uptime())
    else:
        # General query - give overview
        parts.append(read_cpu())
        parts.append(read_mem())
        parts.append(read_disk())

    return ". ".join(parts)


# === LLM ===

def ask_llm(user_input, context):
    """Query TinyLlama with grounded context."""
    prompt = (
        "<|system|>\n"
        "You are Hazel, a friendly AI assistant running on a Raspberry Pi 5. "
        "Answer using ONLY the facts below. Never invent hardware specs. Be concise.\n"
        f"{context}</s>\n"
        f"<|user|>\n{user_input}</s>\n"
        "<|assistant|>\n"
    )

    # Write prompt to file (avoids shell escaping issues with -p)
    prompt_file = HAZEL_DIR / "prompt.txt"
    prompt_file.write_text(prompt)

    try:
        # Use shell=True with explicit command string to avoid argument issues
        cmd_str = (
            f'"{LLAMA_BIN}" '
            f'-m "{MODEL_PATH}" '
            f'-f "{prompt_file}" '
            f'-n {MAX_RESPONSE_TOKENS} '
            f'-t 4 --temp 0.7 --top-p 0.9 --no-display-prompt '
            f'2>/dev/null'
        )
        result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
        text = result.stdout.strip()
        # Cut at any special token
        for tok in ["</s>", "<|user|>", "<|assistant|>", "<|system|>", "> EOF"]:
            text = text.split(tok)[0]
        if not text and result.stderr:
            return f"[llm stderr: {result.stderr[:200]}]"
        return text.strip()
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        return f"[error: {e}]"


# === COMMAND HANDLING ===

def extract_commands(text):
    """Find COMMAND: lines in LLM response."""
    cmds = []
    clean_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("COMMAND:"):
            cmd = stripped[8:].strip().strip("`").strip()
            if cmd:
                cmds.append(cmd)
        else:
            clean_lines.append(line)
    return "\n".join(clean_lines).strip(), cmds


def is_dangerous(cmd):
    """Check if command could be destructive."""
    for pat in DANGEROUS:
        if re.search(pat, cmd):
            return True
    return False


def run_command(cmd):
    """Execute a shell command safely."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.returncode != 0 and result.stderr:
            output += f"\n{C['r']}{result.stderr}{C['x']}"
        return output.strip() if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return f"{C['r']}Command timed out after 30s{C['x']}"


# === UI ===

def banner():
    state = {
        "cpu": read_cpu(),
        "mem": read_mem(),
        "disk": read_disk(),
    }
    # Parse quick stats
    try:
        temp = re.search(r"temp=(\S+)", state["cpu"]).group(1)
        cpu_pct = re.search(r"cpu=(\S+)", state["cpu"]).group(1)
        ram_free = re.search(r"ram=(\S+)", state["mem"]).group(1)
        disk_free = re.search(r"disk=(\S+)", state["disk"]).group(1)
    except Exception:
        temp = cpu_pct = ram_free = disk_free = "?"

    hostname = socket.gethostname()

    print(f"""
{C['B']}{C['g']}  _   _               _
 | | | | __ _ ______| |
 | |_| |/ _` |_  / _` |
 |  _  | (_| |/ /  __/ |
 |_| |_|\\__,_/___\\___|_|{C['x']}

 {C['d']}Hazel OS on {hostname}
 CPU {cpu_pct} | {temp} | RAM {ram_free} free | Disk {disk_free} free
 Type naturally. ! for bash. exit to quit.{C['x']}
""")


def main():
    # Setup
    HAZEL_DIR.mkdir(exist_ok=True)

    # Command history
    try:
        readline.read_history_file(str(HISTORY_FILE))
    except FileNotFoundError:
        pass
    readline.set_history_length(500)

    banner()

    while True:
        try:
            user_input = input(f"{C['g']}hazel> {C['x']}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C['d']}bye!{C['x']}")
            break

        if not user_input:
            continue

        # Save history
        readline.write_history_file(str(HISTORY_FILE))

        if user_input.lower() in ("exit", "quit", "bye", "q"):
            print(f"{C['d']}bye!{C['x']}")
            break

        # Status shortcut
        if user_input.lower() in ("status", "stats"):
            print(f"  {read_cpu()}")
            print(f"  {read_mem()}")
            print(f"  {read_disk()}")
            print(f"  {read_net()}")
            print(f"  {read_uptime()}")
            print()
            continue

        # Help
        if user_input.lower() in ("help", "?"):
            print(f"""
  {C['B']}Hazel OS Commands{C['x']}
  {C['d']}Ask anything in natural language:{C['x']}
    "how much disk space do I have?"
    "what is my IP address?"
    "explain what chmod does"
    "why is the system slow?"

  {C['B']}Shortcuts:{C['x']}
    {C['g']}!{C['x']} <cmd>     Run bash command directly
    {C['g']}status{C['x']}      Quick system overview
    {C['g']}help{C['x']}        This message
    {C['g']}exit{C['x']}        Quit Hazel
""")
            continue

        # Raw bash
        if user_input.startswith("!"):
            cmd = user_input[1:].strip()
            if cmd:
                print(run_command(cmd))
                print()
            continue

        # === AI Query ===
        sys.stdout.write(f"{C['d']}thinking...{C['x']}")
        sys.stdout.flush()

        # Read system state
        context = get_context(user_input)

        # Ask LLM
        start = time.time()
        response = ask_llm(user_input, context)
        elapsed = time.time() - start

        # Debug: show what happened if timeout
        if response is None:
            print(f"\r{C['d']}debug: context={len(context)} chars, query='{user_input}'{C['x']}")
            print(f"{C['d']}debug: context was: {context[:200]}{C['x']}")

        # Clear "thinking"
        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()

        if response is None:
            print(f"{C['y']}Took too long. Try something simpler.{C['x']}\n")
            continue

        # Parse commands from response
        display_text, commands = extract_commands(response)

        # Show response
        if display_text:
            print(f"{C['b']}{display_text}{C['x']}")
        print(f"{C['d']}({elapsed:.1f}s){C['x']}")

        # Handle extracted commands
        for cmd in commands:
            print()
            if is_dangerous(cmd):
                print(f"  {C['y']}{C['B']}warning:{C['x']} {C['y']}{cmd}{C['x']}")
                try:
                    confirm = input(f"  {C['y']}run this? (yes/no): {C['x']}").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print(f"\n  {C['d']}cancelled{C['x']}")
                    continue
                if confirm != "yes":
                    print(f"  {C['d']}cancelled{C['x']}")
                    continue
            else:
                print(f"  {C['d']}$ {cmd}{C['x']}")

            output = run_command(cmd)
            if output:
                # Indent command output
                for line in output.split("\n")[:20]:
                    print(f"  {line}")
                if len(output.split("\n")) > 20:
                    print(f"  {C['d']}... ({len(output.split(chr(10)))} lines total){C['x']}")

        print()


if __name__ == "__main__":
    main()
