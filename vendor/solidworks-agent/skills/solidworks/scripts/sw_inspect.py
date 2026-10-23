"""Numerical model inspection: mass properties, feature health, sketches, references.

Previews show what a model looks like. These helpers measure what it is. Use them as
the primary acceptance evidence and treat previews as a secondary visual check.
Enum values were read from the SolidWorks 2025 swconst.tlb (revision 33).
"""
from __future__ import annotations

try:
    from .sw_connect import get_com_member
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member
    from sw_preflight import import_com_dependencies

pythoncom, win32com_client, VARIANT = import_com_dependencies()

# swConstrainedStatus_e (ISketch.GetConstrainedStatus, IComponent2.GetConstrainedStatus)
SW_UNKNOWN_CONSTRAINT = 1
SW_UNDER_CONSTRAINED = 2
SW_FULLY_CONSTRAINED = 3
SW_OVER_CONSTRAINED = 4
SW_NO_SOLUTION = 5
SW_INVALID_SOLUTION = 6
SW_AUTOSOLVE_OFF = 7
CONSTRAINED_STATUS = {1: "unknown", 2: "under", 3: "fully", 4: "over", 5: "no_solution",
                      6: "invalid_solution", 7: "autosolve_off"}
# swMassPropertyMoment_e
SW_MOMENT_ABOUT_CENTER_OF_MASS = 0
SW_MOMENT_ABOUT_COORD_SYS = 1
# swPersistReferencedObjectStates_e
PERSIST_REFERENCE_STATES = {0: "ok", 1: "invalid", 2: "suppressed", 4: "deleted"}
# swSetValueInConfiguration_e
SW_SET_VALUE_IN_THIS_CONFIGURATION = 1
SW_SET_VALUE_IN_ALL_CONFIGURATIONS = 2
# swAnnotationVisibilityState_e: 0 is Unknown, not hidden.
SW_ANNOTATION_HIDDEN = 3


def _null_dispatch():
    return VARIANT(pythoncom.VT_DISPATCH, None)


def _to_tensor(raw):
    """SolidWorks reports positive products of inertia; negate off-diagonals."""
    return [value if index in (0, 4, 8) else -value for index, value in enumerate(raw)]


def mass_properties(model):
    """Mass, volume, density, center of mass, and inertia in SI units.

    ``inertia_*`` are the raw SolidWorks 3x3 arrays (row-major) whose off-diagonal
    terms are positive products of inertia. ``tensor_*`` negate those terms to give the
    conventional inertia tensor. Both the center-of-mass frame and the model-origin
    frame are returned. Clears the selection so the whole model is measured.
    """
    model.ClearSelection2(True)
    properties = get_com_member(model.Extension, "CreateMassProperty2")
    if properties is None:
        raise RuntimeError("CreateMassProperty2 returned no mass property object")
    properties.UseSystemUnits = True
    raw_cg = [float(value) for value in properties.GetMomentOfInertia(SW_MOMENT_ABOUT_CENTER_OF_MASS)]
    raw_origin = [float(value) for value in properties.GetMomentOfInertia(SW_MOMENT_ABOUT_COORD_SYS)]
    return {
        "mass_kg": float(properties.Mass),
        "volume_m3": float(properties.Volume),
        "density_kg_m3": float(properties.Density),
        "cg_m": [float(value) for value in properties.CenterOfMass],
        "inertia_cg_kg_m2": raw_cg,
        "inertia_origin_kg_m2": raw_origin,
        "tensor_cg_kg_m2": _to_tensor(raw_cg),
        "tensor_origin_kg_m2": _to_tensor(raw_origin),
        "inertia_convention": "inertia_* are raw SolidWorks positive products; "
                              "tensor_* negate the off-diagonal terms",
    }


