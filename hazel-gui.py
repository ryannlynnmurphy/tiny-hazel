#!/usr/bin/env python3
"""
Hazel OS - GUI Edition
Full visual interface with animated face, branding, and personality.
Runs as local web app, opens in browser.
"""

import json
import os
import sys
import threading
import time
import webbrowser
import random
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify, Response

# Import hazel core
sys.path.insert(0, str(Path(__file__).parent))
from hazel import (
    handle_instant, ask_llm, agent_step, get_llm_context, is_deep_query,
    extract_commands, run_cmd, is_dangerous, humanize, auto_provision,
    download_model, auto_select_models,
    sys_overview, sys_temp, get_face, remember, get_memory_context,
    HAZEL_DIR, MODEL_DEFAULT, MODEL_DEEP, get_installed_models,
    get_available_ram_gb, has_gpu, recommend_models, FACES,
    G, B, Y, R, D, BD, X,
)

app = Flask(__name__)

# === LOADING MESSAGES ===
LOADING_MESSAGES = [
    # Privacy
    "Running locally on YOUR hardware. No data leaves this device.",
    "Zero bytes sent to the cloud. You're welcome.",
    "No servers in Oregon were harmed in generating this response.",
    "Your query never left the building. Literally.",
    "This is what privacy looks like.",
    "Fun fact: this response costs $0.00 in API fees.",
    "No subscription required. No login. No tracking.",

    # How it works
    "Checking if I can answer instantly or need to think...",
    "I can search your files, read them, check your system, and run commands.",
    "Six tools at my disposal. Let me pick the right one.",
    "Pattern matching first. If I miss, I think harder.",
    "I run three models. Small for speed, big for brains.",

    # Self-aware
    "I may be small but I can actually do things now.",
    "Not just talking about it. Actually doing it.",
    "I live on your machine. Everything I know, I learned from here.",
    "No hallucinating file paths. I look things up for real.",

    # Personality
    "Hold on, my hamster wheel is spinning...",
    "Computing locally... like it's 1995 but better.",
    "If I'm slow it's because I'm THINKING, not buffering.",
    "Generating response using only vibes and linear algebra...",
    "I'm not slow, I'm thoughtful.",
    "Processing... with zero venture capital...",
    "One sec, checking the actual answer instead of guessing...",
    "Doing real work on your real machine with real files.",
]

