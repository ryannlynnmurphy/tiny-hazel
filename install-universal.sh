#!/bin/bash
# Hazel - Local AI terminal assistant
# Works on: Linux (any), macOS, Raspberry Pi, WSL
set -e

echo ""
echo "  Installing Hazel..."
echo "  ==================="
echo ""

HAZEL_DIR="$HOME/hazel-os"
MODEL_DIR="$HOME/models"
BIN_DIR="$HOME/.local/bin"

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

echo "  Platform: $OS $ARCH"

# === 1. Dependencies ===
echo "  [1/4] Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "  ERROR: Python 3 required. Install it first."
    exit 1
fi
echo "  OK: Python 3"

if ! python3 -c "import psutil" &>/dev/null; then
    echo "  Installing psutil..."
    pip3 install psutil --break-system-packages -q 2>/dev/null || pip3 install psutil -q
fi
echo "  OK: psutil"

if ! command -v cmake &>/dev/null || ! command -v git &>/dev/null; then
    echo "  Installing build tools..."
    if [ "$OS" = "Darwin" ]; then
        brew install cmake git 2>/dev/null || echo "  Install Xcode CLI tools: xcode-select --install"
    elif command -v apt &>/dev/null; then
        sudo apt install -y build-essential cmake git -qq
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y cmake gcc-c++ git -q
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm cmake base-devel git
    fi
fi
echo "  OK: Build tools"

# === 2. llama.cpp ===
echo ""
echo "  [2/4] Building llama.cpp..."

if [ ! -f "$HOME/llama.cpp/build/bin/llama-completion" ]; then
    cd "$HOME"
    if [ ! -d "llama.cpp" ]; then
        git clone --depth 1 https://github.com/ggerganov/llama.cpp
    fi
    cd llama.cpp

    # Detect GPU support
    CMAKE_ARGS="-DLLAMA_NATIVE=ON"
    if [ "$OS" = "Darwin" ]; then
        CMAKE_ARGS="$CMAKE_ARGS -DLLAMA_METAL=ON"
        echo "  Metal GPU acceleration enabled"
    fi

    cmake -B build $CMAKE_ARGS
    CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)
    cmake --build build --config Release -j"$CORES"
    echo "  OK: llama.cpp compiled"
else
    echo "  OK: llama.cpp already built"
fi

# === 3. Model ===
echo ""
echo "  [3/4] Downloading TinyLlama (638MB)..."

mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_DIR/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" ]; then
    wget -q --show-progress \
        "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
        -O "$MODEL_DIR/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
    || curl -L --progress-bar \
        "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" \
        -o "$MODEL_DIR/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    echo "  OK: TinyLlama downloaded"
else
    echo "  OK: TinyLlama already downloaded"
fi

# === 4. Install Hazel ===
echo ""
echo "  [4/4] Installing Hazel..."

# Clone or update repo
if [ ! -d "$HAZEL_DIR" ]; then
    git clone https://github.com/ryannlynnmurphy/tiny-hazel.git "$HAZEL_DIR"
else
    cd "$HAZEL_DIR" && git pull -q 2>/dev/null || true
fi

chmod +x "$HAZEL_DIR/hazel.py"

# Create launcher
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/hazel" << EOF
#!/bin/bash
exec python3 "$HAZEL_DIR/hazel.py" "\$@"
EOF
chmod +x "$BIN_DIR/hazel"

# Add to PATH
if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    SHELL_RC="$HOME/.bashrc"
    [ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
    echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$SHELL_RC"
    export PATH="$BIN_DIR:$PATH"
fi

# Pi-specific extras (skip on other platforms)
if [ -f /proc/device-tree/model ] && grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "  Raspberry Pi detected - setting up extras..."
    # Desktop shortcut
    if [ -d "$HOME/Desktop" ]; then
        cat > "$HOME/Desktop/hazel.desktop" << DESK
[Desktop Entry]
Name=Hazel
Comment=AI Assistant
Exec=x-terminal-emulator -e $BIN_DIR/hazel
Icon=utilities-terminal
Terminal=false
Type=Application
DESK
        chmod +x "$HOME/Desktop/hazel.desktop"
    fi
    # Hotkey
    python3 "$HAZEL_DIR/hazel-hotkey.py" 2>/dev/null || true
fi

echo ""
echo "  ========================"
echo "  Hazel installed!"
echo ""
echo "  Run:  hazel"
echo ""
echo "  (Open a new terminal if 'hazel' isn't found)"
echo "  ========================"
echo ""
