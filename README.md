# Hazel

**Your computer, in your language.**

Local AI assistant with tool use. No cloud. No telemetry. Yours.

Runs on: Linux, macOS, Windows, Raspberry Pi, WSL.

## Install (one line)

```bash
curl -sSL https://raw.githubusercontent.com/ryannlynnmurphy/tiny-hazel/main/install-universal.sh | bash
```

## What it does

Hazel is a natural language interface to your computer. Instead of memorizing terminal commands, just ask. She can search your files, read them, check your system, and run commands — not just talk about doing it.

```
hazel> how much disk space do I have?
You have 111GB free out of 125GB on your SD card.

hazel> do I have anything called scouts?
Found 3 file(s) matching 'scouts':
  ~/projects/SCOUTS-remix.fountain  (14.2KB)
  ~/Documents/scouts-notes.md  (890B)

hazel> open browser
Launched Chromium.

hazel> explain what chmod does
chmod changes file permissions on Linux. Think of it like setting
who can read, write, or run a file...
(8.2s)

hazel> install htop
  $ sudo apt install -y htop
  [installs package]
```

## How it works

1. **You ask a question** in plain English
2. **Instant handler** checks 40+ patterns and answers immediately (system stats, file ops, app launching)
3. **If not**, the LLM decides what to do — answer directly or use tools
4. **Tool system** lets the model search files, read contents, check system state, and run commands
5. **Two-pass agent loop** — model calls tools, gets real results, then responds naturally
6. **Safety layer** catches dangerous commands and asks for confirmation

```
User query
    |
    v
[Instant handler] --match--> Answer immediately (0ms)
    |
    no match
    |
    v
[LLM + Tools] --needs data--> [execute tools] --> [LLM responds with results]
    |
    no tools needed
    |
    v
[Direct response] (5-12s)
```

### Three-tier model routing

Hazel auto-selects the best model for each task based on your hardware:

| Tier | Role | Default model |
|------|------|--------------|
| Tier 1 | Humanizing raw data | TinyLlama 1.1B |
| Tier 2 | Normal questions + tool use | Phi-3 3.8B |
| Tier 3 | Deep reasoning | Mistral 7B / Llama 3 8B |

### Tools available to the LLM

| Tool | What it does |
|------|-------------|
| `find_file` | Search for files by name |
| `search_contents` | Search inside file contents |
| `system_info` | Get CPU, RAM, disk, temperature |
| `list_folders` | List home directory folders |
| `read_file` | Read a file's contents |
| `run_command` | Run a shell command |

## Requirements

- Any Linux, macOS, Windows, Raspberry Pi, or WSL
- 2GB+ RAM (4GB recommended, 8GB+ for larger models)
- 1GB free disk space (for base model, more for additional models)
- Python 3.8+

Works great on: laptops, desktops, Raspberry Pi 4/5, cloud VMs, old Thinkpads.

## Install

**One-liner (recommended):**
```bash
curl -sSL https://raw.githubusercontent.com/ryannlynnmurphy/tiny-hazel/main/install-universal.sh | bash
```

**Manual:**
```bash
git clone https://github.com/ryannlynnmurphy/tiny-hazel.git ~/hazel-os
cd ~/hazel-os
chmod +x install-universal.sh
./install-universal.sh
```

**Run:**
```bash
hazel
```

## Commands

### System
| Command | What it does |
|---------|-------------|
| `status` | Full system overview |
| `temp` | CPU temperature |
| `cpu` | CPU usage |
| `memory` | RAM usage |
| `disk` | Disk space |
| `gpu` | GPU info (NVIDIA, AMD, Metal, VideoCore) |
| `network` | IP addresses, internet status |
| `hardware` | Full hardware specs |
| `uptime` | How long since boot |
| `top` | Running processes |
| `usb` | Connected USB devices |
| `errors` | Failed system services |

### Files
| Command | What it does |
|---------|-------------|
| `files` | List home folders |
| `find <name>` | Search for files by name |
| `search for <term>` | Search file contents |
| `open <file>` | Open file with default app |

