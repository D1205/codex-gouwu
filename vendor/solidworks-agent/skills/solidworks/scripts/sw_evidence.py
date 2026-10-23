"""Structured, atomic evidence recording for CAD automation runs."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def atomic_write_json(path: str | os.PathLike[str], payload: dict[str, Any]) -> Path:
    """Write valid JSON to a temporary file and atomically replace the destination."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(_json_value(payload), ensure_ascii=True, indent=2)
    json.loads(serialized)
    handle, temporary = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers (including log/JSON inspection) can briefly hold a file
        # without FILE_SHARE_DELETE. Retry only sharing/access failures, bounded
        # to < 1 second; preserve the original error if it is not transient.
        for attempt in range(6):
            try:
                os.replace(temporary, destination)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(min(0.02 * (2 ** attempt), 0.2))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return destination


def artifact_metadata(path):
    """Fresh stable file identity and content snapshot; never trust cached existence."""
    path = Path(path).expanduser().resolve()
    info = {"path": str(path), "exists": False, "size_bytes": 0}
    try:
        before = path.stat()
        if not path.is_file():
            return info
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        fields = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_ino", "st_dev")
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ValueError(f"artifact changed while hashing: {path}")
        info.update(exists=True, size_bytes=after.st_size, mtime_ns=after.st_mtime_ns,
                    ctime_ns=after.st_ctime_ns, file_id=[after.st_dev, after.st_ino],
                    sha256=digest.hexdigest())
    except FileNotFoundError:
        pass
    return info


def _filesystem_clock_ns():
    # Windows wall-clock precision can exceed filesystem timestamp precision.
    # Compare against a filesystem-created marker, not datetime.now().
    with tempfile.TemporaryFile() as marker:
        return os.fstat(marker.fileno()).st_mtime_ns


@dataclass
class EvidenceRecorder:
    run_id: str
    output_path: str | os.PathLike[str]
    request: dict[str, Any] = field(default_factory=dict)
    started_mtime_ns: int = field(default_factory=_filesystem_clock_ns)
    required_checks: tuple[str, ...] = ()
    required_artifact_kinds: tuple[str, ...] = ()
    manual_review: dict[str, Any] | None = None
    status: str = "running"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def _flush(self) -> Path:
        self.updated_at = _utc_now()
        return atomic_write_json(self.output_path, asdict(self))

    def _invalidate_acceptance(self) -> None:
        self.manual_review = None
        if self.status in {"automatically_verified", "released", "accepted"}:
            self.status = "running"

    def event(
        self,
        stage: str,
        status: str,
        message: str,
        **data: Any,
    ) -> Path:
        self.events.append(
            {
                "timestamp": _utc_now(),
                "stage": stage,
                "status": status,
                "message": message,
                "data": data,
            }
        )
        return self._flush()

    def artifact(self, kind: str, path: str | os.PathLike[str], required: bool = True,
                 generated: bool = True) -> Path:
        metadata = artifact_metadata(path)
        if any(item["path"] == metadata["path"] for item in self.artifacts):
            raise ValueError("artifact already registered; start a new evidence run after edits")
        if required and (not metadata["exists"] or metadata["size_bytes"] <= 0):
            raise ValueError("required artifact must exist and be nonempty")
        if generated and metadata["exists"]:
            if metadata["mtime_ns"] < self.started_mtime_ns:
                raise ValueError("generated artifact predates this run; declare existing source explicitly")
        self.artifacts.append({"kind": kind, "required": bool(required),
                               "generated": generated, **metadata})
        self._invalidate_acceptance()
        return self._flush()

    def check(
        self,
        name: str,
        passed: bool,
        expected: Any = None,
        actual: Any = None,
        details: str | None = None,
        required: bool = True,
    ) -> Path:
        if not name or not isinstance(passed, bool):
            raise ValueError("check needs a name and explicit Boolean result")
        self._invalidate_acceptance()
        self.checks = [item for item in self.checks if item["name"] != name]
        self.checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "expected": expected,
                "actual": actual,
                "details": details,
                "required": bool(required),
            }
        )
        return self._flush()

    def _validate_automatic(self) -> list[dict[str, Any]]:
        if (not self.required_checks or not self.required_artifact_kinds
                or any(not isinstance(name, str) or not name.strip()
                       for name in (*self.required_checks, *self.required_artifact_kinds))):
            raise ValueError("cannot accept run without named required checks and artifact kinds")
        checks = {item["name"]: item for item in self.checks}
        if any(name not in checks or checks[name]["passed"] is not True
               for name in self.required_checks):
            raise ValueError("cannot accept run: missing or failed required checks")
        if any(item["required"] and item["passed"] is not True for item in self.checks):
            raise ValueError("cannot accept run: failed required checks")
        manifest = []
        for item in self.artifacts:
            current = artifact_metadata(item["path"])
            registered = {key: item[key] for key in current if key in item}
            if current != registered:
                raise ValueError(f"cannot accept run: artifact changed or deleted: {item['path']}")
            if item["required"] and (not current["exists"] or current["size_bytes"] <= 0):
                raise ValueError("cannot accept run: missing or empty required artifact")
            manifest.append({"kind": item["kind"], **current})
        for kind in self.required_artifact_kinds:
            if not any(item["kind"] == kind and item["exists"] and item["size_bytes"] > 0
                       for item in manifest):
                raise ValueError(f"cannot accept run: missing required artifact kind {kind}")
        return manifest

    def record_manual_review(self, reviewer: str, decision: str, details: str) -> Path:
        """Attest actual visual review of this exact artifact set; no auto approval."""
        if not reviewer.strip() or not details.strip() or decision not in {"approved", "rejected"}:
            raise ValueError("review requires reviewer, approved/rejected decision and rationale")
        manifest = self._validate_automatic()
        self._invalidate_acceptance()
        self.manual_review = {"reviewer": reviewer, "decision": decision, "details": details,
                              "timestamp": _utc_now(), "artifacts": manifest}
        return self._flush()

    def validate_release(self) -> None:
        manifest = self._validate_automatic()
        if (not self.manual_review or self.manual_review["decision"] != "approved"
                or self.manual_review["artifacts"] != manifest):
            raise ValueError("cannot accept run: visual review pending, rejected or stale")

    def finalize(self, status: str) -> Path:
        if status not in {"generated", "automatically_verified", "released", "accepted",
                          "failed", "blocked", "cancelled"}:
            raise ValueError(f"invalid final status: {status}")
        if status == "automatically_verified":
            self._validate_automatic()
        if status in {"accepted", "released"}:
            self.validate_release()
            status = "released"  # legacy accepted calls obey the same release gate
        self.status = status
        return self._flush()
