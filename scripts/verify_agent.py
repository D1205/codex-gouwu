"""A bounded live Codex smoke test; no recorded/model-mocked results are accepted."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mechanical_app.agent import interpret_brief, probe_cli
from mechanical_app.rules import compile_plan


def verify_modification(task_file: Path, output_dir: Path, timeout: int) -> int:
    """One new live request, using an already verified task as the baseline."""
    previous_result = json.loads(task_file.read_text(encoding="utf-8"))
    task = previous_result.get("task", previous_result)
    previous_plan = compile_plan(task)
    output_dir.mkdir(parents=True, exist_ok=True)
    selection = {
        "parameter_id": "hole_diameter", "revision": task["revision"],
        "semantic_hash": previous_plan.semantic_hash,
    }
    result = interpret_brief(
        "把这四个贯穿孔的直径改成6毫米，外形和孔位不变。",
        current_task=task, selection=selection, output_dir=output_dir, timeout=timeout,
    )
    checks = []
    report = {
        "schema_version": "agent-modification-verification/1", "mode": "live_codex_cli",
        "model_call_limit": 1, "status": "failed", "baseline_task_path": str(task_file),
        "selection": selection, "result": result, "checks": checks,
        "not_covered": ["CAD execution", "arbitrary face/edge selection", "general modification language"],
    }
    if result["status"] == "ready":
        revised = result["task"]
        plan = compile_plan(revised)
        old_sources = {source["id"]: source for source in task["sources"]}
        new_sources = {source["id"]: source for source in revised["sources"]}
        baseline_matches = revised["baseline"] == {"revision": task["revision"], "semantic_hash": previous_plan.semantic_hash}
        unchanged = all(
            plan.parameters_mm[name] == value
            for name, value in previous_plan.parameters_mm.items() if name != "hole_diameter"
        )
        source_preserved = all(
            new_sources[revised["parameters"][name]["source_id"]]["reference"]
            == old_sources[task["parameters"][name]["source_id"]]["reference"]
            for name in task["parameters"] if name != "hole_diameter"
        )
        checks.extend([
            {"id": "ready_from_real_model", "status": "passed" if result["runtime"]["model_invoked"] else "failed"},
            {"id": "same_task_next_revision", "status": "passed" if revised["task_id"] == task["task_id"] and revised["action"] == "modify" and revised["revision"] == task["revision"] + 1 else "failed"},
            {"id": "exact_baseline", "status": "passed" if baseline_matches else "failed"},
            {"id": "only_hole_diameter_changes", "status": "passed" if unchanged and plan.parameters_mm["hole_diameter"] == 6.0 else "failed", "actual_mm": plan.parameters_mm},
            {"id": "unchanged_source_provenance", "status": "passed" if source_preserved else "failed"},
        ])
        task_path = output_dir / "task-revision-2.json"
        task_path.write_text(json.dumps(revised, ensure_ascii=False, indent=2), encoding="utf-8")
        report["ready_task_path"] = str(task_path)
        report["status"] = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    else:
        report["error"] = result["error"] or {"code": "not_ready", "message": result["questions"]}
        if (result["error"] or {}).get("code") in {"model_timeout", "model_call_failed", "cli_unavailable"}:
            report["status"] = "blocked"
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path), "checks": checks}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("results/agent-verification"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--modify-from", type=Path, help="Run only one live modification against a saved ready result/task")
    args = parser.parse_args()
    if args.modify_from:
        return verify_modification(args.modify_from, args.output_dir, args.timeout)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "agent-verification/1", "status": "blocked", "mode": "live_codex_cli",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model_call_limit": 3, "checks": [], "cases": [],
        "not_covered": ["CAD execution", "manufacturability", "strength", "arbitrary natural-language coverage"],
    }
    try:
        report["probe"] = probe_cli()
        if not report["probe"]["available"]:
            report["error"] = "CLI version/schema support or existing login is unavailable; no model call was made"
        else:
            cases = [
                ("plate_mm", "建一个80×50×4毫米的矩形底板，四个直径5毫米的贯穿孔，每个孔中心距相邻两条边都是10毫米。只做几何评审。"),
                ("plate_cm", "画底板，长度8厘米、宽度5厘米、厚度0.4厘米；四个直径0.5厘米的通孔，中心距相邻边1厘米。做几何评审。"),
                ("box_missing_wall", "做一个无盖的空心长方形盒体，外部长80毫米、宽50毫米、高30毫米。底厚等于侧壁厚，只做几何评审。"),
            ]
            for case_id, brief in cases:
                result = interpret_brief(brief, output_dir=args.output_dir / case_id, timeout=args.timeout)
                report["cases"].append({"id": case_id, "result": result})
                if result["status"] == "failed":
                    code = (result.get("error") or {}).get("code")
                    report["status"] = "blocked" if code in {"cli_unavailable", "model_call_failed", "model_timeout"} else "failed"
                    report["error"] = result["error"]
                    break
            else:
                first, second, missing = [case["result"] for case in report["cases"]]
                ready = first["status"] == second["status"] == "ready"
                report["checks"].append({"id": "explicit_dimensions_ready", "status": "passed" if ready else "failed"})
                if ready:
                    p1, p2 = compile_plan(first["task"]), compile_plan(second["task"])
                    equivalent = p1.semantic_hash == p2.semantic_hash
                    exact = p1.parameters_mm == {
                        "length": 80.0, "width": 50.0, "height": 4.0, "hole_diameter": 5.0, "hole_margin": 10.0,
                    }
                    report["checks"].extend([
                        {"id": "equivalent_units_same_semantics", "status": "passed" if equivalent else "failed", "hashes": [p1.semantic_hash, p2.semantic_hash]},
                        {"id": "explicit_dimensions_match", "status": "passed" if exact else "failed", "actual": p1.parameters_mm},
                    ])
                wall = ((missing.get("task") or {}).get("parameters") or {}).get("wall")
                missing_safe = (
                    missing["status"] == "needs_input" and bool(missing["questions"])
                    and wall is not None and wall["value"] is None and wall["confirmed"] is False
                )
                report["checks"].append({"id": "missing_wall_not_invented", "status": "passed" if missing_safe else "failed", "actual": wall})
                live = all(case["result"]["runtime"]["model_invoked"] for case in report["cases"])
                report["checks"].append({"id": "three_real_model_calls", "status": "passed" if live else "failed"})
                report["status"] = "passed" if all(check["status"] == "passed" for check in report["checks"]) else "failed"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report_path = args.output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path), "checks": report["checks"]}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
