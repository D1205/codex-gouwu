"""Atomic task state, immutable artifacts, and an exclusive local execution lease."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator


def safe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise ValueError("ID must contain only ASCII letters, digits, '.', '-' and '_'")
    return value


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    """Replace only a complete flushed file, keeping an old receipt intact on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def execution_lease(root: Path) -> Iterator[None]:
    """One CAD writer; a leftover lease blocks rather than silently restarting work."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "cad.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"CAD worker busy or interrupted; inspect execution lease: {path}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid()}, stream)
        yield
    finally:
        path.unlink(missing_ok=True)


def verify_artifacts(result: dict, output_dir: Path) -> list[str]:
    """Evidence is valid only for present, nonempty files inside this revision."""
    errors: list[str] = []
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return ["Missing artifact ledger"]
    root = output_dir.resolve()
    for item in artifacts:
        try:
            path = Path(item["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Artifact escapes its revision directory")
            if not path.is_file() or path.stat().st_size <= 0:
                raise ValueError("Artifact missing or empty")
            if path.stat().st_size != item["size_bytes"] or sha256(path) != item["sha256"]:
                raise ValueError("Artifact fingerprint mismatch")
        except (KeyError, OSError, ValueError, TypeError) as error:
            errors.append(str(error))
    return errors
