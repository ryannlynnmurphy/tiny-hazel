#!/usr/bin/env python3
"""
Hazel OS global hotkey daemon.
Press ` (backtick) from anywhere to open Hazel in a terminal.
"""

import subprocess
import os
import sys

def main():
    # Check if we can use wtype/wlrctl for Wayland hotkey
    # For now, set up as keyboard shortcut via labwc/openbox config

    config_dir = os.path.expanduser("~/.config/labwc")
    rc_path = os.path.join(config_dir, "rc.xml")

    hazel_cmd = os.path.expanduser("~/.local/bin/hazel")
    terminal_cmd = f"x-terminal-emulator -e {hazel_cmd}"

    # Check if labwc config exists (Raspberry Pi OS default on Bookworm+)
    if os.path.exists(rc_path):
        with open(rc_path, "r") as f:
            content = f.read()

        if "hazel" in content.lower():
            print("Hotkey already configured.")
            return

        # Add keybind before closing </keyboard> tag
        keybind = f"""
    <!-- Hazel OS: Press Super+H to open Hazel -->
    <keybind key="Super_L-h">
      <action name="Execute" command="{terminal_cmd}" />
    </keybind>
"""
        content = content.replace("</keyboard>", keybind + "  </keyboard>")

        with open(rc_path, "w") as f:
            f.write(content)

        # Reconfigure labwc
        subprocess.run(["labwc", "--reconfigure"], capture_output=True)
        print("Hotkey configured: Super+H opens Hazel")
        print("(Press the Windows/Super key + H from anywhere)")
    else:
        print("labwc not found. Add a keyboard shortcut manually:")
        print(f"  Command: {terminal_cmd}")
        print("  Suggested key: Super+H or Ctrl+`")


if __name__ == "__main__":
    main()
