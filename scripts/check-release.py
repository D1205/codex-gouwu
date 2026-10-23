"""Check tracked publication files without displaying any matched secret value."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".local", ".venv", "node_modules", "results", "dist", "build", "releases", "__pycache__"}
PATTERNS = {
    "api_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "private_key": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
}


def main() -> int:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [name.decode("utf-8") for name in tracked.split(b"\0") if name]
    if not files:
        print(json.dumps({"status": "failed", "error": "No tracked files; add intended release files first"}))
        return 1
    issues, total = [], 0
    for name in files:
        path = ROOT / name
        components = set(Path(name).parts)
        if components & FORBIDDEN or name == "rules/runtime-lock.json" or Path(name).name.startswith(".env"):
            if Path(name).name != ".env.example":
                issues.append({"file": name, "kind": "local_data_or_environment"})
        if path.is_symlink():
            issues.append({"file": name, "kind": "symlink"})
            continue
        if not path.is_file():
            issues.append({"file": name, "kind": "missing_file"})
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            issues.append({"file": name, "kind": "large_file_use_release_asset"})
            continue
        data = path.read_bytes()
        total += len(data)
        for kind, pattern in PATTERNS.items():
            if pattern.search(data):
                issues.append({"file": name, "kind": kind})
    print(json.dumps({"status": "failed" if issues else "passed", "tracked_files": len(files),
                      "bytes": total, "issues": issues}, ensure_ascii=True))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
