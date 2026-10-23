"""Small, allowlisted SolidWorks adapter. All lengths at this boundary are mm.

This module never launches CAD, executes generated code, or edits a baseline.
Revisions are regenerated into new directories; native feature parameters and
semantic IDs are preserved by name, not by transient mesh/face indexes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from .paths import HELPERS, PROJECT_ROOT

PROJECT = PROJECT_ROOT
PARAMETERS = {
    "plate": {"length", "width", "height", "hole_diameter", "hole_margin"},
    "bracket": {"length", "width", "height", "thickness"},
    "box": {"length", "width", "height", "wall"},
}
NOT_COVERED = ["manufacturability", "material selection", "strength and load capacity",
               "assembly and motion", "production drawing and tolerancing",
               "physical prototype acceptance", "arbitrary face/edge selection"]


def _write(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def artifact(path: Path, kind: str) -> dict:
    stat = path.stat()
    if not stat.st_size:
        raise RuntimeError(f"Empty artifact: {path}")
    return {"kind": kind, "path": str(path.resolve()), "size_bytes": stat.st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def _validate(plan: dict) -> tuple[str, dict]:
    from .rules import validate_plan
    violations = validate_plan(plan)
    if violations:
        raise ValueError("; ".join(f"{v.code}: {v.message}" for v in violations))
    # One source of truth: no second set of dimension limits or operation rules.
    return plan["family"], dict(plan["parameters_mm"])


def preflight() -> dict:
    """Read-only dependency/resource checks; no package installation or CAD launch."""
    reports = {}
    for filename, args in (("sw_preflight.py", ["--no-install"]),
                           ("sw_resource_guard.py", ["--target", "solidworks", "--allow-reuse"])):
        run = _helper_process(filename, args)
        reports[filename] = {"returncode": run.returncode, "stdout": run.stdout.strip(), "stderr": run.stderr.strip()}
        if run.returncode:
            raise RuntimeError(f"{filename} failed: {run.stdout} {run.stderr}")
    guard = json.loads(reports["sw_resource_guard.py"]["stdout"])
    if not guard.get("reuse_existing"):
        raise RuntimeError("No running SolidWorks. This adapter only attaches; start one instance first.")
    return reports


def _helper_process(filename: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run read-only helpers with either Python or our frozen GUI executable.

    GUI executables have no stdout/stderr streams. The frozen dispatcher writes
    one temporary JSON report so output capture does not depend on a console.
    """
    if not getattr(sys, "frozen", False):
        return subprocess.run([sys.executable, str(HELPERS / filename), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=45,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    with tempfile.TemporaryDirectory(prefix="codex-gouwu-preflight-") as directory:
        report_path = Path(directory) / "report.json"
        command = [sys.executable, "--helper", filename, "--helper-result", str(report_path), "--", *args]
        run = subprocess.run(command, timeout=45,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if not report_path.is_file():
            raise RuntimeError(f"Packaged helper did not write a report: {filename} (exit {run.returncode})")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(command, run.returncode, report["stdout"], report["stderr"])


@contextmanager
def _exclusive(root: Path):
    path = root / ".cad-execution.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"CAD execution already locked: {path}; inspect owning process before clearing") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def _sw():
    if str(HELPERS) not in sys.path:
        sys.path.insert(0, str(HELPERS))
    import pythoncom
    from win32com.client import VARIANT
    from sw_connect import get_com_member
    from sw_documents import DocumentOwnership, import_owned, new_owned, open_document_report, open_owned
    from sw_inspect import add_named_dimension, fully_define_active_sketch, snapshot
    from sw_part import end_sketch, extrude_boss, extrude_cut, sketch_circle, sketch_corner_rectangle, sketch_line, start_sketch
    from sw_review import save_preview
    from sw_runtime import attach, default_template, early_bound, no_dimension_input_dialog
    return locals()


def _sketch(model, api, name, build):
    api["start_sketch"](model, "Front Plane")
    active = model.SketchManager.ActiveSketch
    active.Name = name
    try:
        dimensions = build()
        # The upstream helper's default datum is English; resolve the localized
        # origin before calling it, without changing the reusable helper library.
        null = api["VARIANT"](api["pythoncom"].VT_DISPATCH, None)
        datum = None
        for origin in ("Origin", "原点"):
            for point in ("Point1", "点1"):
                candidate = f"{point}@{origin}"
                if model.Extension.SelectByID2(candidate, "EXTSKETCHPOINT", 0, 0, 0, False, 6, null, 0):
                    datum = candidate
                    break
            if datum:
                break
        if not datum:
            raise RuntimeError("No localized origin point could be selected")
        state = api["fully_define_active_sketch"](model, datum=datum)
    finally:
        api["end_sketch"](model)
    return name, dimensions, state


def _dimension(api, model, entity, value, name, x, y):
    full_name = api["add_named_dimension"](model, entity, value / 1000, name, x / 1000, y / 1000)
    # FullName may contain @UnsavedPart.Part; that suffix changes on SaveAs.
    return "@".join(full_name.split("@")[:2])


def _rectangle(api, model, x, y, length, width, name):
    # Create explicit linked lines so named dimensions map to semantic horizontal/vertical edges.
    points = [(x, y), (x + length, y), (x + length, y + width), (x, y + width)]
    lines = [api["sketch_line"](model, a[0] / 1000, a[1] / 1000, b[0] / 1000, b[1] / 1000)
             for a, b in zip(points, points[1:] + points[:1])]
    if any(line is None for line in lines):
        raise RuntimeError("Rectangle line creation failed")
    return {f"{name}.length": _dimension(api, model, lines[0], length, f"{name}Length", x + length / 2, y - 5),
            f"{name}.width": _dimension(api, model, lines[1], width, f"{name}Width", x + length + 5, y + width / 2)}


def _build(model, api, family, p):
    features, dimensions, sketches = {}, {}, []

    def profile(name, builder):
        sketch, dims, status = _sketch(model, api, name, builder)
        dimensions.update(dims)
        sketches.append(status)
        return sketch

    def boss(sketch, depth, name):
        feature = api["extrude_boss"](model, sketch, depth / 1000, direction=False)
        feature.Name = name
        features[name] = str(api["get_com_member"](feature, "GetTypeName2"))
        dimensions[f"{name}.depth"] = f"D1@{name}"
        api["snapshot"](model)
        return feature

    if family == "bracket":
        def section():
            length, height, t = p["length"], p["height"], p["thickness"]
            points = [(0, 0), (length, 0), (length, t), (t, t), (t, height), (0, height)]
            lines = [api["sketch_line"](model, a[0] / 1000, a[1] / 1000, b[0] / 1000, b[1] / 1000)
                     for a, b in zip(points, points[1:] + points[:1])]
            return {"length": _dimension(api, model, lines[0], length, "Length", length / 2, -5),
                    "height": _dimension(api, model, lines[5], height, "Height", -5, height / 2),
                    "thickness": _dimension(api, model, lines[1], t, "Thickness", length + 5, t / 2)}
        boss(profile("MD_LSection", section), p["width"], "MD_Base")
    else:
        boss(profile("MD_Outline", lambda: _rectangle(api, model, 0, 0, p["length"], p["width"], "Outer")),
             p["height"] if family == "plate" else p["wall"], "MD_Base")
        if family == "plate":
            def holes():
                values = {}
                for index, (x, y) in enumerate(_hole_centers(p), 1):
                    circle = api["sketch_circle"](model, x / 1000, y / 1000, p["hole_diameter"] / 2000)
                    values[f"hole_{index}.diameter"] = _dimension(api, model, circle, p["hole_diameter"], f"HoleDiameter{index}", x + 6, y + 6)
                return values
            hole_sketch = profile("MD_Holes", holes)
            cut = api["extrude_cut"](model, hole_sketch, 0, direction=True)
            cut.Name = "MD_HolesThrough"
            features[cut.Name] = str(api["get_com_member"](cut, "GetTypeName2"))
            api["snapshot"](model)
        else:
            def walls():
                dims = _rectangle(api, model, 0, 0, p["length"], p["width"], "WallOuter")
                dims.update(_rectangle(api, model, p["wall"], p["wall"], p["length"] - 2 * p["wall"], p["width"] - 2 * p["wall"], "WallInner"))
                return dims
            boss(profile("MD_WallProfile", walls), p["height"], "MD_Walls")
    return {"features": features, "dimensions": dimensions, "sketches": sketches}


def _hole_centers(p):
    m, length, width = p["hole_margin"], p["length"], p["width"]
    return [(m, m), (length - m, m), (length - m, width - m), (m, width - m)]


def _expected(family, p):
    l, w, h = p["length"], p["width"], p["height"]
    if family == "plate":
        volume = (l * w - math.pi * p["hole_diameter"] ** 2) * h
        envelope = [l, w, h]
    elif family == "bracket":
        t = p["thickness"]
        volume, envelope = (l * t + h * t - t * t) * w, [l, h, w]
    else:
        t = p["wall"]
        volume, envelope = l * w * h - (l - 2 * t) * (w - 2 * t) * (h - t), [l, w, h]
    return volume, envelope


def _measure(model, api):
    snap = api["snapshot"](model)
    if snap["bodies"] != 1:
        raise RuntimeError(f"Expected one solid body, got {snap['bodies']}")
    body = list(model.GetBodies2(0, False))[0]
    low, high = [], []
    for axis in range(3):
        for sign, target in ((-1, low), (1, high)):
            vector = [0.0, 0.0, 0.0]
            vector[axis] = sign
            # Generated pywin32 method returns (success, outx, outy, outz).
            coordinates = body.GetExtremePoint(*vector)
            if not isinstance(coordinates, tuple) or len(coordinates) != 4 or not coordinates[0]:
                raise RuntimeError("Exact body extreme point unavailable")
            target.append(float(coordinates[axis + 1]) * 1000)
    cylinders = []
    for face in list(api["get_com_member"](body, "GetFaces") or []):
        surface = api["get_com_member"](face, "GetSurface")
        if api["get_com_member"](surface, "IsCylinder"):
            values = list(api["get_com_member"](surface, "CylinderParams"))
            box = list(api["get_com_member"](face, "GetBox"))
            cylinders.append({"axis_origin_mm": [v * 1000 for v in values[:3]],
                              "axis_direction": list(values[3:6]), "diameter_mm": values[6] * 2000,
                              "bounds_mm": [v * 1000 for v in box],
                              "area_mm2": float(api["get_com_member"](face, "GetArea")) * 1e6})
    return {"snapshot": snap, "origin_mm": low, "maximum_mm": high,
            "envelope_mm": [b - a for a, b in zip(low, high)],
            "volume_mm3": snap["mass"]["volume_m3"] * 1e9, "cylinders": cylinders}


def _check_geometry(measure, family, p, tolerance, add, prefix):
    volume, envelope = _expected(family, p)
    snap = measure["snapshot"]
    add(prefix + ".rebuild", snap["rebuild"] is True, snap["rebuild"], True)
    add(prefix + ".body_count", snap["bodies"] == 1, snap["bodies"], 1)
    errors = [f for f in snap["features"] if f["error"] != 0]
    add(prefix + ".feature_health", not errors, errors, [])
    add(prefix + ".volume", math.isclose(measure["volume_mm3"], volume, rel_tol=1e-6, abs_tol=1e-4), measure["volume_mm3"], volume)
    add(prefix + ".envelope", all(abs(a - b) <= tolerance for a, b in zip(measure["envelope_mm"], envelope)), measure["envelope_mm"], envelope)
    add(prefix + ".origin", all(abs(a) <= tolerance for a in measure["origin_mm"]), measure["origin_mm"], [0, 0, 0])
    if family == "plate":
        cylinders = measure["cylinders"]
        expected = _hole_centers(p)
        matched = []
        for x, y in expected:
            matches = [c for c in cylinders if abs(c["axis_origin_mm"][0] - x) <= tolerance
                       and abs(c["axis_origin_mm"][1] - y) <= tolerance
                       and abs(c["diameter_mm"] - p["hole_diameter"]) <= tolerance
                       and abs(abs(c["axis_direction"][2]) - 1) <= 1e-8
                       and abs(c["bounds_mm"][2]) <= tolerance
                       and abs(c["bounds_mm"][5] - p["height"]) <= tolerance]
            # STEP commonly splits one periodic cylinder into two half-faces.
            # Group by axis/diameter and require full cylindrical area, not a
            # particular face count imposed by one export/import implementation.
            matched.append(bool(matches) and math.isclose(sum(c["area_mm2"] for c in matches),
                           math.pi * p["hole_diameter"] * p["height"], rel_tol=1e-6))
        allowed = sum(1 for c in cylinders if any(abs(c["axis_origin_mm"][0] - x) <= tolerance
                      and abs(c["axis_origin_mm"][1] - y) <= tolerance for x, y in expected))
        add(prefix + ".four_through_holes", allowed == len(cylinders) and all(matched), cylinders,
            {"diameter_mm": p["hole_diameter"], "centers_mm": expected, "z_range_mm": [0, p["height"]]})


def _save(model, path, api):
    errors = api["VARIANT"](api["pythoncom"].VT_BYREF | api["pythoncom"].VT_I4, 0)
    warnings = api["VARIANT"](api["pythoncom"].VT_BYREF | api["pythoncom"].VT_I4, 0)
    null = api["VARIANT"](api["pythoncom"].VT_DISPATCH, None)
    ok = model.Extension.SaveAs(str(path), 0, 1, null, errors, warnings)
    if not ok or errors.value:
        raise RuntimeError(f"SaveAs failed: {path}, ok={ok}, errors={errors.value}, warnings={warnings.value}")
    artifact(path, path.suffix)
    return {"errors": int(errors.value), "warnings": int(warnings.value)}


def _native_readback(model, api, build, family):
    readback = {"dimensions_mm": {}, "sketches": [], "features": {}}
    for key, name in build["dimensions"].items():
        dimension = model.Parameter(name)
        if dimension is None:
            raise RuntimeError(f"Named native dimension missing: {name}")
        readback["dimensions_mm"][key] = float(dimension.SystemValue) * 1000
    for state in build["sketches"]:
        feature = model.FeatureByName(state["sketch"])
        sketch = api["get_com_member"](feature, "GetSpecificFeature2")
        status = int(api["get_com_member"](sketch, "GetConstrainedStatus"))
        if status != 3:
            raise RuntimeError(f"Reopened sketch not fully defined: {state['sketch']}, {status}")
        readback["sketches"].append({"name": state["sketch"], "constrained_status": status})
    for name, kind in build["features"].items():
        feature = model.FeatureByName(name)
        actual = str(api["get_com_member"](feature, "GetTypeName2"))
        if actual != kind:
            raise RuntimeError(f"Native feature identity changed: {name}")
        readback["features"][name] = actual
    if family == "plate":
        definition = api["get_com_member"](model.FeatureByName("MD_HolesThrough"), "GetDefinition")
        end = int(definition.GetEndCondition(True))
        if end != 1:
            raise RuntimeError(f"Hole end condition is not ThroughAll: {end}")
        readback["hole_end_condition"] = end
    return readback


def _stl_bounds(path):
    data = path.read_bytes()
    vertices = []
    if len(data) >= 84 and len(data) == 84 + 50 * struct.unpack_from("<I", data, 80)[0]:
        count = struct.unpack_from("<I", data, 80)[0]
        for i in range(count):
            coords = struct.unpack_from("<12f", data, 84 + i * 50)
            vertices.extend([coords[3:6], coords[6:9], coords[9:12]])
    else:
        for line in data.decode("ascii").splitlines():
            if line.strip().startswith("vertex "):
                vertices.append(tuple(map(float, line.split()[1:])))
    if not vertices:
        raise RuntimeError("STL contains no triangles")
    return {"minimum": [min(v[i] for v in vertices) for i in range(3)],
            "maximum": [max(v[i] for v in vertices) for i in range(3)], "triangles": len(vertices) // 3}


@contextmanager
def _stl_preferences(app, *, deviation_mm=None):
    integers = {211: 0}  # swExportStlUnits=swMM, read from installed swconst typelib.
    doubles = {}
    if deviation_mm is not None:
        # Curved v2 geometry needs an explicit chord tolerance: default STL
        # tessellation may shrink a circular envelope past the task tolerance.
        # swSTLQuality_Custom=3 (official swSTLQuality_e), not Fine=2.
        integers[78] = 3
        doubles = {2: deviation_mm / 1000, 3: math.radians(5)}
    toggles = {69: True, 70: False, 71: True}  # binary; no info dialog; preserve origin.
    old_int = {k: app.GetUserPreferenceIntegerValue(k) for k in integers}
    old_double = {k: app.GetUserPreferenceDoubleValue(k) for k in doubles}
    old_toggle = {k: app.GetUserPreferenceToggle(k) for k in toggles}
    try:
        for k, v in integers.items():
            if not app.SetUserPreferenceIntegerValue(k, v):
                raise RuntimeError(f"Could not set temporary STL integer preference {k}")
        for k, v in doubles.items():
            if not app.SetUserPreferenceDoubleValue(k, v):
                raise RuntimeError(f"Could not set temporary STL double preference {k}")
        for k, v in toggles.items():
            app.SetUserPreferenceToggle(k, v)
        yield
    finally:
        for k, v in old_int.items():
            app.SetUserPreferenceIntegerValue(k, v)
        for k, v in old_double.items():
            app.SetUserPreferenceDoubleValue(k, v)
        for k, v in old_toggle.items():
            app.SetUserPreferenceToggle(k, v)


def _mapping(plan, build, native):
    if plan.get("schema_version") == "cad-plan/2":
        from .cad_features import semantic_mapping
        return semantic_mapping(plan, build, native)
    p, family, task = plan["parameters_mm"], plan["family"], plan["task_id"]
    features = [{"feature_id": f"{task}/feature/{name}", "native_name": name, "native_type": kind}
                for name, kind in build["features"].items()]
    markers = []
    if family == "plate":
        for i, (x, y) in enumerate(_hole_centers(p), 1):
            markers.append({"feature_id": f"{task}/hole/{i}", "parameter_id": f"{task}/parameter/hole_diameter",
                            "position_mm": [x, y, p["height"]], "native_dimension": build["dimensions"][f"hole_{i}.diameter"]})
    return {"schema_version": "semantic-mapping/1", "task_id": task, "instance_id": f"{task}/body/main",
            "revision": plan["revision"], "semantic_hash": plan["semantic_hash"],
            "model_sha256": native["sha256"], "native_sha256": native["sha256"], "preview_revision": plan["revision"],
            "units": "mm", "coordinate_system": "right-handed; XY sketch; positive Z extrusion; origin lower-left-bottom",
            "selection_mode": "semantic_parameter_markers_only", "features": features,
            "parameters": [{"parameter_id": f"{task}/parameter/{key}", "name": key, "value_mm": value}
                           for key, value in p.items()], "markers": markers, "native_dimensions": build["dimensions"]}


def execute_plan(plan: dict, output_dir: Path, *, major: int | None = None) -> dict:
    """Execute one validated family, saving a fresh task/revision directory.

    Caller's ledger must validate baseline revision/hash and immutable artifact hash
    before calling. This adapter never modifies/opens a supplied baseline: changes
    are explicitly regenerated. A global process lock serializes owned COM work.
    """
    started = time.monotonic()
    result = {"status": "failed", "task_id": plan.get("task_id"), "revision": plan.get("revision"),
              "semantic_hash": plan.get("semantic_hash"),
              "checks": [], "artifacts": [], "mapping": None, "not_covered": NOT_COVERED,
              "runtime": {"adapter": "solidworks-agent-native", "mode": "regenerated" if plan.get("baseline") else "new"}}
    owner, run_dir = None, None

    def add(key, passed, actual, expected):
        result["checks"].append({"id": key, "status": "passed" if passed else "failed", "actual": actual, "expected": expected})
        if not passed:
            raise AssertionError(f"CAD check failed: {key}")

    try:
        family, p = _validate(plan)
        generic = plan.get("schema_version") == "cad-plan/2"
        basename = "part" if generic else family
        if generic:
            from .cad_features import build_features, check_geometry
            from .generic_geometry import expected_geometry
            prediction = expected_geometry(plan["features"])
            result["expected_geometry"] = prediction

        def verify(measure, prefix):
            if generic:
                check_geometry(measure, prediction, plan.get("tolerance_mm", 0.01), add, prefix)
            else:
                _check_geometry(measure, family, p, plan.get("tolerance_mm", 0.01), add, prefix)

        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        run_dir = root / plan["task_id"] / f"r{plan['revision']}"
        run_dir.mkdir(parents=True, exist_ok=False)
        _write(run_dir / "plan.json", plan)
        result["runtime"]["preflight"] = preflight()
        with _exclusive(Path(os.environ.get("TEMP", str(root)))):
            api = _sw()
            api["pythoncom"].CoInitialize()
            app, revision = api["attach"](major)
            api["major"] = int(revision.split(".")[0])
            result["runtime"]["solidworks_revision"] = revision
            result["runtime"]["initial_documents"] = api["open_document_report"](app)
            owner = api["DocumentOwnership"](app)
            owner.require_empty()  # Stop safely if a human opened a document in the meantime.
            try:
                with api["no_dimension_input_dialog"](app):
                    model = api["new_owned"](app, owner, api["default_template"](app, "part"))
                    build = build_features(model, api, plan) if generic else _build(model, api, family, p)
                    if generic:
                        result["feature_execution"] = build["instances"]
                        result["runtime"]["feature_api_references"] = build["api_references"]
                    result["geometry"] = _measure(model, api)
                    verify(result["geometry"], "created")
                    native_path = run_dir / f"{basename}.SLDPRT"
                    result["runtime"]["native_save"] = _save(model, native_path, api)
                    result["artifacts"].append(artifact(native_path, "native"))
                    owner.close(model)
                    model, warning = api["open_owned"](app, owner, native_path, 1)
                    result["runtime"]["reopen_warning"] = warning
                    reopened = _measure(model, api)
                    verify(reopened, "reopened")
                    result["native_readback"] = _native_readback(model, api, build, "__generic__" if generic else family)
                    add("reopened.fully_defined_sketches", True, result["native_readback"]["sketches"], "all status 3")
                    if generic:
                        from .cad_features import native_feature_readback
                        result["native_readback"]["feature_contracts"] = native_feature_readback(
                            model, api, build, plan.get("tolerance_mm", 0.01))
                        add("reopened.feature_contracts", True, result["native_readback"]["feature_contracts"],
                            "blind depths, signed starts and positive-Z directions match the plan")
                    if family == "plate" and not generic:
                        add("reopened.native_through_all", True, result["native_readback"]["hole_end_condition"], 1)
                    if "step" in plan["deliverables"]:
                        step = run_dir / f"{basename}.step"
                        _save(model, step, api)
                        result["artifacts"].append(artifact(step, "step"))
                        # Import neutral geometry independently, with no source model open.
                        owner.close(model)
                        imported = api["import_owned"](app, owner, step)
                        imported_measure = _measure(imported, api)
                        verify(imported_measure, "step_readback")
                        owner.close(imported)
                        model, _ = api["open_owned"](app, owner, native_path, 1)
                    if "preview" in plan["deliverables"]:
                        stl = run_dir / f"{basename}.stl"
                        deviation = min(plan.get("tolerance_mm", 0.01) / 4, 0.0025) if generic else None
                        with _stl_preferences(app, deviation_mm=deviation):
                            _save(model, stl, api)
                        if generic:
                            result["runtime"]["stl_tessellation"] = {"quality": "custom", "deviation_mm": deviation,
                                                                    "angle_tolerance_deg": 5,
                                                                    "reference": "https://help.solidworks.com/2024/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSTLQuality_e.html"}
                        stl_box = _stl_bounds(stl)
                        expected_box = prediction["maximum_mm"] if generic else _expected(family, p)[1]
                        expected_min = prediction["minimum_mm"] if generic else [0, 0, 0]
                        stl_tolerance = plan.get("tolerance_mm", 0.01) if generic else 0.01
                        add("preview.stl_units_and_origin", all(abs(a - b) <= stl_tolerance for a, b in zip(stl_box["maximum"], expected_box))
                            and all(abs(a - b) <= stl_tolerance for a, b in zip(stl_box["minimum"], expected_min)), stl_box,
                            {"units": "mm", "minimum": expected_min, "maximum": expected_box})
                        result["artifacts"].append(artifact(stl, "stl"))
                        from PIL import Image, ImageStat
                        for view in ("isometric", "front", "top", "right"):
                            bmp = run_dir / f"{basename}-{view}.bmp"
                            api["save_preview"](model, bmp, view, width=1400, height=1000)
                            png = bmp.with_suffix(".png")
                            with Image.open(bmp) as image:
                                add(f"preview.{view}.nonblank", max(ImageStat.Stat(image.convert("RGB")).stddev) > 3,
                                    image.size, "nonblank 1400x1000 native CAD capture")
                                image.save(png)
                            bmp.unlink()
                            result["artifacts"].append(artifact(png, f"preview_{view}"))
                    result["mapping"] = _mapping(plan, build, result["artifacts"][0])
                    mapping = run_dir / "mapping.json"
                    _write(mapping, result["mapping"])
                    result["artifacts"].append(artifact(mapping, "mapping"))
                    if "preview" in plan["deliverables"]:
                        result["visual_review"] = {"status": "pending", "scope": "Agent must inspect exported PNGs before release"}
                owner.close_all()
                result["runtime"]["final_documents"] = api["open_document_report"](app)
                result["status"] = "passed"
            finally:
                if owner:
                    try:
                        owner.close_all()
                    except Exception as exc:
                        result["runtime"]["cleanup_error"] = repr(exc)
                        result["status"] = "failed"
                api["pythoncom"].CoUninitialize()
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["runtime"]["traceback"] = traceback.format_exc()
    result["runtime"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if run_dir is not None and run_dir.exists() and not (run_dir / "result.json").exists():
        _write(run_dir / "result.json", result)
    return result
