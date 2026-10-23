"""
SolidWorks part modeling utilities.
Common functions for sketching and feature creation.
"""
from contextlib import contextmanager
from functools import wraps
import math

try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import get_com_member
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import get_com_member

pythoncom, _win32com, VARIANT = import_com_dependencies()

# Localized SolidWorks plane names for Chinese-UI installs; keep the Chinese
# strings as-is, they are SolidWorks aliases, not prose.
PLANE_NAME_ALIASES = {
    "Front Plane": ["Front Plane", "前视基准面"],
    "Top Plane": ["Top Plane", "上视基准面"],
    "Right Plane": ["Right Plane", "右视基准面"],
    "前视基准面": ["前视基准面", "Front Plane"],
    "上视基准面": ["上视基准面", "Top Plane"],
    "右视基准面": ["右视基准面", "Right Plane"],
}

# Localized SolidWorks sketch-name prefix for Chinese-UI installs; keep the
# Chinese string as-is, it is a SolidWorks alias, not prose.
SKETCH_NAME_PREFIX_ALIASES = {
    "Sketch": "草图",
    "草图": "Sketch",
}


# ============================================================
# Sketch operations
# ============================================================

def _empty_callout():
    """Create an empty Callout argument compatible with SelectByID2."""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def _select_by_id(extension, entity_name, entity_type, append=False, mark=0):
    """
    Wrap SelectByID2 consistently, avoiding a type mismatch that None can
    trigger on some SolidWorks versions.

    Args:
        extension: ModelDocExtension object
        entity_name: entity name
        entity_type: entity type string
        append: whether to append to the current selection
        mark: selection mark

    Returns:
        bool
    """
    return extension.SelectByID2(
        entity_name, entity_type, 0, 0, 0, append, mark, _empty_callout(), 0
    )


def _get_plane_name_candidates(plane_name):
    """
    Get the list of candidate names for a plane.

    Args:
        plane_name: plane name supplied by the caller

    Returns:
        list[str]
    """
    return PLANE_NAME_ALIASES.get(plane_name, [plane_name])


def _get_sketch_name_candidates(sketch_name):
    """
    Get the list of candidate sketch names, auto-handling Chinese/English
    prefixes.

    Args:
        sketch_name: sketch name

    Returns:
        list[str]
    """
    candidates = [sketch_name]
    for prefix, alias in SKETCH_NAME_PREFIX_ALIASES.items():
        if sketch_name.startswith(prefix):
            alias_name = alias + sketch_name[len(prefix):]
            if alias_name not in candidates:
                candidates.append(alias_name)
    return candidates


def _select_first_candidate(extension, candidate_names, entity_type, append=False, mark=0):
    """
    Try selecting an entity using each candidate name in turn.

    Args:
        extension: ModelDocExtension object
        candidate_names: list of candidate names
        entity_type: entity type string
        append: whether to append to the current selection
        mark: selection mark

    Returns:
        str | None
    """
    for candidate_name in candidate_names:
        if _select_by_id(extension, candidate_name, entity_type, append=append, mark=mark):
            return candidate_name
    return None


def _get_selection_count(model):
    """
    Get the number of objects in the current selection set.

    Args:
        model: IModelDoc2 object

    Returns:
        int
    """
    selection_manager = model.SelectionManager
    count_member = getattr(selection_manager, "GetSelectedObjectCount2")
    return count_member(-1) if callable(count_member) else int(count_member)


def _ensure_sketch_selected(model, sketch_name):
    """
    Make sure a usable sketch selection exists before extrude/cut.

    Args:
        model: IModelDoc2 object
        sketch_name: sketch name

    Returns:
        str
    """
    model.ClearSelection2(True)
    if not isinstance(sketch_name, str) or not sketch_name:
        raise ValueError("An exact sketch name is required")
    if not _select_by_id(model.Extension, sketch_name, "SKETCH"):
        raise ValueError(f"Cannot select sketch: {sketch_name}")
    manager = model.SelectionManager
    if (_get_selection_count(model) != 1
            or manager.GetSelectedObjectCount2(0) != 1
            or manager.GetSelectedObjectType3(1, 0) != 9
            or manager.GetSelectedObject6(1, 0).Name != sketch_name):
        model.ClearSelection2(True)
        raise RuntimeError("Sketch selection identity/type/mark did not match")
    return sketch_name


