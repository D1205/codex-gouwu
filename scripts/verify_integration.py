"""Connect real model-produced tasks to the real CAD service, with explicit visual review."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from mechanical_app.service import DesignService, RevisionConflict
from mechanical_app.storage import read_json, sha256, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["create", "modify", "summarize"])
    parser.add_argument("--store", type=Path, default=PROJECT / "results" / "integration")
    args = parser.parse_args()
    service = DesignService(args.store)
    agent_report = PROJECT / "results" / "agent-verification-proxy" / "report.json"
    agent = read_json(agent_report)
    assert agent["status"] == "passed"
    original = agent["cases"][0]["result"]
    assert original["status"] == "ready" and original["runtime"]["model_invoked"] is True
    task_id = original["task"]["task_id"]
    if args.phase == "create":
        write_json(args.store / "input-provenance.json", {"source": str(agent_report), "sha256": sha256(agent_report),
                   "model_invoked": True, "task_id": task_id})
        result = service.submit(original["task"], major=30)
        write_json(args.store / "create-job.json", result)
    elif args.phase == "modify":
        report = read_json(PROJECT / "results" / "agent-modification" / "report.json")
        assert report["status"] == "passed", "Real language modification did not pass"
        task = read_json(PROJECT / "results" / "agent-modification" / "task-revision-2.json")
        assert task["task_id"] == task_id and task["revision"] == 2
        result = service.submit(task, major=30)
        write_json(args.store / "modify-job.json", result)
    else:
        first = read_json(args.store / "create-job.json")
        second = read_json(args.store / "modify-job.json")
        first_job = read_json(args.store / "jobs" / f"{first['job_id']}.json")
        second_job = read_json(args.store / "jobs" / f"{second['job_id']}.json")
        state = service.current(task_id)
        checks = []
        def check(name, passed):
            checks.append({"id": name, "status": "passed" if passed else "failed"})
        check("live_language_to_cad_revision_1", first_job["status"] == "passed")
        check("live_language_modification_to_cad_revision_2", second_job["status"] == "passed")
        check("published_current_revision", state is not None and state["revision"] == 2)
        first_result, second_result = first_job["result"], second_job["result"]
        first_native = next(a for a in first_result["artifacts"] if a["kind"] == "native")
        check("baseline_bytes_preserved", sha256(Path(first_native["path"])) == first_native["sha256"])
        check("stable_instance_identity", first_result["mapping"]["instance_id"] == second_result["mapping"]["instance_id"])
        rejected = False
        try:
            service.parameter_change(task_id, "hole_diameter", 7.0, "mm", expected_revision=1)
        except RevisionConflict:
            rejected = True
        check("stale_revision_refused_before_cad", rejected)
        result = {"schema_version": "integration-verification/1",
                  "status": "passed" if all(c["status"] == "passed" for c in checks) else "failed",
                  "checks": checks, "task_id": task_id, "current": state,
                  "not_covered": ["arbitrary imported CAD", "manufacturing", "strength", "motion", "physical prototype"]}
        write_json(args.store / "report.json", result)
    import json
    print(json.dumps({"status": result["status"], "job_id": result.get("job_id"), "task_id": task_id,
                      "result": result.get("result_path"), "error": result.get("error"), "checks": result.get("checks")}, ensure_ascii=False))
    return 0 if result["status"] in {"passed", "review_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
