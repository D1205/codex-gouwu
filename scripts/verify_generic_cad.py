"""Focused live qualification of feature plans; no launch or source-model edits.

The cases are explicitly authored synthetic dimensions, not manufacturing designs.
Results preserve native, neutral, previews, and prior failed attempt evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mechanical_app.cad import execute_plan
from mechanical_app.rules import LOCKED_SKILL_SHA256, compile_plan


def circle(diameter, center=None):
    return {"kind": "circle", "center": center or [0.0, 0.0], "diameter": diameter, "size": [], "points": []}


def feature(id, operation, profile, start, depth, pattern=None):
    return {"id": id, "operation": operation, "profile": profile,
            "start": start, "depth": depth, "pattern": pattern}


def task(name, values, features):
    return {"schema_version": "engineering-task/2", "task_id": "generic-pilot-" + name,
            "revision": 1, "action": "create", "family": name,
            "goal": "Authored geometry-only live feature qualification",
            "scope": "geometry_review", "rule_set_version": "engineering-rules/2",
            "sources": [{"id": "test", "kind": "user", "reference": "Explicit synthetic verification dimensions"}],
            "parameters": {key: {"value": float(value[0]) if isinstance(value, tuple) else float(value),
                                  "unit": value[1] if isinstance(value, tuple) else "mm",
                                  "source_id": "test", "confirmed": True} for key, value in values.items()},
            "features": features, "hard_constraints": {}, "baseline": None,
            "deliverables": ["native", "step", "preview"], "tolerance_mm": 0.01,
            "skill_sha256": LOCKED_SKILL_SHA256}


def cases():
    yield task("flange", {
        "outer_diameter": 100, "thickness": 10, "center_bore": 30,
        "bolt_diameter": 8, "pitch_diameter": 70, "bolt_count": (4, "count"),
        "recess_diameter": 40, "recess_depth": 3,
    }, [
        feature("disc", "add", circle("outer_diameter"), 0.0, "thickness"),
        feature("center_hole", "cut", circle("center_bore"), 0.0, "thickness"),
        feature("bolt_holes", "cut", circle("bolt_diameter"), 0.0, "thickness",
                {"kind": "circular", "count": "bolt_count", "radius": "pitch_diameter/2",
                 "angle_deg": 0.0, "step": [0.0, 0.0]}),
        feature("upper_recess", "cut", circle("recess_diameter"), "thickness-recess_depth", "recess_depth"),
    ])
    yield task("stepped-shaft", {"base_diameter": 40, "base_length": 20, "tip_diameter": 24, "tip_length": 30}, [
        feature("base", "add", circle("base_diameter"), 0.0, "base_length"),
        feature("tip", "add", circle("tip_diameter"), "base_length", "tip_length"),
    ])
    hexagon = {"kind": "polygon", "center": [0.0, 0.0], "diameter": None, "size": [],
               "points": [["radius", 0.0], ["radius/2", "radius*0.8660254037844386"],
                          ["-radius/2", "radius*0.8660254037844386"], ["-radius", 0.0],
                          ["-radius/2", "-radius*0.8660254037844386"], ["radius/2", "-radius*0.8660254037844386"]]}
    yield task("hexagonal-spacer", {"radius": 12, "length": 18, "bore": 8}, [
        feature("hexagon", "add", hexagon, 0.0, "length"),
        feature("bore", "cut", circle("bore"), 0.0, "length"),
    ])
    yield task("mounting-block", {"length": 60, "width": 30, "height": 12,
                                  "hole_diameter": 6, "hole_pitch": 20, "hole_count": (3, "count")}, [
        feature("block", "add", {"kind": "rectangle", "center": [0.0, 0.0], "diameter": None,
                                   "size": ["length", "width"], "points": []}, 0.0, "height"),
        feature("row_of_holes", "cut", circle("hole_diameter", ["-hole_pitch", 0.0]), 0.0, "height",
                {"kind": "linear", "count": "hole_count", "radius": 0.0,
                 "angle_deg": 0.0, "step": ["hole_pitch", 0.0]}),
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results" / ("generic-cad-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--major", type=int, default=30)
    parser.add_argument("--case", default="all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "geometry_review", "cases": [], "status": "running"}
    path = args.output / "generic-cad-verification.json"
    for authored in cases():
        if args.case not in ("all", authored["family"]):
            continue
        plan = compile_plan(authored).model_dump(mode="json")
        print("START " + authored["family"], flush=True)
        result = execute_plan(plan, args.output, major=args.major)
        report["cases"].append(result)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"family": authored["family"], "status": result["status"],
                          "checks": len(result["checks"]), "error": result.get("error")}), flush=True)
        if result["status"] != "passed":
            break
    report["status"] = "passed" if report["cases"] and all(r["status"] == "passed" for r in report["cases"]) else "failed"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(str(path.resolve()), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
