"""Deterministic readiness, normalization, capability and version rules."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contracts import (
    CADPlan, EngineeringTask, PARAMETER_NAMES, RuleViolation, operation_spec,
)
from .paths import PROJECT_ROOT, SKILL_PATH

LOCK_PATH = PROJECT_ROOT / "rules" / "lock.json"
LOCK = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
RULE_SET_VERSION = "engineering-rules/1"
FEATURE_RULE_SET_VERSION = "engineering-rules/2"
LOCKED_SKILL_SHA256: str = LOCK["skill_sha256"]
UNIT_FACTORS = {"mm": Decimal("1"), "cm": Decimal("10"), "m": Decimal("1000")}


class TaskRejected(ValueError):
    def __init__(self, violations: list[RuleViolation]):
        self.violations = violations
        super().__init__("; ".join(f"{v.code} ({v.path}): {v.message}" for v in violations))


def _error(code: str, path: str, message: str) -> RuleViolation:
    return RuleViolation(code=code, path=path, message=message)


def _shape_errors(exc: ValidationError) -> list[RuleViolation]:
    return [_error("contract_invalid", ".".join(map(str, e["loc"])), e["msg"])
            for e in exc.errors(include_url=False)]


def to_mm(value: float, unit: str) -> float:
    """Decimal multiplication makes equivalent mm/cm/m inputs canonical."""
    return float(Decimal(str(value)) * UNIT_FACTORS[unit])


def verify_skill_lock() -> list[RuleViolation]:
    errors = []
    for relative, expected in LOCK["files"].items():
        path = SKILL_PATH.parent / relative
        if not path.is_file():
            errors.append(_error("skill_lock_missing", relative, "Locked skill file is missing"))
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(_error("skill_lock_changed", relative, "Skill changed; explicit rule migration is required"))
    return errors


def _geometry_errors(family: str, p: dict[str, float], tolerance_mm: float) -> list[RuleViolation]:
    errors = []
    if any(not math.isfinite(v) or v <= 0 or v > 1_000_000 for v in p.values()):
        return [_error("dimension_range", "parameters", "Dimensions must be >0 and <=1,000,000 mm")]
    # Distinct holes must not touch each other or the boundary.
    if family == "plate":
        r, margin, d = p["hole_diameter"] / 2, p["hole_margin"], p["hole_diameter"]
        if margin - r <= tolerance_mm:
            errors.append(_error("hole_breakout", "parameters.hole_margin", "Four through holes must remain strictly inside the plate"))
        if min(p["length"] - 2 * margin, p["width"] - 2 * margin) - d <= tolerance_mm:
            errors.append(_error("hole_overlap", "parameters.hole_margin", "Four corner holes must be distinct and separated"))
    elif family == "bracket":
        if min(p["length"], p["height"]) - p["thickness"] <= tolerance_mm:
            errors.append(_error("bracket_thickness", "parameters.thickness", "L-section thickness must be smaller than both leg dimensions"))
    elif family == "box":
        if min(p["length"], p["width"]) - 2 * p["wall"] <= tolerance_mm or p["height"] - p["wall"] <= tolerance_mm:
            errors.append(_error("box_wall", "parameters.wall", "Open-top box needs a positive internal cavity and floor"))
    return errors


def _feature_errors(task: EngineeringTask) -> list[RuleViolation]:
    from .generic_geometry import canonical_values, resolve_features, expected_geometry
    try:
        values, units = canonical_values({name: p.model_dump() for name, p in task.parameters.items()})
        features = resolve_features([feature.model_dump() for feature in task.features], values, units)
        expected_geometry(features)
    except (ValueError, SyntaxError, KeyError, TypeError, OverflowError) as exc:
        return [_error("feature_invalid", "features", str(exc))]
    return []


def validate_task(
    task: EngineeringTask | dict[str, Any], *,
    expected_revision: int | None = None,
    expected_baseline_hash: str | None = None,
    verify_lock: bool = True,
) -> list[RuleViolation]:
    """Return blockers; [] means ready for this pilot's geometry stage only.

    expected_revision is the CURRENT ledger revision (0 for a new design),
    not the incoming revision. The service must pass it for every submission.
    """
    try:
        task = EngineeringTask.model_validate(task.model_dump() if isinstance(task, EngineeringTask) else task)
    except ValidationError as exc:
        return _shape_errors(exc)
    errors: list[RuleViolation] = []
    if verify_lock:
        errors.extend(verify_skill_lock())
    if task.skill_sha256 != LOCKED_SKILL_SHA256:
        errors.append(_error("skill_version", "skill_sha256", "Task does not target the locked mechanical-design skill"))
    general = task.schema_version == "engineering-task/2"
    names = set(task.parameters) if general else set(PARAMETER_NAMES[task.family])
    if general and not names:
        errors.append(_error("parameter_set", "parameters", "Record the dimensions needed by this design"))
    if set(task.parameters) != names:
        errors.append(_error("parameter_set", "parameters", f"Required keys are {sorted(names)}; no extra dimensions are supported"))
    sources = {source.id: source for source in task.sources}
    if len(sources) != len(task.sources):
        errors.append(_error("duplicate_source", "sources", "Source IDs must be unique"))
    normalized = {}
    for name, parameter in task.parameters.items():
        path = f"parameters.{name}"
        if parameter.value is None:
            errors.append(_error("unknown_parameter", path + ".value", "A required dimension is unknown; do not invent a value"))
        else:
            normalized[name] = to_mm(parameter.value, parameter.unit) if parameter.unit in UNIT_FACTORS else float(parameter.value)
        if not parameter.confirmed:
            errors.append(_error("unconfirmed_parameter", path + ".confirmed", "Dimension requires an authoritative confirmed source"))
        source = sources.get(parameter.source_id or "")
        if source is None:
            errors.append(_error("source_missing", path + ".source_id", "Parameter must refer to a recorded source ID"))
        elif source.kind in ("rule", "derived"):
            errors.append(_error("proposal_unconfirmed", path + ".source_id", "A rule or derived proposal cannot assert user confirmation"))
    if set(normalized) == names:
        errors.extend(_feature_errors(task) if general else _geometry_errors(task.family, normalized, task.tolerance_mm))
    for name, expected in task.hard_constraints.items():
        if name not in names:
            errors.append(_error("constraint_unknown", f"hard_constraints.{name}", "Constraint targets an unsupported parameter"))
        elif not math.isfinite(expected) or (not general and expected <= 0):
            errors.append(_error("constraint_invalid", f"hard_constraints.{name}", "Constraint must use a finite canonical parameter value"))
        elif name in normalized and not math.isclose(normalized[name], expected, rel_tol=0, abs_tol=1e-9):
            errors.append(_error("constraint_conflict", f"parameters.{name}", "Dimension changes a protected hard constraint"))
    if len(set(task.deliverables)) != len(task.deliverables) or "native" not in task.deliverables:
        errors.append(_error("deliverables", "deliverables", "Use unique deliverables including native save/reopen"))
    if task.action == "create":
        if task.revision != 1 or task.baseline is not None:
            errors.append(_error("invalid_create_version", "baseline", "Creation is revision 1 with no baseline"))
        if expected_revision not in (None, 0) or expected_baseline_hash is not None:
            errors.append(_error("stale_baseline", "baseline", "Creation cannot replace an existing design"))
    else:
        if task.baseline is None:
            errors.append(_error("baseline_missing", "baseline", "A modification must reference the previous revision and hash"))
        elif task.revision != task.baseline.revision + 1:
            errors.append(_error("revision_sequence", "revision", "Incoming revision must immediately follow its baseline"))
        if expected_revision is not None and (task.baseline is None or task.baseline.revision != expected_revision):
            errors.append(_error("stale_revision", "baseline.revision", "Baseline differs from the current ledger revision"))
        if expected_baseline_hash is not None and (task.baseline is None or task.baseline.semantic_hash != expected_baseline_hash):
            errors.append(_error("stale_baseline", "baseline.semantic_hash", "Baseline hash differs from the ledger"))
    return errors


def semantic_payload(plan: CADPlan | dict) -> dict:
    """Only execution semantics; no task ID, revision, narrative or provenance."""
    p = plan.model_dump() if isinstance(plan, CADPlan) else plan
    payload = {key: p[key] for key in (
        "family", "scope", "parameters_mm", "operations", "deliverables",
        "hard_constraints_mm", "tolerance_mm", "rule_set_version", "skill_sha256",
    )}
    if p["schema_version"] == "cad-plan/2":
        payload.update({key: p[key] for key in ("feature_recipe", "features", "parameter_values", "parameter_units", "parameter_bindings")})
    return payload


def semantic_hash(plan: CADPlan | dict) -> str:
    payload = semantic_payload(plan)
    # Deliverable ordering is not a semantic difference.
    payload["deliverables"] = sorted(payload["deliverables"])
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate_plan(plan: CADPlan | dict, *, verify_lock: bool = True) -> list[RuleViolation]:
    """Reject a modified plan before COM access, including allowed-op tampering."""
    try:
        plan = CADPlan.model_validate(plan.model_dump() if isinstance(plan, CADPlan) else plan)
    except ValidationError as exc:
        return _shape_errors(exc)
    errors = verify_skill_lock() if verify_lock else []
    if plan.skill_sha256 != LOCKED_SKILL_SHA256:
        errors.append(_error("skill_version", "skill_sha256", "Plan does not target the locked skill"))
    if plan.semantic_hash != semantic_hash(plan):
        errors.append(_error("plan_tampered", "semantic_hash", "Plan hash does not match execution semantics"))
    if plan.schema_version == "cad-plan/2":
        from .generic_geometry import expected_geometry
        try:
            expected_geometry([feature.model_dump() for feature in plan.features])
        except (ValueError, SyntaxError, KeyError, TypeError, OverflowError) as exc:
            errors.append(_error("feature_invalid", "features", str(exc)))
    else:
        errors.extend(_geometry_errors(plan.family, plan.parameters_mm, plan.tolerance_mm))
    values = plan.parameter_values if plan.schema_version == "cad-plan/2" else plan.parameters_mm
    for name, value in plan.hard_constraints_mm.items():
        if name not in values or not math.isclose(values[name], value, rel_tol=0, abs_tol=1e-9):
            errors.append(_error("constraint_conflict", "hard_constraints_mm." + name, "Plan violates a protected dimension"))
    if plan.baseline is None and plan.revision != 1:
        errors.append(_error("baseline_missing", "baseline", "Only revision 1 may omit a baseline"))
    elif plan.baseline is not None and plan.revision != plan.baseline.revision + 1:
        errors.append(_error("revision_sequence", "revision", "Plan revision must follow its baseline"))
    return errors


def compile_plan(task: EngineeringTask | dict[str, Any]) -> CADPlan:
    errors = validate_task(task)
    if errors:
        raise TaskRejected(errors)
    task = EngineeringTask.model_validate(task.model_dump() if isinstance(task, EngineeringTask) else task)
    general = task.schema_version == "engineering-task/2"
    extras = {}
    if general:
        from .generic_geometry import canonical_values, resolve_features, parameter_bindings
        values, units = canonical_values({name: parameter.model_dump() for name, parameter in task.parameters.items()})
        recipe = [feature.model_dump() for feature in task.features]
        p = {name: value for name, value in values.items() if units[name] == "mm"}
        extras = {"parameter_values": values, "parameter_units": units, "feature_recipe": recipe,
                  "features": resolve_features(recipe, values, units), "parameter_bindings": parameter_bindings(recipe, values)}
    else:
        p = {name: to_mm(task.parameters[name].value, task.parameters[name].unit)
             for name in PARAMETER_NAMES[task.family]}
    data = dict(
        schema_version="cad-plan/2" if general else "cad-plan/1", task_id=task.task_id, revision=task.revision,
        family=task.family, scope=task.scope, parameters_mm=p,
        operations=operation_spec(task.family, p, task.deliverables, general=general),
        baseline=task.baseline.model_dump() if task.baseline else None,
        deliverables=sorted(task.deliverables), hard_constraints_mm=task.hard_constraints,
        tolerance_mm=task.tolerance_mm, rule_set_version=task.rule_set_version,
        skill_sha256=task.skill_sha256,
        **extras,
    )
    data["semantic_hash"] = semantic_hash(data)
    return CADPlan.model_validate(data)