def _checked_feature(function):
    """Feature helpers own and clear their selection even on COM failure."""
    @wraps(function)
    def checked(model, *args, **kwargs):
        try:
            feature = function(model, *args, **kwargs)
            if feature is None or feature is False:
                raise RuntimeError(f"{function.__name__} returned no feature")
            return feature
        finally:
            model.ClearSelection2(True)
    return checked


def _positive(value, name):
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _select_named(model, name, kind, mark):
    if not isinstance(name, str) or not name:
        raise ValueError(f"An exact {kind} name is required")
    if not _select_by_id(model.Extension, name, kind, append=True, mark=mark):
        raise ValueError(f"Cannot select {kind}: {name}")
    if model.SelectionManager.GetSelectedObjectCount2(mark) != 1:
        raise RuntimeError(f"Expected one selection with mark {mark}")


def _select_entities(model, entities, kind):
    """Capture current typed entities if omitted, then reselect using mark 1."""
    manager = model.SelectionManager
    if entities is None:
        count = _get_selection_count(model)
        if any(manager.GetSelectedObjectType3(i, -1) != kind
               for i in range(1, count + 1)):
            raise ValueError("Current selection contains the wrong entity type")
        entities = [manager.GetSelectedObject6(i, -1) for i in range(1, count + 1)]
    entities = list(entities)
    if not entities:
        raise ValueError("At least one explicit edge/face is required")
    model.ClearSelection2(True)
    data = manager.CreateSelectData()
    data.Mark = 1
    for index, entity in enumerate(entities, 1):
        if not entity.Select4(True, data):
            raise ValueError("Entity selection failed")
        if (manager.GetSelectedObjectCount2(1) != index
                or manager.GetSelectedObjectType3(index, 1) != kind):
            raise ValueError("Wrong entity type or duplicate entity selection")
    return entities


def _feature_snapshot(model):
    """Traverse rather than assume last feature position (default folders vary)."""
    features = {}
    feature = get_com_member(model, "FirstFeature")
    while feature is not None:
        if feature.Name in features:
            raise RuntimeError("Duplicate/cyclic feature tree while checking creation")
        features[feature.Name] = feature
        feature = get_com_member(feature, "GetNextFeature")
    return features

def start_sketch(model, plane_name="Front Plane"):
    """
    Start a sketch on the given plane.

    Args:
        model: IModelDoc2
        plane_name: plane name
            English: "Front Plane", "Top Plane", "Right Plane"
            Chinese: "前视基准面", "上视基准面", "右视基准面"
    """
    model.ClearSelection2(True)

    selected_plane = _select_first_candidate(
        model.Extension, _get_plane_name_candidates(plane_name), "PLANE"
    )
    if selected_plane:
        model.SketchManager.InsertSketch(True)
        return selected_plane

    raise ValueError(f"Cannot select plane: {plane_name}")


def end_sketch(model):
    """Exit the current sketch."""
    model.SketchManager.InsertSketch(True)


@contextmanager
def sketch(model, plane_name="Front Plane"):
    """
    Sketch context manager.

    Example:
        with sketch(model, "Front Plane") as sketch_name:
            sketch_circle(model, 0, 0, mm(25))
        extrude_boss(model, sketch_name, mm(50))
    """
    start_sketch(model, plane_name)
    try:
        yield current_sketch_name(model)
    finally:
        end_sketch(model)


def current_sketch_name(model, fallback=None):
    """
    Get the current sketch name.

    Args:
        model: IModelDoc2
        fallback: default name to return if the active sketch cannot be read
    """
    active_sketch = model.SketchManager.ActiveSketch
    if active_sketch:
        return active_sketch.Name
    if fallback is not None:
        return fallback
    raise RuntimeError("No active sketch; cannot infer a sketch name")


def sketch_line(model, x1, y1, x2, y2):
    """Draw a line (units: meters)."""
    return model.SketchManager.CreateLine(x1, y1, 0, x2, y2, 0)


def sketch_rectangle(model, cx, cy, w, h):
    """Draw a rectangle from its center point (units: meters)."""
    return model.SketchManager.CreateCenterRectangle(
        cx, cy, 0, cx + w / 2, cy + h / 2, 0
    )


