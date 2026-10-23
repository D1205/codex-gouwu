"""Focused live pilot: three families, preserved baseline, hole-diameter revision.

Execute with the automation-skill virtualenv from this project root.
Does not install dependencies, launch SolidWorks, or run upstream suites.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mechanical_app.cad import execute_plan
from mechanical_app.contracts import EngineeringTask
from mechanical_app.rules import LOCKED_SKILL_SHA256, compile_plan


def task(family, values):
    return EngineeringTask.model_validate({
        "task_id": "pilot-" + family, "revision": 1, "action": "create", "family": family,
        "goal": "Authored technical verification dimensions; geometry review only",
        "sources": [{"id": "test", "kind": "user", "reference": "Explicit synthetic pilot case, not a production design"}],
        "parameters": {k: {"value": float(v), "unit": "mm", "source_id": "test", "confirmed": True} for k, v in values.items()},
        "hard_constraints": {k: float(v) for k, v in values.items() if k != "hole_diameter"},
        "baseline": None, "deliverables": ["native", "step", "preview"], "skill_sha256": LOCKED_SKILL_SHA256,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results" / ("cad-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--major", type=int, default=None)
    parser.add_argument("--family", choices=["all", "plate", "bracket", "box"], default="all")
    args = parser.parse_args()
    values = {
        "plate": {"length": 80, "width": 50, "height": 4, "hole_diameter": 4, "hole_margin": 10},
        "bracket": {"length": 60, "width": 30, "height": 40, "thickness": 4},
        "box": {"length": 80, "width": 50, "height": 30, "wall": 2},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "geometry_review", "cases": [], "checks": []}
    for family, parameters in values.items():
        if args.family not in ("all", family):
            continue
        authored = task(family, parameters)
        plan = compile_plan(authored).model_dump(mode="json")
        print(f"START {family}", flush=True)
        result = execute_plan(plan, args.output, major=args.major)
        report["cases"].append(result)
        print(json.dumps({"family": family, "revision": 1, "status": result["status"], "error": result.get("error")}), flush=True)
        if result["status"] != "passed":
            break
        if family == "plate":
            before = {a["path"]: a["sha256"] for a in result["artifacts"]}
            changed = authored.model_dump(mode="json")
            changed.update(revision=2, action="modify", baseline={"revision": 1, "semantic_hash": plan["semantic_hash"]})
            changed["parameters"]["hole_diameter"]["value"] = 6.0
            changed_plan = compile_plan(changed).model_dump(mode="json")
            revised = execute_plan(changed_plan, args.output, major=args.major)
            report["cases"].append(revised)
            preserved = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())
            report["checks"].append({"id": "baseline_bytes_preserved", "status": "passed" if preserved else "failed", "actual": preserved})
            semantic = result["mapping"]
            new_semantic = revised.get("mapping") or {}
            ids_stable = revised["status"] == "passed" and semantic["instance_id"] == new_semantic.get("instance_id") and [m["feature_id"] for m in semantic["markers"]] == [m["feature_id"] for m in new_semantic.get("markers", [])]
            report["checks"].append({"id": "stable_semantic_identity", "status": "passed" if ids_stable else "failed", "actual": ids_stable})
            print(json.dumps({"family": family, "revision": 2, "status": revised["status"], "error": revised.get("error")}), flush=True)
            if revised["status"] != "passed" or not preserved or not ids_stable:
                break
    passed = bool(report["cases"]) and all(c["status"] == "passed" for c in report["cases"]) and all(c["status"] == "passed" for c in report["checks"])
    report["status"] = "passed" if passed else "failed"
    path = args.output / "cad-verification.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path.resolve()), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
