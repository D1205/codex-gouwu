"""Execute the version-2, numeric feature contract in an owned SolidWorks part.

Part names never select code paths. The only operations executed here are the
validated planar profiles and positive-Z blind extrusions in the CAD plan.
No generated program, macro, external model, or user filename is executed.
"""
from __future__ import annotations

import math
import re


API_REFERENCES = {
    "start_offset": "https://help.solidworks.com/2023/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swStartConditions_e.html",
    "cut": "https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ifeaturemanager~featurecut4.html",
}


def _name(value: str) -> str:
    # Prefix and digest-like source IDs are retained semantically in the mapping;
    # the native tree uses only safe, deterministic identifiers.
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _extrude(model, api, sketch_name: str, feature: dict):
    """Same native helper calls, with a qualified swStartOffset extension.

    The front-plane normal is +Z. Boss Dir=False and cut Dir=True both travel
    +Z; start offset is signed independently of the operation direction.
    """
    from sw_part import _ensure_sketch_selected

    start = float(feature["start"])
    depth = float(feature["depth"]) / 1000
    t0 = 3 if start else 0  # swStartConditions_e.swStartOffset
    offset, reverse = abs(start) / 1000, start < 0
    try:
        _ensure_sketch_selected(model, sketch_name)
        if feature["operation"] == "add":
            native = model.FeatureManager.FeatureExtrusion3(
                True, False, False, 0, 0, depth, 0.0,
                False, False, False, False, 0.0, 0.0,
                False, False, False, False, True, False, True,
                t0, offset, reverse)
        else:
            native = model.FeatureManager.FeatureCut4(
                True, False, True, 0, 0, depth, 0.0,
                False, False, False, False, 0.0, 0.0,
                False, False, False, False, False,
                True, True, True, True, False, t0, offset, reverse, False)
        if native is None or native is False:
            raise RuntimeError(f"Native blind extrusion returned no feature: {feature['id']}")
        return native
    finally:
        model.ClearSelection2(True)


def build_features(model, api, plan: dict) -> dict:
    from .cad import _dimension, _rectangle, _sketch
    from .generic_geometry import expand_features, expected_geometry

    features, dimensions, sketches, instances = {}, {}, [], []
    names = set()
    predictions = expected_geometry(plan["features"])["steps"]
    for index, primitive in enumerate(expand_features(plan["features"]), 1):
        native_name = f"MD_{index:03d}_{_name(primitive['id'])}"
        if native_name in names:
            raise RuntimeError("Native feature name collision")
        names.add(native_name)
        profile = primitive["profile"]
        cx, cy = profile["center"]

        def draw():
            if profile["kind"] == "circle":
                circle = api["sketch_circle"](model, cx / 1000, cy / 1000, profile["diameter"] / 2000)
                if circle is None:
                    raise RuntimeError("Circle creation failed")
                return {f"{native_name}.diameter": _dimension(
                    api, model, circle, profile["diameter"], "Diameter", cx + profile["diameter"] / 2 + 5, cy + 5)}
            if profile["kind"] == "rectangle":
                width, height = profile["size"]
                return _rectangle(api, model, cx - width / 2, cy - height / 2,
                                  width, height, native_name)
            points = [(cx + x, cy + y) for x, y in profile["points"]]
            for a, b in zip(points, points[1:] + points[:1]):
                line = api["sketch_line"](model, a[0] / 1000, a[1] / 1000, b[0] / 1000, b[1] / 1000)
                if line is None:
                    raise RuntimeError("Polygon line creation failed")
            # FullyDefineSketch adds coordinate/angle driving dimensions without
            # changing polygon vertices. Volume/bounds are checked independently.
            return {}

        sketch_name, dims, sketch_state = _sketch(model, api, native_name + "_Profile", draw)
        dimensions.update(dims)
        sketches.append(sketch_state)
        native = _extrude(model, api, sketch_name, primitive)
        native.Name = native_name
        features[native_name] = str(api["get_com_member"](native, "GetTypeName2"))
        dimensions[f"{native_name}.depth"] = f"D1@{native_name}"
        instances.append({"feature_id": primitive.get("source_feature_id", primitive["id"]),
                          "instance_id": primitive["id"], "native_name": native_name,
                          "native_sketch": sketch_name,
                          "profile": profile, "start": primitive["start"], "depth": primitive["depth"],
                          "operation": primitive["operation"]})
        state = api["snapshot"](model)
        errors = [entry for entry in state["features"] if entry["error"] != 0]
        actual_volume = state["mass"]["volume_m3"] * 1e9
        expected_volume = predictions[index - 1]["volume_mm3"]
        if errors or not math.isclose(actual_volume, expected_volume, rel_tol=1e-5, abs_tol=1e-4):
            raise RuntimeError(f"Feature {primitive['id']} differs from independent CSG: "
                               f"volume={actual_volume}, expected={expected_volume}, feature_errors={errors}")
        instances[-1]["verification"] = {"volume_mm3": actual_volume,
                                          "expected_volume_mm3": expected_volume,
                                          "body_count": state["bodies"], "feature_errors": errors}
    return {"features": features, "dimensions": dimensions, "sketches": sketches,
            "instances": instances, "api_references": API_REFERENCES}


