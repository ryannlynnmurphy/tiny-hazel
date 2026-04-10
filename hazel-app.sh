#!/bin/bash
# Launch Hazel OS GUI as a desktop app
HAZEL_DIR="$HOME/hazel-os"
PORT=3000

# Start the server in background
python3 "$HAZEL_DIR/hazel-gui.py" &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Open in Chromium app mode (no browser chrome - looks like native app)
if command -v chromium-browser &>/dev/null; then
    chromium-browser --app="http://localhost:$PORT" \
        --window-size=500,700 \
        --window-position=100,50 \
        --disable-extensions \
        --disable-plugins \
        2>/dev/null
elif command -v chromium &>/dev/null; then
    chromium --app="http://localhost:$PORT" \
        --window-size=500,700 \
        2>/dev/null
else
    xdg-open "http://localhost:$PORT"
fi

# When browser closes, kill server
kill $SERVER_PID 2>/dev/null
