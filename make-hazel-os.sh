#!/bin/bash
# ===========================================
# make-hazel-os.sh
# Transforms stock Raspberry Pi OS into Hazel OS
# Run once on a fresh Pi, reboot, and you're in Hazel OS
# ===========================================
set -e

echo ""
echo "  ╦ ╦╔═╗╔═╗╔═╗╦"
echo "  ╠═╣╠═╣╔═╝║╣ ║"
echo "  ╩ ╩╩ ╩╚═╝╚═╝╩═╝  OS Installer"
echo ""
echo "  This will transform your Raspberry Pi into Hazel OS."
echo "  Takes about 15 minutes. Your files are safe."
echo ""
read -p "  Continue? (y/n): " confirm
if [ "$confirm" != "y" ]; then
    echo "  Cancelled."
    exit 0
fi

HAZEL_DIR="$HOME/hazel-os"
MODEL_DIR="$HOME/models"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config"

echo ""
echo "  [1/8] Installing system packages..."
sudo apt update -qq
sudo apt install -y -qq \
    build-essential cmake git \
    libnotify-bin dunst \
    python3-psutil \
    fonts-noto \
    2>/dev/null

echo "  [2/8] Building llama.cpp..."
if [ ! -f "$HOME/llama.cpp/build/bin/llama-completion" ]; then
    cd "$HOME"
    [ ! -d "llama.cpp" ] && git clone --depth 1 https://github.com/ggerganov/llama.cpp
    cd llama.cpp
    cmake -B build -DLLAMA_NATIVE=ON -DCMAKE_BUILD_TYPE=Release 2>/dev/null
    cmake --build build --config Release -j4 2>&1 | tail -1
fi
echo "  OK"

echo "  [3/8] Downloading AI model..."
mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_DIR/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" ]; then
    wget -q --show-progress \
        "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
        -O "$MODEL_DIR/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
fi
echo "  OK"

echo "  [4/8] Installing Hazel..."
cd "$HOME"
if [ ! -d "$HAZEL_DIR/.git" ]; then
    git clone https://github.com/ryannlynnmurphy/tiny-hazel.git "$HAZEL_DIR"
else
    cd "$HAZEL_DIR" && git pull -q
fi

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/hazel" << 'LAUNCHER'
#!/bin/bash
exec python3 "$HOME/hazel-os/hazel.py" "$@"
LAUNCHER
chmod +x "$BIN_DIR/hazel"

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi
echo "  OK"

echo "  [5/8] Setting up desktop..."

# Desktop shortcut
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/hazel.desktop" << EOF
[Desktop Entry]
Name=Hazel
Comment=AI Assistant - Your computer in your language
Exec=x-terminal-emulator -e $BIN_DIR/hazel
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=System;
Keywords=ai;assistant;hazel;
StartupNotify=true
EOF

# Desktop icon
if [ -d "$HOME/Desktop" ]; then
    cp "$HOME/.local/share/applications/hazel.desktop" "$HOME/Desktop/"
    chmod +x "$HOME/Desktop/hazel.desktop"
fi

# Add to panel launchers
PANEL_SYS="/etc/xdg/wf-panel-pi/wf-panel-pi.ini"
PANEL_USER="$CONFIG_DIR/wf-panel-pi.ini"
if [ ! -f "$PANEL_USER" ] && [ -f "$PANEL_SYS" ]; then
    mkdir -p "$CONFIG_DIR"
    cp "$PANEL_SYS" "$PANEL_USER"
fi
if [ -f "$PANEL_USER" ] && ! grep -q "hazel" "$PANEL_USER"; then
    sed -i 's/^launchers=\(.*\)/launchers=hazel \1/' "$PANEL_USER"
fi
echo "  OK"

echo "  [6/8] Setting up global hotkey (Super+H)..."
# Copy labwc config
LABWC_SYS="/etc/xdg/labwc/rc.xml"
LABWC_USER="$CONFIG_DIR/labwc/rc.xml"
if [ ! -f "$LABWC_USER" ] && [ -f "$LABWC_SYS" ]; then
    mkdir -p "$CONFIG_DIR/labwc"
    cp "$LABWC_SYS" "$LABWC_USER"
