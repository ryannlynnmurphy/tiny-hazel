#!/bin/bash
# Set up Hazel in the taskbar panel

HAZEL_BIN="$HOME/.local/bin/hazel"
HAZEL_DIR="$HOME/hazel-os"

# 1. Install panel daemon service
echo "Setting up Hazel system monitor..."
mkdir -p "$HOME/.config/systemd/user"
cp "$HAZEL_DIR/hazel-panel.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable hazel-panel.service
systemctl --user start hazel-panel.service
echo "  OK: System monitor running"

# 2. Create Hazel desktop entry for panel launcher
echo "Adding Hazel to taskbar..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/hazel.desktop" << EOF
[Desktop Entry]
Name=Hazel
Comment=AI Assistant
Exec=x-terminal-emulator -e $HAZEL_BIN
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=System;
Keywords=ai;assistant;hazel;
EOF

# 3. Add Hazel to panel launchers if not already there
PANEL_CONF="$HOME/.config/wf-panel-pi.ini"
SYSTEM_CONF="/etc/xdg/wf-panel-pi/wf-panel-pi.ini"

# Copy system config if user config doesn't exist
if [ ! -f "$PANEL_CONF" ]; then
    mkdir -p "$(dirname "$PANEL_CONF")"
    if [ -f "$SYSTEM_CONF" ]; then
        cp "$SYSTEM_CONF" "$PANEL_CONF"
    fi
fi

if [ -f "$PANEL_CONF" ]; then
    # Check if hazel is already in launchers
    if ! grep -q "hazel" "$PANEL_CONF"; then
        # Add hazel to launchers line
        sed -i 's/^launchers=\(.*\)/launchers=hazel \1/' "$PANEL_CONF"
        echo "  OK: Hazel added to taskbar"
        echo "  Restart panel to see it: killall wf-panel-pi"
    else
        echo "  OK: Hazel already in taskbar"
    fi
else
    echo "  Panel config not found, skipping taskbar integration"
fi

# 4. Install notify-send if missing
if ! command -v notify-send &>/dev/null; then
    echo "Installing notification support..."
    sudo apt install -y libnotify-bin 2>/dev/null
fi

echo ""
echo "Done! Hazel is now in your taskbar."
echo "Restart the panel to see it: killall wf-panel-pi"
