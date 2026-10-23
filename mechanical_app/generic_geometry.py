"""Independent expression evaluation and layered 2-D CSG for the feature protocol.

No eval/exec, CAD calls, part-family lookup, or generated code is used. Circular
areas use GEOS polygons with 8192 edges; CAD comparisons allow 1e-5 relative
volume error. Coordinates and lengths are millimetres; angles are degrees.
"""
from __future__ import annotations

import ast
import copy
import math
import re

from .feature_contracts import Feature

PARAMETER_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
LENGTH_UNITS = {"mm", "cm", "m"}


def canonical_values(parameters: dict) -> tuple[dict, dict]:
    from .rules import to_mm
    values, units = {}, {}
    for name, item in parameters.items():
        if not PARAMETER_ID.fullmatch(name):
            raise ValueError(f"Invalid parameter name: {name}; use snake_case identifiers")
        if item["value"] is None:
            raise ValueError(f"Unknown parameter: {name}")
        unit = item["unit"]
        value = to_mm(item["value"], unit) if unit in LENGTH_UNITS else float(item["value"])
        if not math.isfinite(value) or abs(value) > 1_000_000:
            raise ValueError(f"Parameter outside finite numerical range: {name}")
        if unit == "count" and (value < 1 or not value.is_integer()):
            raise ValueError(f"Count must be a positive integer: {name}")
        values[name], units[name] = value, "mm" if unit in LENGTH_UNITS else unit
    return values, units


