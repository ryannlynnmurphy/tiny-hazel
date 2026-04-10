#!/bin/bash
# Hazel OS installer for Raspberry Pi
set -e

echo ""
echo "  Installing Hazel OS..."
echo "  ======================"
echo ""

HAZEL_HOME="$HOME/.hazel"
HAZEL_BIN="$HOME/hazel-os"

# Create directories
mkdir -p "$HAZEL_HOME"
mkdir -p "$HAZEL_BIN"

# Check dependencies
echo "  [1/4] Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "  ERROR: Python 3 not found"
    exit 1
fi

if ! python3 -c "import psutil" &>/dev/null; then
    echo "  Installing psutil..."
    pip3 install psutil --break-system-packages -q
fi

# Check llama.cpp
if [ ! -f "$HOME/llama.cpp/build/bin/llama-completion" ]; then
    echo "  ERROR: llama.cpp not compiled. Run:"
    echo "    cd ~ && git clone https://github.com/ggerganov/llama.cpp"
    echo "    cd llama.cpp && cmake -B build -DLLAMA_NATIVE=ON"
    echo "    cmake --build build --config Release -j4"
    exit 1
fi
echo "  OK: llama.cpp found"

# Check model
if [ ! -f "$HOME/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" ]; then
    echo "  Downloading TinyLlama model (638MB)..."
    mkdir -p "$HOME/models"
    wget -q --show-progress \
        "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
        -O "$HOME/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
fi
echo "  OK: TinyLlama model found"

# Install Hazel
echo ""
echo "  [2/4] Installing Hazel shell..."
chmod +x "$HAZEL_BIN/hazel.py"

# Create launcher script
cat > "$HOME/.local/bin/hazel" << 'EOF'
#!/bin/bash
exec python3 "$HOME/hazel-os/hazel.py" "$@"
EOF
mkdir -p "$HOME/.local/bin"
chmod +x "$HOME/.local/bin/hazel"

# Add to PATH if needed
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi

# Copy config if not exists
if [ ! -f "$HAZEL_BIN/config.yaml" ]; then
    echo "  Config file not found, this is expected on first install"
fi

echo "  OK: 'hazel' command installed"

# Desktop shortcut
echo ""
echo "  [3/4] Creating desktop shortcut..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/hazel.desktop" << EOF
[Desktop Entry]
Name=Hazel OS
Comment=AI-powered natural language shell
Exec=lxterminal -e "$HOME/.local/bin/hazel"
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=System;TerminalEmulator;
Keywords=ai;assistant;shell;hazel;
EOF

# Also put on desktop
if [ -d "$HOME/Desktop" ]; then
    cp "$HOME/.local/share/applications/hazel.desktop" "$HOME/Desktop/"
    chmod +x "$HOME/Desktop/hazel.desktop"
fi

echo "  OK: Desktop shortcut created"

# Auto-start option
echo ""
echo "  [4/4] Setting up auto-start..."
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/hazel-welcome.desktop" << EOF
[Desktop Entry]
Name=Hazel Welcome
Exec=lxterminal -e "$HOME/.local/bin/hazel"
Type=Application
X-GNOME-Autostart-enabled=true
Comment=Start Hazel OS on login
EOF

echo "  OK: Hazel will start on login"

# Global hotkey (Super+H)
echo ""
echo "  [5/5] Setting up global hotkey..."
python3 "$HAZEL_BIN/hazel-hotkey.py" 2>/dev/null || echo "  Hotkey setup skipped (configure manually)"

echo ""
echo "  =============================="
echo "  Hazel OS installed!"
echo ""
echo "  Start now:     hazel"
echo "  Hotkey:        Super+H (from anywhere)"
echo "  Config:        ~/hazel-os/config.yaml"
echo "  Desktop icon:  On your desktop"
echo ""
echo "  Optional: Download smarter model (2.3GB):"
echo "    hazel, then type: download phi3"
echo "  =============================="
echo ""