### Apps
| Command | What it does |
|---------|-------------|
| `open browser` | Launch Chromium |
| `open editor` | Launch text editor |
| `open terminal` | New terminal window |
| `open files` | File manager |
| `open writer` | LibreOffice Writer |
| `close <app>` | Kill an application |

### System Control
| Command | What it does |
|---------|-------------|
| `install <pkg>` | Install apt package |
| `remove <pkg>` | Remove apt package |
| `update system` | apt update + upgrade |
| `volume <0-100>` | Set system volume |
| `reboot` | Restart Pi |
| `shutdown` | Power off |

### AI Queries
Ask anything naturally. Keywords like `explain`, `why`, `how does`, `write`, `debug` trigger deep thinking mode with longer, more thorough responses.

```
hazel> explain how wifi works
hazel> why is my system slow
hazel> write a python script to rename files
hazel> what is the difference between TCP and UDP
```

### Learn
| Command | What it does |
|---------|-------------|
| `tutorial` | List available tutorials |
| `tutorial permissions` | Learn file permissions (chmod) |
| `tutorial files` | Learn to find files |
| `tutorial processes` | Learn process management |
| `tutorial networking` | Learn networking basics |
| `tutorial gpio` | Learn Raspberry Pi GPIO |
| `tutorial pi` | Explore your Pi hardware |
| `teach me <topic>` | Same as tutorial |

### Config
| Command | What it does |
|---------|-------------|
| `config` | Show current settings |
| `model` | Show installed models and routing |
| `download phi3` | Download Phi-3 3.8B (2.3GB) |
| `download mistral` | Download Mistral 7B (4.1GB) |
| `download llama3` | Download Llama 3.1 8B (4.9GB) |
| `download deepseek` | Download DeepSeek R1 8B (4.9GB) |
| `download qwen` | Download Qwen 2.5 7B (4.4GB) |
| `profile` | Show what Hazel knows about you |
| `scan profile` | Rescan machine to learn about you |

### Power User
| Command | What it does |
|---------|-------------|
| `! <cmd>` | Run bash command directly |
| `help` | Show all commands |
| `exit` | Quit Hazel |

## Architecture

```
hazel.py
    |
    ├── System Reading     - psutil, /proc, vcgencmd, nvidia-smi
    ├── File Operations    - find, grep, xdg-open
    ├── App Launching      - .desktop file discovery
    ├── Instant Handler    - 40+ pattern matches (0ms)
    ├── Tool System        - 6 tools the LLM can call
    ├── Agent Loop         - two-pass: tools → results → response
    ├── Humanizer          - raw data → natural language (Tier 1)
    ├── LLM Interface      - llama.cpp, three-tier model routing
    ├── Safety Layer       - destructive command detection
    └── Conversation Memory - session context + persistent notes

hazel-gui.py
    |
    └── Web GUI            - Flask app, animated face, chat interface
```

**Models:** TinyLlama 1.1B / Phi-3 3.8B / Mistral 7B (Q4_K_M quantization)
**Inference:** llama.cpp (CPU or GPU-accelerated via Vulkan/Metal/CUDA)
**GPU support:** NVIDIA, AMD, Intel Arc, Apple Silicon, Raspberry Pi VideoCore

## Philosophy

- **Local-first**: Everything runs on your machine. No cloud services required.
- **Agentic**: Hazel uses tools to find real answers, not hallucinate them.
- **Grounded**: Reads actual system state before answering. No made-up specs.
- **Honest**: When Hazel doesn't know, she says so. When a command is dangerous, she warns you.
- **Simple**: Two Python files. No heavy frameworks. psutil + llama.cpp + Flask for the GUI.
- **Open**: MIT license. Fork it, modify it, make it yours.

## License

MIT

## Author

Ryann Murphy ([@ryannlynnmurphy](https://github.com/ryannlynnmurphy))

Built with TinyLlama and llama.cpp.