fi
if [ -f "$LABWC_USER" ] && ! grep -q "hazel" "$LABWC_USER"; then
    sed -i "s|</keyboard>|    <keybind key=\"Super_L-h\">\n      <action name=\"Execute\" command=\"x-terminal-emulator -e $BIN_DIR/hazel\" />\n    </keybind>\n  </keyboard>|" "$LABWC_USER"
fi
echo "  OK"

echo "  [7/8] Setting up auto-start and notifications..."

# Auto-start Hazel on login
mkdir -p "$CONFIG_DIR/autostart"
cat > "$CONFIG_DIR/autostart/hazel.desktop" << EOF
[Desktop Entry]
Name=Hazel
Exec=x-terminal-emulator -e $BIN_DIR/hazel
Type=Application
X-GNOME-Autostart-enabled=true
EOF

# System monitor daemon
mkdir -p "$CONFIG_DIR/systemd/user"
cat > "$CONFIG_DIR/systemd/user/hazel-monitor.service" << EOF
[Unit]
Description=Hazel System Monitor
After=graphical.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $HAZEL_DIR/hazel-panel.py
Restart=on-failure
RestartSec=10
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload 2>/dev/null
systemctl --user enable hazel-monitor.service 2>/dev/null
systemctl --user start hazel-monitor.service 2>/dev/null
echo "  OK"

echo "  [8/8] Customizing desktop appearance..."

# Set terminal to open Hazel by default
# Create custom terminal profile that runs Hazel
mkdir -p "$CONFIG_DIR/lxterminal"
cat > "$CONFIG_DIR/lxterminal/lxterminal.conf" << 'EOF'
[general]
fontname=Monospace 11
selchars=-A-Za-z0-9,./?%&#:_
scrollback=1000
bgcolor=rgb(25,25,30)
fgcolor=rgb(200,210,200)
palette_color_0=rgb(25,25,30)
palette_color_1=rgb(204,102,102)
palette_color_2=rgb(152,195,121)
palette_color_3=rgb(229,192,123)
palette_color_4=rgb(97,175,239)
palette_color_5=rgb(198,120,221)
palette_color_6=rgb(86,182,194)
palette_color_7=rgb(200,210,200)
palette_color_8=rgb(92,99,112)
palette_color_9=rgb(224,108,117)
palette_color_10=rgb(152,195,121)
palette_color_11=rgb(229,192,123)
palette_color_12=rgb(97,175,239)
palette_color_13=rgb(198,120,221)
palette_color_14=rgb(86,182,194)
palette_color_15=rgb(255,255,255)
disallowbold=false
cursorblinks=true
cursorunderline=false
audiblebell=false
tabpos=top
hidescrollbar=true
hidemenubar=true
hideclosebutton=false
disablef10=false
disablealt=false
EOF

# Set desktop wallpaper to dark
PCMANFM_CONF="$CONFIG_DIR/pcmanfm/LXDE-pi/desktop-items-0.conf"
if [ -f "$PCMANFM_CONF" ]; then
    sed -i 's/^desktop_bg=.*/desktop_bg=#191920/' "$PCMANFM_CONF" 2>/dev/null
    sed -i 's/^desktop_fg=.*/desktop_fg=#c8d2c8/' "$PCMANFM_CONF" 2>/dev/null
fi

# Create a simple welcome wallpaper message
cat > "$HOME/Desktop/WELCOME.txt" << 'EOF'
Welcome to Hazel OS!

Press Super+H anywhere to open Hazel.
Or click the Hazel icon in the taskbar.

Hazel is your AI assistant. Ask her anything:
  - "status" to check your system
  - "explain what linux is" to learn
  - "open browser" to launch apps
  - "help" for all commands

Everything runs locally. No cloud. No tracking. Yours.
EOF

echo "  OK"

# Clear failed services
sudo systemctl reset-failed 2>/dev/null
sudo systemctl disable NetworkManager-wait-online.service 2>/dev/null

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║                                      ║"
echo "  ║    Hazel OS installed!   (^_^)       ║"
echo "  ║                                      ║"
echo "  ║    Reboot to start fresh:            ║"
echo "  ║      sudo reboot                     ║"
echo "  ║                                      ║"
echo "  ║    Or start now:                     ║"
echo "  ║      hazel                           ║"
echo "  ║                                      ║"
echo "  ║    Hotkey: Super+H from anywhere     ║"
echo "  ║                                      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