def sketch_corner_rectangle(model, x1, y1, x2, y2):
    """Draw a rectangle from a diagonal (units: meters)."""
    return model.SketchManager.CreateCornerRectangle(x1, y1, 0, x2, y2, 0)


def sketch_circle(model, cx, cy, radius):
    """Draw a circle (units: meters)."""
    return model.SketchManager.CreateCircleByRadius(cx, cy, 0, radius)


def sketch_arc(model, cx, cy, x1, y1, x2, y2, direction=1):
    """
    Draw an arc.

    Args:
        cx, cy: center coordinates (meters)
        x1, y1: start point coordinates
        x2, y2: end point coordinates
        direction: 1=counterclockwise, -1=clockwise
    """
    return model.SketchManager.CreateArc(cx, cy, 0, x1, y1, 0, x2, y2, 0, direction)


def sketch_polygon(model, cx, cy, radius, sides=6):
    """Draw a regular polygon (inscribed-circle method)."""
    return model.SketchManager.CreatePolygon(cx, cy, 0, cx + radius, cy, 0, sides, True)


def sketch_slot(model, x1, y1, x2, y2, radius):
    """Straight slot: endpoints are arc centers; width is twice radius (meters)."""
    _positive(radius, "radius")
    if (x1, y1) == (x2, y2):
        raise ValueError("Slot centers must differ")
    result = model.SketchManager.CreateSketchSlot(
        0,  # swSketchSlotCreationType_e: 0=Straight
        0, 2 * radius,  # CenterCenter length mode; full width
        x1, y1, 0,
        x2, y2, 0,
        0, 0, 0,
        1, False
    )
    if result is None or result is False:
        raise RuntimeError("CreateSketchSlot returned no slot")
    return result


def sketch_spline(model, points):
    """
    Draw a spline curve.

    Args:
        points: [(x1,y1), (x2,y2), ...] list of control points (units: meters)
    """
    import array
    point_array = array.array('d')
    for x, y in points:
        point_array.extend([x, y, 0.0])
    return model.SketchManager.CreateSpline2(point_array, False)


def add_dimension(model, x, y):
    """Add a dimension annotation at the given position."""
    return model.AddDimension2(x, y, 0)


def add_sketch_relation(model, relation_type):
    """
    Add a sketch geometric relation.

    Common relation_type values:
        "sgFIXED", "sgHORIZONTAL", "sgVERTICAL", "sgCOLINEAR",
        "sgPARALLEL", "sgPERPENDICULAR", "sgTANGENT", "sgCONCENTRIC",
        "sgEQUAL", "sgSYMMETRIC", "sgMIDPOINT", "sgCOINCIDENT"
    """
    return model.SketchAddConstraints(relation_type)


# ============================================================
# Feature operations
# ============================================================

@_checked_feature
def extrude_boss(model, sketch_name, depth, direction=True, merge=True):
    """
    Boss extrusion.

    Args:
        model: IModelDoc2
        sketch_name: sketch name (e.g. "Sketch1")
        depth: extrusion depth (meters)
        direction: True=positive direction
        merge: True=merge result
    """
    _positive(depth, "depth")
    _ensure_sketch_selected(model, sketch_name)
    return model.FeatureManager.FeatureExtrusion3(
        True,         # Sd: single-direction extrusion
        False,        # Flip
        direction,    # Dir: extrusion direction
        0,            # T1: Blind
        0,            # T2: Blind
        depth,        # D1
        0.0,          # D2
        False,        # Dchk1
        False,        # Dchk2
        False,        # Ddir1
        False,        # Ddir2
        0.0,          # Dang1
        0.0,          # Dang2
        False,        # OffsetReverse1
        False,        # OffsetReverse2
        False,        # TranslateSurface1
        False,        # TranslateSurface2
        merge,        # Merge
        False,        # UseFeatScope
        True,         # UseAutoSelect
        0,            # T0: start from the sketch plane
        0.0,          # StartOffset
        False         # FlipStartOffset
    )


