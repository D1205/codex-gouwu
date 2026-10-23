"""Headless product interface used before any UI is introduced."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .storage import read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
DEFAULT_STORE = WORKSPACE / "results" / "mechanical-design-app" / "runtime"


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(description="mechanical-design verified task adapter")
    commands = app.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema", help="Export the task and CAD plan JSON Schemas")
    schema.add_argument("--output", type=Path, default=PROJECT / "schemas")
    validate = commands.add_parser("validate", help="Validate a task and compile its deterministic CAD plan")
    validate.add_argument("task", type=Path)
    validate.add_argument("--output", type=Path)
    interpret = commands.add_parser("interpret", help="Call the real local Codex bridge for a requirement draft")
    interpret.add_argument("--brief", required=True)
    interpret.add_argument("--current-task", type=Path)
    interpret.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="Run a confirmed engineering task in the real CAD backend")
    run.add_argument("task", type=Path)
    run.add_argument("--store", type=Path, default=DEFAULT_STORE)
    run.add_argument("--major", type=int)
    change = commands.add_parser("change", help="Create a new version from an explicit parameter change")
    change.add_argument("task_id")
    change.add_argument("parameter_id")
    change.add_argument("value", type=float)
    change.add_argument("--unit", default="mm", choices=["mm", "cm", "m"])
    change.add_argument("--expected-revision", type=int, required=True)
    change.add_argument("--selection", type=Path)
    change.add_argument("--store", type=Path, default=DEFAULT_STORE)
    change.add_argument("--major", type=int)
    status = commands.add_parser("status")
    status.add_argument("task_id")
    status.add_argument("--store", type=Path, default=DEFAULT_STORE)
    review = commands.add_parser("review", help="Record observations after viewing the native CAD previews")
    review.add_argument("job_id")
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--notes", required=True)
    review.add_argument("--store", type=Path, default=DEFAULT_STORE)
    return app


def execute(args: argparse.Namespace) -> dict:
    if args.command == "schema":
        from .contracts import CADPlan, EngineeringTask
        files = []
        for model, name in ((EngineeringTask, "engineering-task-v1.schema.json"), (CADPlan, "cad-plan-v1.schema.json")):
            path = args.output / name
            write_json(path, model.model_json_schema())
            files.append(str(path.resolve()))
        return {"status": "passed", "schemas": files}
    if args.command == "validate":
        from .contracts import EngineeringTask
        from .rules import compile_plan
        plan = compile_plan(EngineeringTask.model_validate(read_json(args.task))).model_dump(mode="json")
        if args.output:
            write_json(args.output, plan)
        return {"status": "ready", "plan": plan}
    if args.command == "interpret":
        from .agent import interpret_brief
        current = read_json(args.current_task) if args.current_task else None
        result = interpret_brief(args.brief, current_task=current, output_dir=args.output.parent)
        write_json(args.output, result)
        return result
    from .service import DesignService
    service = DesignService(args.store)
    if args.command == "run":
        return service.submit(read_json(args.task), major=args.major)
    if args.command == "change":
        selection = read_json(args.selection) if args.selection else None
        return service.parameter_change(args.task_id, args.parameter_id, args.value, args.unit,
                                        args.expected_revision, selection=selection, major=args.major)
    if args.command == "review":
        return service.complete_review(args.job_id, approved=args.approve, reviewer=args.reviewer, notes=args.notes)
    current = service.current(args.task_id)
    return {"status": "found" if current else "missing", "current": current}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if result.get("status") in {"failed", "blocked", "missing"} else 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
