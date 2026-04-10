#!/bin/bash
# Launch Hazel OS GUI as a native-looking desktop app
HAZEL_DIR="$HOME/hazel-os"
PORT=3000
URL="http://localhost:$PORT"

# Kill any existing instances
killall -q python3 2>/dev/null
sleep 1

# Start the server in background
python3 "$HAZEL_DIR/hazel-gui.py" > /tmp/hazel-gui.log 2>&1 &
SERVER_PID=$!

# Wait until server is actually responding (up to 30 seconds)
echo "Starting Hazel..."
for i in $(seq 1 30); do
    if curl -s -o /dev/null "$URL" 2>/dev/null; then
        echo "Server ready."
        break
    fi
    sleep 1
done

# Open ONLY in Chromium app mode (no browser chrome)
if command -v chromium-browser &>/dev/null; then
    chromium-browser \
        --app="$URL" \
        --window-size=520,750 \
        --disable-extensions \
        --disable-plugins \
        --no-first-run \
        --noerrdialogs \
        2>/dev/null
elif command -v chromium &>/dev/null; then
    chromium \
        --app="$URL" \
        --window-size=520,750 \
        --no-first-run \
        2>/dev/null
fi

# When app window closes, kill server
kill $SERVER_PID 2>/dev/null