@_checked_feature
def extrude_cut(model, sketch_name, depth, direction=True, flip=False):
    """
    Cut extrusion.

    Args:
        model: IModelDoc2
        sketch_name: sketch name
        depth: cut depth (meters); 0 means through-all
        direction: True=positive direction
        flip: True=flip the cut direction
    """
    if depth != 0:
        _positive(depth, "depth")
    _ensure_sketch_selected(model, sketch_name)
    if depth == 0:
        # Through-all
        end_condition = 1  # swEndCondThroughAll
        depth = 0.01  # placeholder value
    else:
        end_condition = 0  # swEndCondBlind

    return model.FeatureManager.FeatureCut4(
        True, flip, direction,
        end_condition, 0,
        depth, 0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False, False,
        True, True, True, True,
        False, 0, 0, False, False
    )


@_checked_feature
def extrude_midplane(model, sketch_name, total_depth):
    """
    Mid-plane extrusion (symmetric extrusion on both sides).

    Args:
        total_depth: total depth (meters); each side is total_depth/2
    """
    _positive(total_depth, "total_depth")
    _ensure_sketch_selected(model, sketch_name)
    return model.FeatureManager.FeatureExtrusion3(
        True,         # Sd: single-direction definition, end condition controls mid-plane
        False,        # Flip
        True,         # Dir
        6,            # T1: swEndCondMidPlane
        0,            # T2
        total_depth,  # D1
        0.0,          # D2
        False,        # Dchk1
        False,        # Dchk2
        False,        # Ddir1
        False,        # Ddir2
        0.0,          # Dang1
        0.0,          # Dang2
        False,        # OffsetReverse1
        False,        # OffsetReverse2
        False,        # TranslateSurface1
        False,        # TranslateSurface2
        True,         # Merge
        False,        # UseFeatScope
        True,         # UseAutoSelect
        0,            # T0
        0.0,          # StartOffset
        False         # FlipStartOffset
    )


@_checked_feature
def revolve_boss(model, sketch_name, angle_rad, axis_sketch_name=None, *, axis_type="EXTSKETCHSEGMENT"):
    """
    Revolved boss.

    Args:
        sketch_name: profile sketch name
        angle_rad: revolve angle (radians); 2*pi means 360 degrees
        axis_sketch_name: exact qualified sketch segment name, e.g. Line1@Sketch2;
            for a named reference axis supply axis_type="AXIS". Required.
    """
    _positive(angle_rad, "angle_rad")
    if angle_rad > 2 * math.pi:
        raise ValueError("angle_rad cannot exceed 2*pi")
    if axis_type not in ("EXTSKETCHSEGMENT", "AXIS") or not axis_sketch_name:
        raise ValueError("An explicit sketch segment or reference axis is required")
    _ensure_sketch_selected(model, sketch_name)
    _select_named(model, axis_sketch_name, axis_type, 4)
    return model.FeatureManager.FeatureRevolve2(
        True, True, False,
        False, False, False,
        0, 0,
        angle_rad, 0,
        False, False,
        0.0, 0.0,
        0, 0, 0, True, True, True
    )


@_checked_feature
def fillet(model, radius, edges=None):
    """
    Fillet.

    Args:
        model: IModelDoc2
        radius: fillet radius (meters)
        edges: pre-selected list of edges; None uses the current selection
    """
    _positive(radius, "radius")
    _select_entities(model, edges, 1)  # swSelEDGES; FeatureFillet mark 1
    return model.FeatureManager.FeatureFillet(
        3, radius, 0, 0, VARIANT(pythoncom.VT_EMPTY, None),
        VARIANT(pythoncom.VT_EMPTY, None), VARIANT(pythoncom.VT_EMPTY, None)
    )


def chamfer(model, distance, angle_deg=45):
    """
    Chamfer.

    Args:
        distance: chamfer distance (meters)
        angle_deg: chamfer angle (degrees)
    """
    import math
    angle_rad = angle_deg * math.pi / 180.0
    return model.FeatureManager.InsertFeatureChamfer(
        4, 1, distance, angle_rad, 0, 0, 0, 0
    )


