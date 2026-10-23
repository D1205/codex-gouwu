"""Pinned SolidWorks runtime: attach, early binding, preferences, and transforms.

These helpers attach to a SolidWorks process that is already running. They never
launch or terminate CAD. Enum values below were read from the SolidWorks 2025
type libraries (sldworks.tlb / swconst.tlb, revision 33).
"""
from __future__ import annotations

import contextlib
import math
import os

try:
    from .sw_connect import get_com_member
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member
    from sw_preflight import import_com_dependencies

pythoncom, win32com_client, VARIANT = import_com_dependencies()

# Type-library GUIDs are stable across releases; the major version is the revision.
SLDWORKS_TYPELIB = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
SWCONST_TYPELIB = "{4687F359-55D0-4CD3-B6CF-2EB42C11F989}"

# swUserPreferenceToggle_e
SW_INPUT_DIM_VAL_ON_CREATE = 10
# swUserPreferenceStringValue_e
SW_DEFAULT_TEMPLATE = {"part": 8, "assembly": 9, "drawing": 10}
# swDocumentTypes_e
SW_DOC_TYPES = {"part": 1, "assembly": 2, "drawing": 3}

IDENTITY_ROTATION = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def revision_major(year):
    """SolidWorks year to COM major revision: 2025 -> 33."""
    return int(year) - 2000 + 8


def prog_id(major=None):
    """Version-specific ProgID when major is given.

    The version-independent ProgID binds to whichever release registered last. Pin
    a major version whenever more than one release is installed.
    """
    return "SldWorks.Application" if major is None else f"SldWorks.Application.{int(major)}"


def installed_majors(candidates=range(20, 50)):
    """Return registered version-specific SolidWorks ProgID majors (registry read only)."""
    if os.name != "nt":
        return []
    import winreg

    found = []
    for major in candidates:
        try:
            winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, prog_id(major) + r"\CLSID")
        except OSError:
            continue
        found.append(major)
    return found


def ensure_type_libraries(major):
    """Generate or load pywin32 early-bound wrappers for sldworks and swconst."""
    for clsid in (SLDWORKS_TYPELIB, SWCONST_TYPELIB):
        win32com_client.gencache.EnsureModule(clsid, 0, int(major), 0)


def early_bound(obj, interface, major):
    """Wrap a dispatch object with a typed interface, e.g. ``IEquationMgr``.

    Some members, such as equation-manager properties, only behave correctly through
    the generated early-bound interface.
    """
    module = win32com_client.gencache.EnsureModule(SLDWORKS_TYPELIB, 0, int(major), 0)
    if module is None:
        raise RuntimeError(f"sldworks type library {major} is not registered")
    return getattr(module, interface)(getattr(obj, "_oleobj_", obj))


def attach(major=None, *, expect_revision=None, early_binding=True):
    """Attach to a running SolidWorks and return ``(app, revision)``.

    ``app`` is a late-bound ``DumbDispatch`` wrapper, which keeps property/method
    handling predictable. Raises if no matching process is running, if the major
    version differs, or if ``expect_revision`` (for example ``"33.5.0"``) differs.
    This function never starts SolidWorks.
    """
    progid = prog_id(major)
    try:
        app = win32com_client.GetActiveObject(progid)
    except pythoncom.com_error as exc:
        raise RuntimeError(
            f"No running SolidWorks is registered as {progid}. Start SolidWorks first; "
            "this helper never launches CAD."
        ) from exc
    revision = str(get_com_member(app, "RevisionNumber"))
    actual_major = int(revision.split(".")[0])
    if major is not None and actual_major != int(major):
        raise RuntimeError(f"Attached revision {revision} does not match major {major}")
    if expect_revision is not None and revision != str(expect_revision):
        raise RuntimeError(f"Attached revision {revision}; expected {expect_revision}")
    if early_binding:
        ensure_type_libraries(actual_major)
    return win32com_client.dynamic.DumbDispatch(app._oleobj_), revision


def default_template(app, doc_type):
    """Return the user's default template path for part, assembly, or drawing."""
    key = str(doc_type).lower()
    if key not in SW_DEFAULT_TEMPLATE:
        raise ValueError(f"Unknown document type: {doc_type}")
    path = app.GetUserPreferenceStringValue(SW_DEFAULT_TEMPLATE[key])
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(
            f"Default {key} template is not configured or missing: {path!r}. "
            "Set it in Tools > Options > Default Templates or pass a template path."
        )
    return path


@contextlib.contextmanager
def user_preference_toggle(app, preference, value):
    """Set a user-preference toggle and always restore the original value."""
    original = app.GetUserPreferenceToggle(preference)
    app.SetUserPreferenceToggle(preference, value)
    try:
        yield original
    finally:
        app.SetUserPreferenceToggle(preference, original)


def no_dimension_input_dialog(app):
    """Suppress the modal 'input dimension value' dialog for this block only."""
    return user_preference_toggle(app, SW_INPUT_DIM_VAL_ON_CREATE, False)


def math_transform(app, rotation=IDENTITY_ROTATION, translation=(0.0, 0.0, 0.0), scale=1.0):
    """Create an IMathTransform from a 3x3 row-major rotation and a translation in meters.

    pywin32 does not expose ``CreateTransform`` as callable on the dynamic wrapper,
    so it is flagged as a method first. The 16-value array is rotation(9),
    translation(3), scale(1), unused(3).
    """
    rotation = [float(value) for value in rotation]
    translation = [float(value) for value in translation]
    if len(rotation) != 9 or len(translation) != 3:
        raise ValueError("rotation needs 9 values and translation needs 3")
    utility = get_com_member(app, "GetMathUtility")
    if hasattr(utility, "_FlagAsMethod"):
        utility._FlagAsMethod("CreateTransform")
    data = [*rotation, *translation, float(scale), 0.0, 0.0, 0.0]
    transform = utility.CreateTransform(VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, data))
    if transform is None:
        raise RuntimeError("CreateTransform returned no transform")
    return transform


def rotation_about_z(angle_rad):
    """Row-major rotation about +Z, in the layout used by IMathTransform.ArrayData."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (c, s, 0.0, -s, c, 0.0, 0.0, 0.0, 1.0)


def component_transform(component):
    """Return a component's 16-value transform array (translation at indices 9-11, meters)."""
    return [float(value) for value in component.Transform2.ArrayData]


def place_component(app, component, translation=(0.0, 0.0, 0.0), rotation=IDENTITY_ROTATION):
    """Set a component transform directly. Use for initial placement, not for mates."""
    component.Transform2 = math_transform(app, rotation, translation)
    return component_transform(component)


def transform_and_solve(app, component, translation=(0.0, 0.0, 0.0), rotation=IDENTITY_ROTATION):
    """Request a pose through the mate solver; returns ``(result, actual_transform)``.

    The solver may reject or project the request onto the free degrees of freedom.
    Always compare the returned transform with the request.
    """
    result = component.SetTransformAndSolve2(math_transform(app, rotation, translation))
    return result, component_transform(component)