def check_geometry(measure, expected: dict, tolerance: float, add, prefix: str):
    state = measure["snapshot"]
    errors = [feature for feature in state["features"] if feature["error"] != 0]
    add(prefix + ".rebuild", state["rebuild"] is True, state["rebuild"], True)
    add(prefix + ".body_count", state["bodies"] == 1, state["bodies"], 1)
    add(prefix + ".feature_health", not errors, errors, [])
    add(prefix + ".volume", math.isclose(measure["volume_mm3"], expected["volume_mm3"], rel_tol=1e-5, abs_tol=1e-4),
        measure["volume_mm3"], expected["volume_mm3"])
    # Compare both high/low boundaries. Equal envelopes alone can hide a shifted
    # part and negative coordinates are valid in the version-2 contract.
    add(prefix + ".envelope", all(abs(a - b) <= tolerance for a, b in zip(measure["maximum_mm"], expected["maximum_mm"]))
        and all(abs(a - b) <= tolerance for a, b in zip(measure["envelope_mm"], expected["envelope_mm"])),
        {"maximum_mm": measure["maximum_mm"], "envelope_mm": measure["envelope_mm"]},
        {"maximum_mm": expected["maximum_mm"], "envelope_mm": expected["envelope_mm"]})
    add(prefix + ".origin", all(abs(a - b) <= tolerance for a, b in zip(measure["origin_mm"], expected["minimum_mm"])),
        measure["origin_mm"], expected["minimum_mm"])


def native_feature_readback(model, api, build, tolerance):
    """Read saved native start/depth/direction, including blind pocket placement."""
    rows = []
    for instance in build["instances"]:
        feature = model.FeatureByName(instance["native_name"])
        definition = api["get_com_member"](feature, "GetDefinition")
        end = int(definition.GetEndCondition(True))
        depth = float(definition.GetDepth(True)) * 1000
        reverse = bool(api["get_com_member"](definition, "ReverseDirection"))
        start_kind = int(api["get_com_member"](definition, "FromType"))
        start = 0.0
        if instance["start"]:
            start = float(api["get_com_member"](definition, "FromOffsetDistance")) * 1000
            if api["get_com_member"](definition, "FromOffsetReverse"):
                start *= -1
        expected_reverse = instance["operation"] == "cut"
        expected_start_kind = 3 if instance["start"] else 0
        if (end != 0 or abs(depth - instance["depth"]) > tolerance
                or reverse != expected_reverse or start_kind != expected_start_kind
                or abs(start - instance["start"]) > tolerance):
            raise RuntimeError(f"Saved extrusion contract changed: {instance['native_name']}; "
                               f"end={end}, depth={depth}, reverse={reverse}, from={start_kind}, start={start}")
        profile = _profile_readback(model, api, instance, tolerance)
        rows.append({"native_name": instance["native_name"], "end_condition": end,
                     "depth_mm": depth, "reverse_direction": reverse,
                     "start_condition": start_kind, "start_mm": start, "profile": profile})
    return rows