@_checked_feature
def linear_pattern(model, feature_name, direction1, d1_spacing, d1_count, *,
                   direction2=None, d2_spacing=0, d2_count=1,
                   flip1=False, flip2=False):
    """Pattern a feature using (exact_name, selection_type) direction references.

    Direction types are AXIS, EDGE or EXTSKETCHSEGMENT; raw vectors are unsupported.
    Counts include the seed. Direction two is optional. Lengths are meters.
    """
    for count in (d1_count, d2_count):
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("Pattern counts must be positive integers")
    if d1_count < 2:
        raise ValueError("Direction one requires at least two instances")
    _positive(d1_spacing, "d1_spacing")
    if direction2 is None and (d2_count != 1 or d2_spacing != 0):
        raise ValueError("Direction two parameters require a reference")
    if direction2 is not None:
        _positive(d2_spacing, "d2_spacing")
        if d2_count < 2:
            raise ValueError("Direction two requires at least two instances")
    model.ClearSelection2(True)
    for direction, mark in ((direction1, 1), (direction2, 2)):
        if direction is None:
            continue
        if (not isinstance(direction, (tuple, list)) or len(direction) != 2
                or direction[1] not in ("AXIS", "EDGE", "EXTSKETCHSEGMENT")):
            raise ValueError("Direction requires (name, AXIS/EDGE/EXTSKETCHSEGMENT)")
        _select_named(model, direction[0], direction[1], mark)
    if direction1 is None:
        raise ValueError("Direction one reference is required")
    _select_named(model, feature_name, "BODYFEATURE", 4)
    return model.FeatureManager.FeatureLinearPattern3(
        d1_count, d1_spacing, d2_count, d2_spacing,
        flip1, flip2, "", "", False, False
    )


@_checked_feature
def circular_pattern(model, feature_name, axis_name, angle_rad, count, equal_spacing=True):
    """
    Circular pattern.

    Args:
        feature_name: name of the feature to pattern
        axis_name: rotation axis name
        angle_rad: total angle (radians)
        count: number of instances
        equal_spacing: True=equal spacing
    """
    _positive(angle_rad, "angle_rad")
    if isinstance(count, bool) or not isinstance(count, int) or count < 2:
        raise ValueError("Pattern count must be an integer >= 2")
    model.ClearSelection2(True)
    _select_named(model, axis_name, "AXIS", 1)
    _select_named(model, feature_name, "BODYFEATURE", 4)
    return model.FeatureManager.FeatureCircularPattern4(
        count, angle_rad, False, "", False, equal_spacing, False
    )


@_checked_feature
def shell(model, thickness, faces_to_remove=None):
    """
    Shell.

    Args:
        thickness: wall thickness (meters)
        faces_to_remove: faces to remove must be pre-selected
    """
    _positive(thickness, "thickness")
    _select_entities(model, faces_to_remove, 2)  # swSelFACES; removal mark 1
    before = _feature_snapshot(model)
    model.InsertFeatureShell(thickness, False)  # IModelDoc2 method returns void
    after = _feature_snapshot(model)
    added = [feature for name, feature in after.items() if name not in before]
    if (len(added) != 1 or set(before) - set(after)
            or get_com_member(added[0], "GetTypeName2") != "Shell"):
        raise RuntimeError("InsertFeatureShell did not create exactly one Shell feature")
    feature = added[0]
    return feature


@_checked_feature
def mirror_feature(model, feature_name, mirror_plane_name):
    """
    Mirror a feature.

    Args:
        feature_name: name of the feature to mirror
        mirror_plane_name: mirror plane name
    """
    model.ClearSelection2(True)
    _select_named(model, feature_name, "BODYFEATURE", 1)
    _select_named(model, mirror_plane_name, "PLANE", 2)
    return model.FeatureManager.InsertMirrorFeature2(False, False, False, False, 0)


def hole_wizard(model, hole_type, standard, fastener_type, size, depth, x, y, z):
    """
    Hole Wizard (simplified).
    Note: the full Hole Wizard parameter set is complex; refer to the API docs
    before adjusting it.
    """
    raise NotImplementedError(
        "Hole Wizard has no qualified contract in this helper. Use an explicitly "
        "validated HoleWizard5 adapter with standard/type/size and placement checks."
    )


def rib(model, sketch_name, thickness, direction=True):
    """
    Rib feature.

    Args:
        sketch_name: rib profile sketch name
        thickness: rib thickness (meters)
        direction: extrusion direction
    """
    raise NotImplementedError(
        "The legacy rib direction parameter is ambiguous: InsertRib takes ten "
        "arguments and returns void. Use a qualified rib feature-data adapter."
    )
