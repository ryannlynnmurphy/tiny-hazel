#!/usr/bin/env python3
"""
Hazel User Profiler
Scans the local machine to understand who the user is.
Everything stays local. No data leaves the device.
"""

import os
import json
import subprocess
import time
from pathlib import Path
from collections import Counter
from datetime import datetime

HAZEL_DIR = Path.home() / ".hazel"
PROFILE_FILE = HAZEL_DIR / "profile.json"


def scan_file_types(home):
    """What kinds of files does this person have?"""
    ext_count = Counter()
    total_files = 0
    for root, dirs, files in os.walk(str(home)):
        # Skip hidden, node_modules, build dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d not in ("node_modules", "__pycache__", "llama.cpp",
                                 ".git", "build", "dist", ".cache", "models")]
        for f in files:
            if f.startswith("."):
                continue
            ext = Path(f).suffix.lower()
            if ext:
                ext_count[ext] += 1
            total_files += 1
            if total_files > 5000:
                return ext_count
    return ext_count


def detect_role(ext_count):
    """Guess what the user does based on their files."""
    roles = []
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
                 ".h", ".rs", ".go", ".rb", ".php", ".swift", ".kt"}
    web_exts = {".html", ".css", ".scss", ".vue", ".svelte"}
    writing_exts = {".md", ".txt", ".doc", ".docx", ".pdf", ".fountain", ".rtf"}
    media_exts = {".mp3", ".wav", ".flac", ".mp4", ".mov", ".avi", ".mkv"}
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".psd", ".xcf"}
    data_exts = {".csv", ".json", ".xml", ".yaml", ".yml", ".sql", ".db"}
    design_exts = {".fig", ".sketch", ".ai", ".eps", ".indd"}

    code_count = sum(ext_count.get(e, 0) for e in code_exts)
    web_count = sum(ext_count.get(e, 0) for e in web_exts)
    writing_count = sum(ext_count.get(e, 0) for e in writing_exts)
    media_count = sum(ext_count.get(e, 0) for e in media_exts)
    image_count = sum(ext_count.get(e, 0) for e in image_exts)
    data_count = sum(ext_count.get(e, 0) for e in data_exts)
    design_count = sum(ext_count.get(e, 0) for e in design_exts)

    if code_count > 20:
        roles.append("developer")
    if web_count > 10:
        roles.append("web developer")
    if writing_count > 10:
        roles.append("writer")
    if media_count > 20:
        roles.append("media creator")
    if image_count > 30:
        roles.append("visual artist")
    if data_count > 10:
        roles.append("data worker")
    if design_count > 5:
        roles.append("designer")
    if ext_count.get(".fountain", 0) > 0:
        roles.append("playwright/screenwriter")

    return roles if roles else ["general user"]


def detect_languages(ext_count):
    """What programming languages do they use?"""
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".jsx": "React", ".tsx": "React/TypeScript",
        ".java": "Java", ".c": "C", ".cpp": "C++",
        ".rs": "Rust", ".go": "Go", ".rb": "Ruby",
        ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin",
        ".sh": "Bash", ".html": "HTML", ".css": "CSS",
        ".sql": "SQL", ".r": "R",
    }
    langs = []
    for ext, name in lang_map.items():
        count = ext_count.get(ext, 0)
        if count > 0:
            langs.append({"name": name, "files": count})
    return sorted(langs, key=lambda x: x["files"], reverse=True)[:8]


def scan_git_repos(home):
    """Find git repos to understand projects."""
    repos = []

    # Scan top-level directories for .git (fast, works on all platforms)
    for d in home.iterdir():
        if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists():
            root = str(d)
            repo_name = os.path.basename(root)
            # Get last commit date
            try:
                r = subprocess.run(
                    ["git", "-C", root, "log", "-1", "--format=%ci"],
                    capture_output=True, text=True, timeout=5,
                )
                last_commit = r.stdout.strip()[:10] if r.stdout.strip() else "unknown"
            except Exception:
                last_commit = "unknown"

            # Get branch
            try:
                r = subprocess.run(
                    ["git", "-C", root, "branch", "--show-current"],
                    capture_output=True, text=True, timeout=5,
                )
                branch = r.stdout.strip() or "unknown"
            except Exception:
                branch = "unknown"

            repos.append({
                "name": repo_name,
                "path": os.path.relpath(root, str(home)),
                "last_commit": last_commit,
                "branch": branch,
            })
    return repos[:15]


def scan_installed_packages():
    """What software is installed?"""
    packages = []

    # apt (Debian/Ubuntu/Pi)
    try:
        r = subprocess.run(
            ["dpkg-query", "-W", "-f", "${Package}\n"],
            capture_output=True, text=True, timeout=10,
        )
        apt_pkgs = r.stdout.strip().split("\n")
        packages.append({"manager": "apt", "count": len(apt_pkgs)})

        # Notable packages
        notable = []
        interesting = [
            "nodejs", "python3", "docker", "nginx", "apache2",
            "postgresql", "mysql", "redis", "code", "gimp",
            "blender", "libreoffice", "vlc", "chromium", "firefox",
            "golang", "rustc", "openjdk",
        ]
        for pkg in interesting:
            if any(pkg in p for p in apt_pkgs):
                notable.append(pkg)
        if notable:
            packages.append({"notable_apt": notable})
    except Exception:
        pass

    # pip
    try:
        r = subprocess.run(
            ["pip3", "list", "--format=freeze"],
            capture_output=True, text=True, timeout=10,
        )
        pip_pkgs = [l.split("==")[0] for l in r.stdout.strip().split("\n") if l]
        packages.append({"manager": "pip", "count": len(pip_pkgs)})

        notable_pip = []
        interesting_pip = [
            "flask", "django", "fastapi", "numpy", "pandas",
            "tensorflow", "torch", "transformers", "jupyter",
            "requests", "scrapy", "pillow", "opencv",
        ]
        for pkg in interesting_pip:
            if any(pkg in p.lower() for p in pip_pkgs):
                notable_pip.append(pkg)
        if notable_pip:
            packages.append({"notable_pip": notable_pip})
    except Exception:
        pass

    return packages