def feature_health(model):
    """Walk features and sub-features; record ``GetErrorCode2`` and its warning flag.

    Error 0 means no error. A feature whose error cannot be read records the exception
    text instead of a number, so callers cannot mistake it for success.
    """
    rows = []
    seen = set()

    def walk(feature, sub=False):
        while feature is not None:
            key = (feature.Name, get_com_member(feature, "GetTypeName2"))
            if key not in seen:
                seen.add(key)
                try:
                    warning = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
                    error = feature.GetErrorCode2(warning)
                    warning_value = bool(warning.value)
                except Exception as exc:  # noqa: BLE001 - recorded, never treated as success
                    error, warning_value = repr(exc), None
                rows.append({"name": key[0], "type": key[1], "error": error,
                             "warning": warning_value})
                walk(get_com_member(feature, "GetFirstSubFeature"), True)
            feature = get_com_member(feature, "GetNextSubFeature" if sub else "GetNextFeature")

    walk(get_com_member(model, "FirstFeature"))
    return rows


def failing_features(rows, types=None):
    """Features with a nonzero or unreadable error, optionally filtered by type name."""
    return [row for row in rows
            if (types is None or row["type"] in types) and row["error"] != 0]


def snapshot(model):
    """Rebuild, then record body count, body boxes, mass properties, and feature health.

    Raises if the rebuild does not return True. Part documents only for bodies.
    """
    rebuilt = get_com_member(model, "EditRebuild3")
    if rebuilt is not True:
        raise RuntimeError(f"EditRebuild3 did not succeed: {rebuilt!r}")
    bodies = list(model.GetBodies2(0, False) or []) if get_com_member(model, "GetType") == 1 else []
    return {
        "rebuild": rebuilt,
        "bodies": len(bodies),
        "bounds_m": [[float(v) for v in get_com_member(body, "GetBodyBox")] for body in bodies],
        "mass": mass_properties(model),
        "features": feature_health(model),
    }


def sketch_status(model):
    """Constrained status of the active sketch as ``(code, label)``."""
    sketch = model.SketchManager.ActiveSketch
    if sketch is None:
        raise RuntimeError("No active sketch")
    code = int(get_com_member(sketch, "GetConstrainedStatus"))
    return code, CONSTRAINED_STATUS.get(code, "unknown")


def fully_define_active_sketch(model, datum="Point1@Origin", datum_type="EXTSKETCHPOINT"):
    """Apply FullyDefineSketch against a datum, then require solver state 3.

    The FullyDefineSketch return code is not documented in the 2025 API help, so the
    solver state is the evidence. Relations: horizontal + vertical (mask 6); baseline
    dimension schemes; the datum is selected with mark 6. Automatic definition proves
    solver closure, not design intent: add named driving dimensions first.
    """
    sketch = model.SketchManager.ActiveSketch
    if sketch is None:
        raise RuntimeError("No active sketch")
    model.ClearSelection2(True)
    if not model.Extension.SelectByID2(datum, datum_type, 0, 0, 0, False, 6, _null_dispatch(), 0):
        raise RuntimeError(f"Cannot select sketch datum {datum}")
    code = model.SketchManager.FullyDefineSketch(
        True, True, 6, True, 1, _null_dispatch(), 1, _null_dispatch(), 1, 1)
    status = int(get_com_member(sketch, "GetConstrainedStatus"))
    model.ClearSelection2(True)
    if status != SW_FULLY_CONSTRAINED:
        raise RuntimeError(f"Sketch {sketch.Name} not fully defined: return={code}, "
                           f"status={CONSTRAINED_STATUS.get(status, status)}")
    return {"sketch": sketch.Name, "return_code": code, "status": status}


def add_named_dimension(model, entity, value, name, x, y):
    """Dimension one sketch entity, rename it, and drive it to ``value`` (meters).

    Returns the dimension full name, e.g. ``BoreDiameter@Sketch1``. Suppress the
    modal dimension dialog first (see ``sw_runtime.no_dimension_input_dialog``).
    """
    model.ClearSelection2(True)
    if not entity.Select4(False, _null_dispatch()):
        raise RuntimeError("Cannot select entity to dimension")
    display = model.AddDimension2(x, y, 0)
    if display is None:
        raise RuntimeError("AddDimension2 returned no display dimension")
    dimension = display.GetDimension2(0)
    dimension.Name = name
    dimension.SystemValue = value
    model.ClearSelection2(True)
    return dimension.FullName