DEEP_LOADING_MESSAGES = [
    "Deep thinking mode. Switching to the bigger model.",
    "This one deserves the full brain. Give me a moment.",
    "Complex question detected. Engaging all cores.",
    "Loading the heavy model. Like putting on my reading glasses.",
    "Pulling out the 7 billion parameter brain for this one.",
    "Deep thinking... searching, reading, reasoning.",
    "Big question. Big model. Real answers.",
    "This is where tool use really shines. Hang on.",
]


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hazel OS</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --bg: #0f1114;
            --bg-secondary: #1a1d23;
            --bg-chat: #22262e;
            --text: #e0e4e8;
            --text-dim: #6b7280;
            --green: #4ade80;
            --green-dim: #166534;
            --blue: #60a5fa;
            --yellow: #fbbf24;
            --red: #f87171;
            --border: #2d3139;
        }

        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* === HEADER === */
        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo {
            font-size: 18px;
            font-weight: 700;
            color: var(--green);
            letter-spacing: 2px;
        }

        .status-bar {
            font-size: 12px;
            color: var(--text-dim);
        }

        .status-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            margin-right: 6px;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* === FACE === */
        .face-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
            user-select: none;
        }

        .face {
            font-size: 48px;
            transition: all 0.3s ease;
            line-height: 1;
        }

        .face.thinking {
            animation: think 1.5s ease-in-out infinite;
        }

        @keyframes think {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-4px); }
        }

        .face-label {
            font-size: 11px;
            color: var(--text-dim);
            margin-top: 6px;
        }

        /* === CHAT === */
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 16px 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .message {
            max-width: 85%;
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .message.user {
            align-self: flex-end;
            background: var(--green-dim);
            color: var(--green);
            border-bottom-right-radius: 4px;
        }

        .message.hazel {
            align-self: flex-start;
            background: var(--bg-chat);
            border-bottom-left-radius: 4px;
        }

        .message.system {
            align-self: center;
            background: transparent;
            color: var(--text-dim);
            font-size: 12px;
            font-style: italic;
            text-align: center;
            padding: 4px;
        }

        .message.command {
            align-self: flex-start;
            background: #1a1a2e;
            border-left: 3px solid var(--blue);
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
        }

        .message.warning {
            border-left: 3px solid var(--yellow);
            background: #1a1a1e;
        }

        .message .raw-data {
            font-size: 11px;
            color: var(--text-dim);
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid var(--border);
            font-family: monospace;
        }

        .message .timing {
            font-size: 11px;
            color: var(--text-dim);
            margin-top: 4px;
        }

        .loading-msg {
            font-size: 16px;
            color: var(--text-dim);
            font-style: italic;
            text-align: center;
            padding: 8px 16px;
            animation: loadFadeIn 0.4s ease-out;
        }

        .loading-msg .loading-text {
            display: inline-block;
            animation: loadCycle 0.4s ease-out;
        }

        @keyframes loadFadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes loadCycle {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* === INPUT === */
        .input-container {
            background: var(--bg-secondary);
            border-top: 1px solid var(--border);
            padding: 16px 20px;
            display: flex;
            gap: 10px;
        }

        .input-container input {
            flex: 1;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 16px;
            color: var(--text);
            font-size: 14px;
            outline: none;
            font-family: inherit;
        }

        .input-container input:focus {
            border-color: var(--green);
        }

        .input-container input::placeholder {
            color: var(--text-dim);
        }

        .input-container button {
            background: var(--green);
            color: var(--bg);
            border: none;
            border-radius: 8px;
            padding: 12px 20px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }

        .input-container button:hover { opacity: 0.8; }
        .input-container button:disabled { opacity: 0.3; cursor: not-allowed; }

        /* === SCROLLBAR === */
        .chat-container::-webkit-scrollbar { width: 6px; }
        .chat-container::-webkit-scrollbar-track { background: transparent; }
        .chat-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

        /* === QUICK COMMANDS === */
        .quick-commands {
            display: flex;
            gap: 6px;
            padding: 8px 20px;
            overflow-x: auto;
            background: var(--bg);
        }

        .quick-cmd {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 4px 12px;
            font-size: 12px;
            color: var(--text-dim);
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }

        .quick-cmd:hover {
            border-color: var(--green);
            color: var(--green);
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <span class="logo">HAZEL</span>
            <span class="status-bar">
                <span class="status-dot"></span>
                <span id="system-status">Loading...</span>
            </span>
        </div>
        <div class="face-container">
            <div class="face" id="hazel-face">(^_^)</div>
            <div class="face-label" id="face-label">online</div>
        </div>
    </div>

    <div class="quick-commands">
        <span class="quick-cmd" onclick="sendMessage('status')">status</span>
        <span class="quick-cmd" onclick="sendMessage('temp')">temp</span>
        <span class="quick-cmd" onclick="sendMessage('model')">model</span>
        <span class="quick-cmd" onclick="sendMessage('hardware')">hardware</span>
        <span class="quick-cmd" onclick="sendMessage('files')">files</span>
        <span class="quick-cmd" onclick="sendMessage('top')">processes</span>
        <span class="quick-cmd" onclick="sendMessage('network')">network</span>
        <span class="quick-cmd" onclick="sendMessage('help')">help</span>
    </div>

    <div class="chat-container" id="chat"></div>

    <div class="input-container">
        <input type="text" id="input" placeholder="Talk to Hazel..." autocomplete="off"
               onkeydown="if(event.key==='Enter')sendMessage()">
        <button onclick="sendMessage()" id="send-btn">Send</button>
    </div>

    <script>
        const chat = document.getElementById('chat');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('send-btn');
        const face = document.getElementById('hazel-face');
        const faceLabel = document.getElementById('face-label');
        const systemStatus = document.getElementById('system-status');

        const loadingMessages = LOADING_MESSAGES_JSON;
        const deepLoadingMessages = DEEP_LOADING_MESSAGES_JSON;

        // Fetch system status on load
        fetch('/api/status').then(r => r.json()).then(data => {
            systemStatus.textContent = data.summary;
            face.textContent = data.face;
        });

        // Refresh status every 30s
        setInterval(() => {
            fetch('/api/status').then(r => r.json()).then(data => {
                systemStatus.textContent = data.summary;
                face.textContent = data.face;
            });
        }, 30000);

        // Welcome message
        addMessage('hazel',
            "Hey! I'm Hazel, your local AI assistant. " +
            "Everything I do runs right here on this device - " +
            "no cloud, no tracking, no data leaving this room.\\n\\n" +
            "Ask me anything, or tap a quick command above.");

        function addMessage(type, text, extra) {
            const div = document.createElement('div');
            div.className = 'message ' + type;
            div.textContent = text;
            if (extra) {
                const raw = document.createElement('div');
                raw.className = 'raw-data';
                raw.textContent = extra;
                div.appendChild(raw);
            }
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
            return div;
        }

        let loadingInterval = null;

        function setThinking(isDeep) {
            face.className = 'face thinking';
            faceLabel.textContent = isDeep ? 'thinking deeply...' : 'thinking...';
            face.textContent = '(-_-)';

            const msgs = isDeep ? deepLoadingMessages : loadingMessages;
            // Shuffle and pick a sequence to cycle through
            const shuffled = [...msgs].sort(() => Math.random() - 0.5);
            let idx = 0;

            const div = document.createElement('div');
            div.className = 'message system loading-msg';
            const span = document.createElement('span');
            span.className = 'loading-text';
            span.textContent = shuffled[idx];
            div.appendChild(span);
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;

            // Cycle to next message every 2.5s
            loadingInterval = setInterval(() => {
                idx = (idx + 1) % shuffled.length;
                span.style.animation = 'none';
                span.offsetHeight; // force reflow
                span.style.animation = 'loadCycle 0.4s ease-out';
                span.textContent = shuffled[idx];
                chat.scrollTop = chat.scrollHeight;
            }, 2500);

            return div;
        }

        function stopThinking() {
            if (loadingInterval) {
                clearInterval(loadingInterval);
                loadingInterval = null;
            }
            face.className = 'face';
            faceLabel.textContent = 'online';
            fetch('/api/status').then(r => r.json()).then(data => {
                face.textContent = data.face;
            });
        }

        async function sendMessage(preset) {
            const text = preset || input.value.trim();
            if (!text) return;

            input.value = '';
            sendBtn.disabled = true;
            input.disabled = true;

            addMessage('user', text);

            // Check if deep query
            const deepKeywords = ['explain','why','how does','how do','what is','what are',
                'teach','describe','compare','write','create','build','debug','fix','solve',
                'analyze','review'];
            const isDeep = deepKeywords.some(kw => text.toLowerCase().includes(kw));
            const loadingDiv = setThinking(isDeep);

            try {
                const resp = await fetch('/api/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: text})
                });
                const data = await resp.json();

                // Remove loading message
                loadingDiv.remove();
                stopThinking();

                // Show response
                if (data.response) {
                    addMessage('hazel', data.response, data.raw_data);
                }
                if (data.timing) {
                    const t = document.createElement('div');
                    t.className = 'message system';
                    t.textContent = data.timing;
                    chat.appendChild(t);
                }

                // Show commands
                if (data.commands) {
                    for (const cmd of data.commands) {
                        if (data.dangerous && data.dangerous.includes(cmd)) {
                            addMessage('warning', 'Dangerous: ' + cmd + '\\nType "yes ' + cmd + '" to confirm');
                        } else {
                            addMessage('command', '$ ' + cmd + '\\n' + (data.command_output || ''));
                        }
                    }
                }
            } catch(e) {
                loadingDiv.remove();
                stopThinking();
                addMessage('hazel', 'Something went wrong: ' + e.message);
            }

            sendBtn.disabled = false;
            input.disabled = false;
            input.focus();
        }

        input.focus();
    </script>
</body>
</html>"""


# === API ROUTES ===

@app.route("/")
def index():
    html = HTML_TEMPLATE.replace(
        "LOADING_MESSAGES_JSON", json.dumps(LOADING_MESSAGES)
    ).replace(
        "DEEP_LOADING_MESSAGES_JSON", json.dumps(DEEP_LOADING_MESSAGES)
    )
    return html


@app.route("/api/status")
def api_status():
    overview = sys_overview()
    face = get_face()
    return jsonify({"summary": overview, "face": face})


@app.route("/api/query", methods=["POST"])
def api_query():
    try:
        return _handle_query()
    except Exception as e:
        return jsonify({
            "response": f"Oops, I hit a bump: {str(e)[:200]}. Try again?",
            "timing": "error",
        })


def _handle_query():
    data = request.json
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"response": "Say something!"})

    import re

    # Try instant handler
    instant = handle_instant(query)
    if instant is not None:
        response_text, flag = instant

        # Handle download requests in background thread
        if flag == "download" and response_text.startswith("__DOWNLOAD__:"):
            parts = response_text.split(":", 3)
            model_name = parts[1]
            size_gb = parts[2]
            desc = parts[3] if len(parts) > 3 else ""

            def _bg_download(name):
                success = download_model(name)
                if success:
                    auto_select_models()

            threading.Thread(target=_bg_download, args=(model_name,), daemon=True).start()

            return jsonify({
                "response": f"Downloading {model_name} ({size_gb}GB)... this will take a few minutes.\n\n{desc}\n\nI'll keep working while it downloads. Type 'model' to check when it's ready.",
            })

        display, commands = extract_commands(response_text)

        # Strip ANSI colors
        clean_display = re.sub(r'\033\[[0-9;]*m', '', display).strip()

        raw_data = None
        if flag == "skip":
            result_text = clean_display
        elif clean_display and not commands:
            natural = humanize(clean_display, query)
            result_text = natural
            raw_data = clean_display
        else:
            result_text = clean_display

        # Execute safe commands
        cmd_output = ""
        dangerous_cmds = []
        for cmd in commands:
            if is_dangerous(cmd):
                dangerous_cmds.append(cmd)
            else:
                cmd_output = run_cmd(cmd)

        remember("user", query)
        remember("hazel", result_text[:100])

        return jsonify({
            "response": result_text,
            "raw_data": raw_data,
            "commands": commands if commands else None,
            "command_output": cmd_output if cmd_output else None,
            "dangerous": dangerous_cmds if dangerous_cmds else None,
        })

    # LLM fallback (with tools)
    deep = is_deep_query(query)
    context = get_llm_context(query)
    start = time.time()
    response = agent_step(query, context)
    elapsed = time.time() - start

    if response is None:
        return jsonify({
            "response": "Hmm, I couldn't figure that out. Try rephrasing?",
            "timing": "timed out",
        })

    display, commands = extract_commands(response)

    cmd_output = ""
    dangerous_cmds = []
    for cmd in commands:
        if is_dangerous(cmd):
            dangerous_cmds.append(cmd)
        else:
            cmd_output = run_cmd(cmd)

    remember("user", query)
    remember("hazel", display[:100])

    return jsonify({
        "response": display,
        "commands": commands if commands else None,
        "command_output": cmd_output if cmd_output else None,
        "dangerous": dangerous_cmds if dangerous_cmds else None,
        "timing": f"{elapsed:.1f}s",
    })


def main():
    # Auto-download models this machine needs
    auto_provision()

    port = 3000

    print(f"\n  HAZEL OS - GUI")
    print(f"  Running on http://localhost:{port}")
    print(f"  Press Ctrl+C to stop\n")

    # Don't open browser - the launcher script handles that
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
