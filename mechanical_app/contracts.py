"""Strict data contracts. Parsing a task does not authorize CAD execution."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .feature_contracts import Feature

Family = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")]
Unit = Literal["mm", "cm", "m", "deg", "count"]
SourceKind = Literal["user", "rule", "derived", "cad", "spec"]
Deliverable = Literal["native", "step", "preview"]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")]
Number = Annotated[float, Field(allow_inf_nan=False)]
PARAMETER_NAMES: dict[str, tuple[str, ...]] = {
    "plate": ("length", "width", "height", "hole_diameter", "hole_margin"),
    "bracket": ("length", "width", "height", "thickness"),
    "box": ("length", "width", "height", "wall"),
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class Source(Contract):
    id: Identifier
    kind: SourceKind
    reference: Annotated[str, Field(min_length=1, max_length=10000)]


class Parameter(Contract):
    value: Number | None
    unit: Unit
    source_id: Identifier | None
    confirmed: bool


class Baseline(Contract):
    revision: Annotated[int, Field(ge=1)]
    semantic_hash: Hash


class EngineeringTask(Contract):
    schema_version: Literal["engineering-task/1", "engineering-task/2"] = "engineering-task/1"
    task_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    action: Literal["create", "modify"]
    family: Family
    goal: Annotated[str, Field(min_length=1, max_length=10000)]
    scope: Literal["geometry_review"] = "geometry_review"
    sources: list[Source]
    parameters: dict[str, Parameter]
    features: list[Feature] = Field(default_factory=list)
    # Hard constraints are canonical millimetres, independent of input units.
    hard_constraints: dict[str, Number]
    baseline: Baseline | None
    deliverables: Annotated[list[Deliverable], Field(min_length=1)]
    tolerance_mm: Annotated[float, Field(gt=0, le=0.1, allow_inf_nan=False)] = 0.01
    rule_set_version: Literal["engineering-rules/1", "engineering-rules/2"] = "engineering-rules/1"
    skill_sha256: Hash

    @model_validator(mode="after")
    def versioned_shape(self) -> "EngineeringTask":
        if self.schema_version.endswith("/1"):
            if self.family not in PARAMETER_NAMES or self.features or self.rule_set_version != "engineering-rules/1":
                raise ValueError("Legacy task retains its three fixed recipes; use engineering-task/2 for open modeling")
            if any(parameter.unit not in ("mm", "cm", "m") for parameter in self.parameters.values()):
                raise ValueError("Legacy task supports length parameters only")
        elif self.rule_set_version != "engineering-rules/2":
            raise ValueError("Feature tasks require engineering-rules/2")
        return self

    @model_serializer(mode="wrap")
    def versioned_dump(self, handler):
        data = handler(self)
        if self.schema_version.endswith("/1"):
            data.pop("features", None)
        return data


OperationName = Literal[
    "create_plate", "create_bracket", "create_box", "create_features", "rebuild", "measure",
    "save", "reopen", "export", "preview",
]


class Operation(Contract):
    id: Identifier
    op: OperationName
    parameters: dict[str, Number | Literal["step", "stl"]]


def operation_spec(family: str, parameters_mm: dict[str, float], deliverables: list[str], *, general: bool = False) -> list[dict]:
    operations = [{"id": "build", "op": "create_features" if general else "create_" + family,
                   "parameters": {} if general else parameters_mm}]
    operations.extend({"id": name, "op": name, "parameters": {}}
                      for name in ("rebuild", "measure", "save", "reopen"))
    if "step" in deliverables:
        operations.append({"id": "export-step", "op": "export", "parameters": {"format": "step"}})
    if "preview" in deliverables:
        operations.append({"id": "preview", "op": "preview", "parameters": {"format": "stl"}})
    return operations


class CADPlan(Contract):
    schema_version: Literal["cad-plan/1", "cad-plan/2"] = "cad-plan/1"
    task_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    family: Family
    scope: Literal["geometry_review"] = "geometry_review"
    parameters_mm: dict[str, Number]
    parameter_values: dict[str, Number] = Field(default_factory=dict)
    parameter_units: dict[str, Literal["mm", "deg", "count"]] = Field(default_factory=dict)
    parameter_bindings: dict[str, list[str]] = Field(default_factory=dict)
    feature_recipe: list[Feature] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    operations: list[Operation]
    baseline: Baseline | None
    deliverables: Annotated[list[Deliverable], Field(min_length=1)]
    hard_constraints_mm: dict[str, Number]
    tolerance_mm: Annotated[float, Field(gt=0, le=0.1, allow_inf_nan=False)]
    semantic_hash: Hash
    rule_set_version: Literal["engineering-rules/1", "engineering-rules/2"] = "engineering-rules/1"
    skill_sha256: Hash

    @model_validator(mode="after")
    def fixed_execution_shape(self) -> "CADPlan":
        general = self.schema_version == "cad-plan/2"
        if not general:
            if self.family not in PARAMETER_NAMES or set(self.parameters_mm) != set(PARAMETER_NAMES[self.family]):
                raise ValueError("Legacy plan parameters must exactly match the supported family")
            if any(not math.isfinite(v) or v <= 0 for v in self.parameters_mm.values()):
                raise ValueError("Plan dimensions must be finite and positive")
            if (self.features or self.feature_recipe or self.parameter_values or self.parameter_units
                    or self.parameter_bindings or self.rule_set_version != "engineering-rules/1"):
                raise ValueError("General feature fields require cad-plan/2")
        else:
            from .generic_geometry import resolve_features, parameter_bindings
            if self.rule_set_version != "engineering-rules/2" or set(self.parameter_values) != set(self.parameter_units):
                raise ValueError("Feature plan requires v2 rules and explicit canonical parameter units")
            if self.parameters_mm != {k: v for k, v in self.parameter_values.items() if self.parameter_units[k] == "mm"}:
                raise ValueError("parameters_mm must contain exactly the canonical length parameters")
            recipe = [f.model_dump() for f in self.feature_recipe]
            if resolve_features(recipe, self.parameter_values, self.parameter_units) != [f.model_dump() for f in self.features]:
                raise ValueError("Resolved features differ from their parameterized recipe")
            if self.parameter_bindings != parameter_bindings(recipe, self.parameter_values):
                raise ValueError("Parameter bindings differ from the feature recipe")
        if len(set(self.deliverables)) != len(self.deliverables) or "native" not in self.deliverables:
            raise ValueError("Deliverables must be unique and include native save/reopen")
        if [op.model_dump() for op in self.operations] != operation_spec(
            self.family, self.parameters_mm, self.deliverables, general=general
        ):
            raise ValueError("Operations or arguments differ from the versioned family recipe")
        return self

    @model_serializer(mode="wrap")
    def versioned_dump(self, handler):
        data = handler(self)
        if self.schema_version.endswith("/1"):
            for name in ("features", "feature_recipe", "parameter_values", "parameter_units", "parameter_bindings"):
                data.pop(name, None)
        return data


class RuleViolation(Contract):
    code: str
    path: str
    message: str