def set_dimension(model, full_name, value, which=SW_SET_VALUE_IN_THIS_CONFIGURATION):
    """Set a dimension value (meters or radians) with SetSystemValue3; 0 means success."""
    dimension = model.Parameter(full_name)
    if dimension is None:
        raise KeyError(f"Dimension not found: {full_name}")
    result = dimension.SetSystemValue3(value, which, VARIANT(pythoncom.VT_EMPTY, None))
    if result != 0:
        raise RuntimeError(f"SetSystemValue3({full_name}) returned {result}")
    return float(dimension.SystemValue)


def activate_configuration(model, name):
    """Activate a configuration and prove it by reading the active name back."""
    manager = model.ConfigurationManager
    previous = manager.ActiveConfiguration.Name
    result = None
    if previous != name:
        result = model.ShowConfiguration2(name)
    actual = manager.ActiveConfiguration.Name
    if actual != name:
        raise RuntimeError(f"Configuration {name!r} not active (still {actual!r})")
    return {"requested": name, "previous": previous, "return_value": result}


def persist_reference(model, obj):
    """Serialize an entity/feature to persistent-reference bytes (same document only)."""
    reference = model.Extension.GetPersistReference3(obj)
    if reference is None:
        raise RuntimeError("GetPersistReference3 returned no reference")
    return list(reference)


def resolve_persist_reference(model, reference):
    """Resolve persistent-reference bytes; returns ``(object_or_None, state_label)``.

    A deleted or replaced target must come back as a non-ok state. Never promise that
    a reference survives arbitrary topology replacement.
    """
    error = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    data = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_UI1, list(reference))
    obj = model.Extension.GetObjectByPersistReference3(data, error)
    return obj, PERSIST_REFERENCE_STATES.get(int(error.value), f"code {error.value}")


def interference_status(model, skip_reason=None):
    """Static interference scan that reports failure as ``unknown`` instead of raising.

    A skipped or failed scan has ``count`` None. Never report it as zero interference.
    """
    if skip_reason:
        return {"status": "unknown", "skipped": True, "reason": skip_reason, "count": None}
    try:
        if get_com_member(model, "GetType") != 2:
            raise ValueError("interference scan requires an assembly")
        try:
            from .sw_assembly import get_interference_detection
        except ImportError:
            from sw_assembly import get_interference_detection
        return get_interference_detection(model, detailed=True)
    except Exception as exc:  # noqa: BLE001 - surfaced as unknown, never as clear
        return {"status": "unknown", "skipped": False, "error": repr(exc), "count": None}


def table_cells(table):
    """Read every cell of a table annotation (for example a BOM) as text rows."""
    table = win32com_client.dynamic.DumbDispatch(getattr(table, "_oleobj_", table))
    rows, columns = int(table.RowCount), int(table.ColumnCount)
    cells = []
    for row in range(rows):
        line = []
        for column in range(columns):
            try:
                line.append(table.Text2(row, column, False))
            except Exception:  # noqa: BLE001 - older releases expose only Text
                line.append(table.Text(row, column))
        cells.append(line)
    return cells


def pdf_page_texts(path):
    """Extract text per PDF page (requires ``pypdf``). Use to prove exact sheet sets."""
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


def render_pdf_pages(path, output_dir, zoom=2.0):
    """Render each PDF page to PNG for visual review (requires ``pymupdf``)."""
    from pathlib import Path

    import pymupdf

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with pymupdf.open(str(path)) as document:
        for index, page in enumerate(document, 1):
            target = output_dir / f"{Path(path).stem}-page-{index}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(str(target))
            written.append(str(target))
    return written


def bmp_to_png(path):
    """Convert a SaveBMP preview to PNG next to it (requires ``pillow``)."""
    from pathlib import Path

    from PIL import Image

    source = Path(path)
    target = source.with_suffix(".png")
    with Image.open(source) as image:
        image.save(target)
    return str(target)