def expression(value, parameters: dict, units: dict, expected: str) -> float:
    """Evaluate only bounded arithmetic; track length/angle dimensions."""
    references = set()
    if isinstance(value, bool):
        raise ValueError("Boolean is not an engineering value")
    try:
        tree = ast.parse(str(value), mode="eval")
    except SyntaxError as exc:
        raise ValueError("Invalid arithmetic expression") from exc
    if len(list(ast.walk(tree))) > 80:
        raise ValueError("Engineering expression is too complex")

    def walk(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value), (0, 0)
        if isinstance(node, ast.Name) and node.id in parameters:
            references.add(node.id)
            unit = units[node.id]
            return parameters[node.id], ((1, 0) if unit == "mm" else (0, 1) if unit == "deg" else (0, 0))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result, dimension = walk(node.operand)
            return (-result if isinstance(node.op, ast.USub) else result), dimension
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            def constant_zero(item):
                return isinstance(item, ast.Constant) and type(item.value) in (int, float) and item.value == 0
            has_names = any(isinstance(item, ast.Name) for item in ast.walk(node))
            if has_names and ((isinstance(node.op, ast.Mult) and (constant_zero(node.left) or constant_zero(node.right)))
                              or (isinstance(node.op, ast.Div) and constant_zero(node.left))
                              or (isinstance(node.op, ast.Sub) and ast.dump(node.left) == ast.dump(node.right))):
                raise ValueError("Parameters must affect geometry; do not hide unused requirements with zero/cancelling expressions")
            a, da = walk(node.left); b, db = walk(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if da != db and not (a == 0 and da == (0, 0)) and not (b == 0 and db == (0, 0)):
                    raise ValueError("Cannot add dimensions with different units")
                return (a + b if isinstance(node.op, ast.Add) else a - b), (db if a == 0 and da == (0, 0) else da)
            if isinstance(node.op, ast.Mult):
                return a * b, tuple(x + y for x, y in zip(da, db))
            if b == 0:
                raise ValueError("Division by zero in engineering expression")
            return a / b, tuple(x - y for x, y in zip(da, db))
        raise ValueError("Only confirmed parameter names, numbers, + - * / and parentheses are allowed")

    result, dimension = walk(tree.body)
    wanted = {"length": (1, 0), "angle": (0, 1), "count": (0, 0)}[expected]
    if not math.isfinite(result) or abs(result) > 1_000_000:
        raise ValueError("Engineering expression is outside numerical range")
    # The geometric origin and reference angle may be zero without a dimension.
    if result != 0 and (not references or dimension != wanted):
        raise ValueError(f"Nonzero {expected} must reference confirmed parameters with matching units")
    if result == 0 and dimension not in ((0, 0), wanted):
        raise ValueError(f"Incorrect units for {expected}")
    return 0.0 if result == 0 else result


def resolve_features(features: list, values: dict, units: dict) -> list[dict]:
    if not features:
        raise ValueError("Describe at least one modeling feature; part names are unrestricted")
    if len(features) > 256:
        raise ValueError("This local execution has too many features; split the task")
    result, ids, referenced = [], set(), set()
    for raw in features:
        feature = Feature.model_validate(raw.model_dump() if isinstance(raw, Feature) else raw).model_dump()
        if feature["id"] in ids:
            raise ValueError("Feature IDs must be unique")
        ids.add(feature["id"])

        def resolve(value, role="length"):
            if isinstance(value, str):
                try:
                    parsed = ast.parse(value, mode="eval")
                except SyntaxError as exc:
                    raise ValueError("Invalid arithmetic expression") from exc
                referenced.update(n.id for n in ast.walk(parsed) if isinstance(n, ast.Name))
            return expression(value, values, units, role)

        p = feature["profile"]
        p["center"] = [resolve(v) for v in p["center"]]
        if p["kind"] == "circle":
            if p["diameter"] is None or p["size"] or p["points"]:
                raise ValueError("Circle requires diameter, empty size and empty points")
            p["diameter"] = resolve(p["diameter"])
            if p["diameter"] <= 0:
                raise ValueError("Circle diameter must be positive")
        elif p["kind"] == "rectangle":
            if p["diameter"] is not None or len(p["size"]) != 2 or p["points"]:
                raise ValueError("Rectangle requires exactly two sizes and no circle/polygon data")
            p["size"] = [resolve(v) for v in p["size"]]
            if min(p["size"]) <= 0:
                raise ValueError("Rectangle sizes must be positive")
        else:
            if p["diameter"] is not None or p["size"] or len(p["points"]) < 3:
                raise ValueError("Polygon requires at least three local points and no other shape data")
            p["points"] = [[resolve(v) for v in point] for point in p["points"]]
        feature["start"], feature["depth"] = resolve(feature["start"]), resolve(feature["depth"])
        if feature["depth"] <= 0 or feature["start"] < 0:
            raise ValueError("Extrusion depth must be positive; start must be nonnegative")
        if feature["pattern"]:
            pattern = feature["pattern"]
            pattern["count"] = resolve(pattern["count"], "count")
            if pattern["count"] < 1 or pattern["count"] > 256 or not pattern["count"].is_integer():
                raise ValueError("Pattern count must be an integer in the local execution budget 1..256")
            pattern["radius"] = resolve(pattern["radius"])
            pattern["angle_deg"] = resolve(pattern["angle_deg"], "angle")
            pattern["step"] = [resolve(v) for v in pattern["step"]]
            if pattern["kind"] == "circular" and (pattern["radius"] <= 0 or any(pattern["step"])):
                raise ValueError("Circular pattern requires positive radius and zero linear step")
            if pattern["kind"] == "linear" and (pattern["radius"] or pattern["angle_deg"] or not any(pattern["step"])):
                raise ValueError("Linear pattern requires nonzero step and zero radius/angle")
        result.append(feature)
    if result[0]["operation"] != "add":
        raise ValueError("The first feature must add material")
    unused = set(values) - referenced
    if unused:
        raise ValueError("Confirmed dimensions must not be silently ignored: " + ", ".join(sorted(unused)))
    if len(expand_features(result)) > 1024:
        raise ValueError("Too many feature instances for one local execution")
    return result


def expand_features(features: list[dict]) -> list[dict]:
    result = []
    for feature in features:
        pattern = feature.get("pattern")
        count = int(pattern["count"]) if pattern else 1
        for i in range(count):
            instance = copy.deepcopy(feature)
            instance["source_feature_id"] = feature["id"]
            instance["pattern"] = None
            if pattern:
                instance["id"] = f"{feature['id']}__{i + 1:03d}"
                if pattern["kind"] == "circular":
                    angle = math.radians(pattern["angle_deg"] + 360 * i / count)
                    delta = [pattern["radius"] * math.cos(angle), pattern["radius"] * math.sin(angle)]
                else:
                    delta = [i * v for v in pattern["step"]]
                instance["profile"]["center"] = [a + b for a, b in zip(feature["profile"]["center"], delta)]
            result.append(instance)
    return result


def parameter_bindings(recipe: list[dict], parameters: dict) -> dict[str, list[str]]:
    result = {name: [] for name in parameters}
    def visit(value, path):
        if isinstance(value, str):
            try:
                names = {node.id for node in ast.walk(ast.parse(value, mode="eval")) if isinstance(node, ast.Name)}
            except SyntaxError:
                return
            for name in names & set(parameters):
                result[name].append(path)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, f"{path}[{i}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in ("id", "kind", "operation"):
                    visit(item, f"{path}.{key}")
    for feature in recipe:
        visit(feature, feature["id"])
    return result


def expected_geometry(features: list[dict]) -> dict:
    from shapely.geometry import Point, Polygon, box
    instances = expand_features(features)
    breaks = sorted({float(f["start"]) for f in instances} | {float(f["start"] + f["depth"]) for f in instances})
    slabs = [[a, b, Polygon()] for a, b in zip(breaks, breaks[1:]) if b - a > 1e-9]
    history = []
    previous_volume = 0.0
    for f in instances:
        p = f["profile"]; x, y = p["center"]
        if p["kind"] == "circle":
            shape = Point(x, y).buffer(p["diameter"] / 2, quad_segs=2048)
        elif p["kind"] == "rectangle":
            w, h = p["size"]; shape = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
        else:
            shape = Polygon([(x + a, y + b) for a, b in p["points"]])
        if not shape.is_valid or shape.is_empty or shape.area <= 1e-10:
            raise ValueError(f"Invalid/self-intersecting profile: {f['id']}")
        for slab in slabs:
            middle = (slab[0] + slab[1]) / 2
            if f["start"] <= middle <= f["start"] + f["depth"]:
                slab[2] = slab[2].union(shape) if f["operation"] == "add" else slab[2].difference(shape)
        volume = sum((b - a) * geometry.area for a, b, geometry in slabs)
        delta = volume - previous_volume
        if (f["operation"] == "add" and delta <= 1e-8) or (f["operation"] == "cut" and delta >= -1e-8):
            raise ValueError(f"Feature has no material effect: {f['id']}")
        if volume <= 1e-8:
            raise ValueError(f"Feature removes the entire part: {f['id']}")
        history.append({"id": f["id"], "volume_mm3": volume, "delta_mm3": delta})
        previous_volume = volume
    active = [(a, b, g) for a, b, g in slabs if not g.is_empty and g.area > 1e-10]
    if not active:
        raise ValueError("No solid remains")
    # Connectivity in each slab and across adjacent slab faces; point/edge contact
    # is insufficient to join two three-dimensional solids.
    nodes = []
    for a, b, geometry in active:
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("CSG did not produce a regular solid section")
        for component in ([geometry] if geometry.geom_type == "Polygon" else geometry.geoms):
            nodes.append((a, b, component))
    parents = list(range(len(nodes)))
    def find(i):
        while parents[i] != i:
            i = parents[i]
        return i
    for i, (a, b, g) in enumerate(nodes):
        for j in range(i):
            c, d, h = nodes[j]
            if (abs(a - d) <= 1e-9 or abs(b - c) <= 1e-9) and g.intersection(h).area > 1e-9:
                parents[find(i)] = find(j)
    if len({find(i) for i in range(len(nodes))}) != 1:
        raise ValueError("Features form disconnected solids; define how the pieces join")
    low = [min(g.bounds[0] for _, _, g in active), min(g.bounds[1] for _, _, g in active), min(a for a, _, _ in active)]
    high = [max(g.bounds[2] for _, _, g in active), max(g.bounds[3] for _, _, g in active), max(b for _, b, _ in active)]
    return {"volume_mm3": previous_volume, "minimum_mm": low, "maximum_mm": high,
            "envelope_mm": [b - a for a, b in zip(low, high)], "steps": history,
            "independent_kernel": "Shapely/GEOS layered planar CSG; circles=8192 segments"}