def _profile_readback(model, api, instance, tolerance):
    """Prove saved centers/vertices, which mass and overall bounds cannot locate."""
    sketch_feature = model.FeatureByName(instance["native_sketch"])
    sketch = api["get_com_member"](sketch_feature, "GetSpecificFeature2")
    segments = list(api["get_com_member"](sketch, "GetSketchSegments") or [])
    profile = instance["profile"]

    def point(value):
        return [float(api["get_com_member"](value, axis)) * 1000 for axis in ("X", "Y")]

    def close(a, b):
        return all(abs(x - y) <= tolerance for x, y in zip(a, b))

    if profile["kind"] == "circle":
        if len(segments) != 1 or int(api["get_com_member"](segments[0], "GetType")) != 1:
            raise RuntimeError("Saved circle sketch does not contain exactly one arc")
        arc = api["early_bound"](segments[0], "ISketchArc", api["major"])
        center = point(api["get_com_member"](arc, "GetCenterPoint2"))
        diameter = float(api["get_com_member"](arc, "GetRadius")) * 2000
        if not close(center, profile["center"]) or abs(diameter - profile["diameter"]) > tolerance:
            raise RuntimeError(f"Saved circle center/diameter differs: {instance['native_sketch']}")
        return {"kind": "circle", "center_mm": center, "diameter_mm": diameter}

    cx, cy = profile["center"]
    if profile["kind"] == "rectangle":
        w, h = profile["size"]
        vertices = [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2],
                    [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]]
    else:
        vertices = [[cx + x, cy + y] for x, y in profile["points"]]
    expected_edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    edges = []
    for segment in segments:
        if int(api["get_com_member"](segment, "GetType")) != 0:
            raise RuntimeError("Saved polygon sketch contains a non-line segment")
        line = api["early_bound"](segment, "ISketchLine", api["major"])
        edges.append([point(api["get_com_member"](line, "GetStartPoint2")),
                      point(api["get_com_member"](line, "GetEndPoint2"))])
    if len(edges) != len(expected_edges) or not all(
            any((close(a, x) and close(b, y)) or (close(a, y) and close(b, x)) for a, b in edges)
            for x, y in expected_edges):
        raise RuntimeError(f"Saved polygon vertices differ: {instance['native_sketch']}")
    return {"kind": profile["kind"], "edges_mm": edges}


def semantic_mapping(plan, build, native):
    task = plan["task_id"]
    units = plan.get("parameter_units", {})
    values = plan.get("parameter_values", plan["parameters_mm"])
    bindings = plan.get("parameter_bindings", {})
    instances = build["instances"]
    feature_rows = [
        {"feature_id": f"{task}/feature/{instance['feature_id']}",
         "instance_id": f"{task}/feature-instance/{instance['instance_id']}",
         "native_name": instance["native_name"],
         "native_type": build["features"][instance["native_name"]],
         "operation": instance["operation"], "profile_kind": instance["profile"]["kind"]}
        for instance in instances]
    parameters, markers = [], []
    for key, value in values.items():
        unit = units.get(key, "mm")
        parameter = {"parameter_id": f"{task}/parameter/{key}", "name": key,
                     "value": value, "unit": unit, "bindings": bindings.get(key, [])}
        if unit == "mm":
            parameter["value_mm"] = value
        parameters.append(parameter)
        for instance in instances:
            source_id = instance["feature_id"]
            paths = bindings.get(key, [])
            if not any(path == source_id or path.startswith(source_id + ".") for path in paths):
                continue
            markers.append({"feature_id": f"{task}/feature/{source_id}",
                            "instance_id": f"{task}/feature-instance/{instance['instance_id']}",
                            "parameter_id": parameter["parameter_id"],
                            "position_mm": [*instance["profile"]["center"], instance["start"] + instance["depth"]],
                            "native_feature": instance["native_name"], "binding_paths": paths})
    return {"schema_version": "semantic-mapping/2", "task_id": task,
            "instance_id": f"{task}/body/main", "revision": plan["revision"],
            "semantic_hash": plan["semantic_hash"], "model_sha256": native["sha256"],
            "native_sha256": native["sha256"], "preview_revision": plan["revision"],
            "units": "mm", "coordinate_system": "right-handed; XY sketch; positive Z extrusion; signed world origin",
            "selection_mode": "semantic_parameter_markers_only", "features": feature_rows,
            "parameters": parameters, "markers": markers, "native_dimensions": build["dimensions"]}
