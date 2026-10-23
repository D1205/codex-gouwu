"""Read-only saved-profile qualification using existing live pilot artifacts."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mechanical_app.cad import _sw, artifact, preflight
from mechanical_app.cad_features import native_feature_readback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--major", type=int, default=30)
    args = parser.parse_args()
    source = json.loads(args.report.read_text(encoding="utf-8"))
    result = {"status": "running", "source_report": artifact(args.report, "source_report"),
              "preflight": preflight(), "cases": []}
    api = _sw()
    api["pythoncom"].CoInitialize()
    owner = None
    try:
        app, revision = api["attach"](args.major)
        api["major"] = int(revision.split(".")[0])
        owner = api["DocumentOwnership"](app)
        owner.require_empty()
        for case in source["cases"]:
            native = next(item for item in case["artifacts"] if item["kind"] == "native")
            if artifact(Path(native["path"]), "native")["sha256"] != native["sha256"]:
                raise RuntimeError("Pilot artifact was modified before saved-profile readback")
            instances = copy.deepcopy(case["feature_execution"])
            for instance in instances:
                instance.setdefault("native_sketch", instance["native_name"] + "_Profile")
            model, warning = api["open_owned"](app, owner, native["path"], 1)
            profiles = native_feature_readback(model, api, {"instances": instances}, 0.01)
            owner.close(model)
            unchanged = artifact(Path(native["path"]), "native")["sha256"] == native["sha256"]
            if not unchanged:
                raise RuntimeError("Readback changed a native artifact")
            result["cases"].append({"task_id": case["task_id"], "status": "passed", "native": native,
                                    "profiles": profiles, "native_bytes_preserved": unchanged, "reopen_warning": warning})
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if owner:
            owner.close_all()
            result["final_documents"] = api["open_document_report"](app)
        api["pythoncom"].CoUninitialize()
    path = args.report.with_name("saved-profile-readback.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "cases": len(result["cases"]), "error": result.get("error"), "report": str(path)}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