def scan_recent_files(home, days=7):
    """What has the user been working on recently?"""
    recent = []
    cutoff = time.time() - (days * 86400)

    for root, dirs, files in os.walk(str(home)):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d not in ("node_modules", "__pycache__", "llama.cpp",
                                 "models", ".cache", "build")]
        for f in files:
            if f.startswith("."):
                continue
            fp = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(fp)
                if mtime > cutoff:
                    recent.append({
                        "name": f,
                        "path": os.path.relpath(fp, str(home)),
                        "modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                        "size": os.path.getsize(fp),
                    })
            except Exception:
                pass

    # Sort by most recent
    recent.sort(key=lambda x: x["modified"], reverse=True)
    return recent[:20]


def scan_shell_history():
    """What commands does the user run?"""
    history_files = [
        Path.home() / ".bash_history",
        Path.home() / ".zsh_history",
    ]

    commands = Counter()
    for hf in history_files:
        if hf.exists():
            try:
                lines = hf.read_text(errors="ignore").strip().split("\n")
                for line in lines[-500:]:  # Last 500 commands
                    # Get base command
                    cmd = line.strip().lstrip(": 0123456789;")
                    if cmd:
                        base = cmd.split()[0] if cmd.split() else ""
                        if base and not base.startswith("#"):
                            commands[base] += 1
            except Exception:
                pass

    return [{"cmd": cmd, "count": n} for cmd, n in commands.most_common(15)]


def scan_home_structure(home):
    """Top-level directory structure."""
    dirs = []
    for d in sorted(home.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            # Count files in this dir
            try:
                count = sum(1 for _ in d.rglob("*") if _.is_file())
            except Exception:
                count = 0
            dirs.append({"name": d.name, "files": min(count, 9999)})
    return dirs[:20]


def build_profile():
    """Build complete user profile from machine scan."""
    home = Path.home()
    profile = {
        "generated": datetime.now().isoformat(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "username": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
        "home": str(home),
    }

    print("  Scanning files...")
    ext_count = scan_file_types(home)
    profile["file_types"] = dict(ext_count.most_common(20))
    profile["total_file_types"] = len(ext_count)

    print("  Detecting role...")
    profile["roles"] = detect_role(ext_count)

    print("  Detecting languages...")
    profile["languages"] = detect_languages(ext_count)

    print("  Scanning projects...")
    profile["git_repos"] = scan_git_repos(home)

    print("  Scanning packages...")
    profile["packages"] = scan_installed_packages()

    print("  Finding recent work...")
    profile["recent_files"] = scan_recent_files(home)

    print("  Reading command history...")
    profile["frequent_commands"] = scan_shell_history()

    print("  Mapping home directory...")
    profile["home_structure"] = scan_home_structure(home)

    # Generate summary
    roles_str = ", ".join(profile["roles"])
    lang_str = ", ".join(l["name"] for l in profile["languages"][:5])
    repo_str = ", ".join(r["name"] for r in profile["git_repos"][:5])
    recent_str = ", ".join(f["name"] for f in profile["recent_files"][:5])

    profile["summary"] = (
        f"User {profile['username']} on {profile['hostname']}. "
        f"Roles: {roles_str}. "
        f"Languages: {lang_str or 'none detected'}. "
        f"Projects: {repo_str or 'none'}. "
        f"Recently working on: {recent_str or 'unknown'}."
    )

    return profile


def save_profile(profile):
    """Save profile to disk."""
    HAZEL_DIR.mkdir(exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(profile, indent=2))


def load_profile():
    """Load existing profile."""
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text())
        except Exception:
            pass
    return None


def get_profile_summary():
    """Get the one-line summary for LLM context."""
    profile = load_profile()
    if profile:
        return profile.get("summary", "")
    return ""


def main():
    print("\n  Hazel User Profiler")
    print("  ===================")
    print("  Scanning your machine to learn about you.")
    print("  Everything stays local.\n")

    profile = build_profile()
    save_profile(profile)

    print(f"\n  Profile saved to {PROFILE_FILE}")
    print(f"\n  Summary:")
    print(f"  {profile['summary']}")
    print(f"\n  Roles: {', '.join(profile['roles'])}")
    print(f"  Languages: {', '.join(l['name'] for l in profile['languages'][:5])}")
    print(f"  Projects: {', '.join(r['name'] for r in profile['git_repos'][:5])}")
    print(f"  Recent files: {', '.join(f['name'] for f in profile['recent_files'][:5])}")
    print()


if __name__ == "__main__":
    main()
