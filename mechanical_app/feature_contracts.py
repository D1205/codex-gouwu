"""Versioned, data-only prismatic feature language; part names are not capabilities."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Scalar = Annotated[float, Field(allow_inf_nan=False)] | Annotated[str, Field(min_length=1, max_length=200)]


class FeatureContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Profile(FeatureContract):
    kind: Literal["circle", "rectangle", "polygon"]
    center: Annotated[list[Scalar], Field(min_length=2, max_length=2)]
    diameter: Scalar | None
    size: Annotated[list[Scalar], Field(max_length=2)]
    points: Annotated[list[Annotated[list[Scalar], Field(min_length=2, max_length=2)]], Field(max_length=512)]


class Pattern(FeatureContract):
    kind: Literal["circular", "linear"]
    count: Scalar
    radius: Scalar
    angle_deg: Scalar
    step: Annotated[list[Scalar], Field(min_length=2, max_length=2)]


class Feature(FeatureContract):
    id: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,59}$")]
    operation: Literal["add", "cut"]
    profile: Profile
    start: Scalar
    depth: Scalar
    pattern: Pattern | None
