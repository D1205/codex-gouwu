"""Single-heavyweight-session guard for SolidWorks and common ANSYS processes.

The guard is intentionally non-destructive: it reports conflicts but never terminates a
process. Agents must decide whether an existing instance belongs to the current job.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


PROCESS_GROUPS = {
    "solidworks": {"sldworks.exe"},
    "ansys": {
        "runwb2.exe",
        "ansyswbu.exe",
        "mechanical.exe",
        "mapdl.exe",
        "ansyscl.exe",
        "ansysfw.exe",
    },
}


@dataclass(frozen=True)
class ProcessInfo:
    name: str
    pid: int | None = None


@dataclass(frozen=True)
class GuardDecision:
    target: str
    allowed: bool
    reuse_existing: bool
    reason: str
    target_processes: tuple[str, ...]
    conflicting_processes: tuple[str, ...]


def _normalize_name(name: str) -> str:
    return os.path.basename(str(name)).strip().lower()


def parse_tasklist_csv(output: str) -> list[ProcessInfo]:
    """Parse `tasklist /FO CSV /NH` output without depending on UI language."""
    result: list[ProcessInfo] = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) < 2 or not row[0] or row[0].startswith("INFO:"):
            continue
        try:
            pid = int(row[1])
        except (TypeError, ValueError):
            pid = None
        result.append(ProcessInfo(name=_normalize_name(row[0]), pid=pid))
    return result


def running_processes() -> list[ProcessInfo]:
    """Return a process snapshot using the Windows built-in `tasklist` command."""
    if os.name != "nt":
        return []
    completed = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return parse_tasklist_csv(completed.stdout)


def evaluate_launch(
    target: str,
    processes: Iterable[ProcessInfo | str],
    allow_reuse: bool = False,
) -> GuardDecision:
    """Evaluate whether a new heavyweight application may be started."""
    target = str(target).strip().lower()
    if target not in PROCESS_GROUPS:
        raise ValueError(f"unsupported target: {target}")

    names = {
        _normalize_name(item.name if isinstance(item, ProcessInfo) else item)
        for item in processes
    }
    target_names = sorted(names & PROCESS_GROUPS[target])
    other_groups = set().union(
        *(members for group, members in PROCESS_GROUPS.items() if group != target)
    )
    conflicts = sorted(names & other_groups)

    if conflicts:
        return GuardDecision(
            target=target,
            allowed=False,
            reuse_existing=False,
            reason="another heavyweight CAD/CAE application is already running",
            target_processes=tuple(target_names),
            conflicting_processes=tuple(conflicts),
        )
    if target_names and not allow_reuse:
        return GuardDecision(
            target=target,
            allowed=False,
            reuse_existing=False,
            reason="a target application instance already exists; explicitly allow reuse",
            target_processes=tuple(target_names),
            conflicting_processes=(),
        )
    if target_names:
        return GuardDecision(
            target=target,
            allowed=True,
            reuse_existing=True,
            reason="reuse the existing target application instance",
            target_processes=tuple(target_names),
            conflicting_processes=(),
        )
    return GuardDecision(
        target=target,
        allowed=True,
        reuse_existing=False,
        reason="no heavyweight application conflict detected",
        target_processes=(),
        conflicting_processes=(),
    )


def assert_can_start(target: str, allow_reuse: bool = False) -> GuardDecision:
    """Raise a clear error when the current process snapshot violates the guard."""
    decision = evaluate_launch(target, running_processes(), allow_reuse=allow_reuse)
    if not decision.allowed:
        raise RuntimeError(decision.reason)
    return decision


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(PROCESS_GROUPS), required=True)
    parser.add_argument("--allow-reuse", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    decision = evaluate_launch(
        args.target,
        running_processes(),
        allow_reuse=args.allow_reuse,
    )
    print(json.dumps(asdict(decision), ensure_ascii=False, indent=2))
    return 0 if decision.allowed else 4


if __name__ == "__main__":
    raise SystemExit(main())
