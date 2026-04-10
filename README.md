# Hazel

**Your computer, in your language.**

Local AI terminal assistant powered by TinyLlama. No cloud. No telemetry. Yours.

Runs on: Linux, macOS, Raspberry Pi, WSL.

## Install (one line)

```bash
curl -sSL https://raw.githubusercontent.com/ryannlynnmurphy/tiny-hazel/main/install-universal.sh | bash
```

## What it does

Hazel is a natural language interface to your computer. Instead of memorizing terminal commands, just ask.

```
hazel> how much disk space do I have?
You have 111GB free out of 125GB on your SD card.

hazel> open browser
Launched Chromium.

hazel> find readme
Found 3 file(s) matching 'readme':
  ~/hazel-os/README.md  (2.1KB)
  ~/projects/README.md  (890B)

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
2. **Instant handler** checks if it can answer immediately (system stats, file ops, app launching)
3. **If not**, TinyLlama (1.1B parameter LLM running locally) generates a response
4. **System grounding** - Hazel reads actual system state before answering, preventing hallucination
5. **Safety layer** catches dangerous commands and asks for confirmation

```
User query
    |
    v
[Instant handler] --match--> Answer immediately (0ms)
    |
    no match
    |
    v
[Read system state] --> [TinyLlama interprets] --> Answer (5-8s)
```

## Requirements

- Any Linux, macOS, Raspberry Pi, or WSL
- 2GB+ RAM (4GB recommended)
- 1GB free disk space (for model)
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
| `model` | Show installed models |
| `download phi3` | Download smarter model (2.3GB) |

### Power User
| Command | What it does |
|---------|-------------|
| `! <cmd>` | Run bash command directly |
| `help` | Show all commands |
| `exit` | Quit Hazel |

## Architecture

```
hazel.py (~600 lines of Python)
    |
    ├── System Reading    - psutil, /proc, vcgencmd
    ├── File Operations   - find, grep, xdg-open
    ├── App Launching     - .desktop file discovery
    ├── Instant Handler   - pattern matching (0ms)
    ├── Humanizer         - raw data → natural language
    ├── LLM Interface     - TinyLlama via llama.cpp
    ├── Safety Layer      - destructive command detection
    └── Conversation Memory - session context
```

**Model:** TinyLlama-1.1B-Chat (Q4_K_M quantization, 638MB)
**Inference:** llama.cpp compiled natively for ARM
**Performance:** 16.5 tokens/sec on Pi 5

## Philosophy

- **Local-first**: Everything runs on your Pi. No cloud services required.
- **Grounded**: Hazel reads actual system state before answering. No hallucinated specs.
- **Honest**: When Hazel doesn't know, she says so. When a command is dangerous, she warns you.
- **Simple**: One Python file. No frameworks. No dependencies beyond psutil and llama.cpp.
- **Open**: MIT license. Fork it, modify it, make it yours.

## License

MIT

## Author

Ryann Murphy ([@ryannlynnmurphy](https://github.com/ryannlynnmurphy))

Built with TinyLlama and llama.cpp.
