"""Verify pinned distributable resources without CAD, network or app dependencies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    manifest_path = PROJECT / "vendor/SOURCES.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != "vendor-sources/1":
        raise ValueError("Unsupported vendor manifest")
    declared = {manifest_path.resolve()}
    copied = 0
    for source in manifest["sources"]:
        for item in source["files"]:
            path = (PROJECT / item["path"]).resolve()
            if not path.is_relative_to(PROJECT / "vendor") or path in declared:
                raise ValueError(f"Invalid or duplicate vendor path: {item['path']}")
            data = path.read_bytes()
            if len(data) != item["size_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(f"Vendor snapshot changed: {item['path']}")
            if "git_blob_sha256" in item:
                upstream = data.replace(b"\r\n", b"\n") if item["checkout_transform"] != "none" else data
                if hashlib.sha256(upstream).hexdigest() != item["git_blob_sha256"]:
                    raise ValueError(f"Upstream Git blob mismatch: {item['path']}")
            declared.add(path)
            copied += 1
        if source.get("rule_lock"):
            path = PROJECT / source["rule_lock"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["rule_lock_sha256"]:
                raise ValueError("Original rule lock changed; explicit migration is required")
    # Python may generate caches while importing the provider; they are never
    # source resources and are excluded from both Git and the packaging allowlist.
    actual = {p.resolve() for p in (PROJECT / "vendor").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts}
    if actual != declared:
        raise ValueError(f"Undeclared/missing vendor files: {sorted(str(p) for p in actual ^ declared)}")
    lock = json.loads((PROJECT / "rules/lock.json").read_text(encoding="utf-8"))
    for relative, expected in lock["files"].items():
        path = PROJECT / "vendor/mechanical-design-sop" / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Locked policy changed: {relative}")
    print(f"Verified {copied} vendored files and {len(lock['files'])} unchanged policy hashes.")


if __name__ == "__main__":
    main()
