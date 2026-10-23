"""
SolidWorks connection utilities.
Provides several ways to connect to a SolidWorks instance.
"""
import glob
import os
import time

try:
    from .sw_preflight import ensure_solidworks_installed, import_com_dependencies
except ImportError:
    from sw_preflight import ensure_solidworks_installed, import_com_dependencies

pythoncom, win32com_client, VARIANT = import_com_dependencies()


DOC_TYPE_MAP = {
    "part": 1,
    "prt": 1,
    "sldprt": 1,
    "assembly": 2,
    "asm": 2,
    "sldasm": 2,
    "drawing": 3,
    "drw": 3,
    "slddrw": 3,
}

DOC_TYPE_LABELS = {
    "part": "part",
    "assembly": "assembly",
    "drawing": "drawing",
}


def get_com_member(obj, attr_name, *args):
    """
    Handle the pywin32 case where the same member may be a property or a
    method depending on the environment.

    Args:
        obj: COM object
        attr_name: member name
        *args: arguments to pass if the member is callable

    Returns:
        the member value, or the result of calling it
    """
    member = getattr(obj, attr_name)
    if args:
        if not callable(member):
            raise TypeError(f"COM member does not accept arguments: {attr_name}")
        return member(*args)
    # A pywin32 CDispatch returned by a COM property is itself callable. Calling it
    # again invokes the object's default member and often raises "member not found".
    if callable(member) and not hasattr(member, "_oleobj_"):
        return member()
    return member


def rebuild_document(model):
    """Handle both the property and method COM exposure forms; run a normal
    rebuild followed by a forced rebuild."""
    edit_result = get_com_member(model, "EditRebuild3")
    force_result = get_com_member(model, "ForceRebuild3", False)
    return bool(edit_result), bool(force_result)


def create_empty_dispatch_variant():
    """Create an empty Dispatch argument to pass to a COM interface."""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def normalize_doc_type(doc_type):
    """
    Normalize a document type name.

    Args:
        doc_type: "part", "assembly", "drawing", or a common abbreviation/extension

    Returns:
        (name, enum_value) tuple
    """
    key = str(doc_type).strip().lower().lstrip(".")
    enum_value = DOC_TYPE_MAP.get(key)
    if enum_value is None:
        raise ValueError(f"Unknown document type: {doc_type}")

    name_map = {1: "part", 2: "assembly", 3: "drawing"}
    return name_map[enum_value], enum_value


def _expand_path(file_path):
    """Expand the user directory and environment variables, and return an absolute path."""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(file_path)))


def _ensure_parent_dir(file_path):
    """Make sure the output file's parent directory exists."""
    parent = os.path.dirname(_expand_path(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def connect_solidworks(version=None, wait_seconds=5, visible=True):
    """
    Connect to a SolidWorks instance.

    Args:
        version: SolidWorks release year (e.g. 2024); None auto-detects
        wait_seconds: seconds to wait after starting a new instance
        visible: whether to show the window after starting a new instance

    Returns:
        (sw, model) tuple; model may be None if no document is open
    """
    ensure_solidworks_installed()
    sw = None

    # Prefer connecting to an already-running instance.
    try:
        sw = win32com_client.GetActiveObject("SldWorks.Application")
        print("Connected to a running SolidWorks instance")
    except Exception:
        prog_id = "SldWorks.Application"
        if version:
            revision = (version - 2000) + 8
            prog_id = f"SldWorks.Application.{revision}"

        sw = win32com_client.Dispatch(prog_id)
        sw.Visible = visible
        print(f"Started a new SolidWorks instance (ProgID: {prog_id})")
        time.sleep(wait_seconds)

    model = sw.ActiveDoc
    if model:
        doc_types = {1: "part", 2: "assembly", 3: "drawing"}
        doc_type = get_com_member(model, "GetType")
        title = get_com_member(model, "GetTitle")
        print(f"Current document: {title} (type: {doc_types.get(doc_type, 'unknown')})")
    else:
        print("No document is currently open")

    return sw, model


def get_sw_version(sw):
    """Get the SolidWorks version information."""
    rev = get_com_member(sw, "RevisionNumber")
    major = int(rev.split(".")[0])
    year = major - 8 + 2000
    return {"revision": rev, "year": year, "major": major}


def find_template(sw, doc_type="part"):
    """
    Automatically locate a SolidWorks document template.

    Args:
        sw: SolidWorks application object
        doc_type: "part" | "assembly" | "drawing"

    Returns:
        template file path string
    """
    doc_type, _ = normalize_doc_type(doc_type)

    # swUserPreferenceStringValue_e: swDefaultTemplatePart=8, swDefaultTemplateAssembly=9,
    # swDefaultTemplateDrawing=10, swFileLocationsDocumentTemplates=6 (";"-separated
    # folders). Values checked against the SolidWorks 2025 swconst.tlb.
    type_map = {
        "part": (8, "*.prtdot"),
        "assembly": (9, "*.asmdot"),
        "drawing": (10, "*.drwdot"),
    }

    preference, pattern = type_map.get(doc_type, type_map["part"])
    default_path = sw.GetUserPreferenceStringValue(preference)
    template_folders = sw.GetUserPreferenceStringValue(6)
    candidates = ";".join(str(value) for value in (default_path, template_folders) if value)
    if candidates:
        for candidate_root in candidates.split(";"):
            candidate_root = _expand_path(candidate_root.strip().strip('"'))
            if not candidate_root:
                continue

            if os.path.isfile(candidate_root):
                return candidate_root

            if os.path.isdir(candidate_root):
                matches = glob.glob(os.path.join(candidate_root, pattern))
                if matches:
                    return matches[0]

    # "chinese-simplified" is a real SolidWorks install path segment for the
    # Chinese-UI language pack; keep it as-is.
    search_dirs = [
        r"C:\ProgramData\SolidWorks\SOLIDWORKS *\templates",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\chinese-simplified",
    ]
    for search_dir in search_dirs:
        matches = glob.glob(os.path.join(os.path.expandvars(search_dir), pattern))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"Could not find a {doc_type} template file; please specify the path manually")


def new_document(sw, doc_type="part", template_path=None):
    """
    Create a new document.

    Args:
        sw: SolidWorks application object
        doc_type: "part" | "assembly" | "drawing"
        template_path: template path; None auto-locates one

    Returns:
        the new IModelDoc2 object
    """
    doc_type, _ = normalize_doc_type(doc_type)
    if not template_path:
        template_path = find_template(sw, doc_type)
    else:
        template_path = _expand_path(template_path)

    model = sw.NewDocument(template_path, 0, 0, 0)
    if model is None:
        for _ in range(20):
            model = sw.ActiveDoc
            if model is not None:
                break
            time.sleep(0.25)

    if model is None:
        raise RuntimeError(f"Failed to create {DOC_TYPE_LABELS.get(doc_type, doc_type)} document; SolidWorks did not return an active document")

    print(f"Created a new {DOC_TYPE_LABELS.get(doc_type, doc_type)} document")
    return model


def open_document(sw, file_path, read_only=False, silent=False, raise_on_error=False):
    """
    Open an existing document.

    Args:
        sw: SolidWorks application object
        file_path: full file path
        read_only: whether to open in read-only mode
        silent: whether to open silently
        raise_on_error: whether to raise an exception on failure

    Returns:
        IModelDoc2 object
    """
    file_path = _expand_path(file_path)
    if not os.path.exists(file_path):
        message = f"File does not exist: {file_path}"
        if raise_on_error:
            raise FileNotFoundError(message)
        print(message)
        return None

    ext = os.path.splitext(file_path)[1].lower()
    type_map = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3, ".step": 1, ".stp": 1, ".igs": 1, ".iges": 1}
    doc_type = type_map.get(ext, 1)

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    options = 2 if read_only else 0  # swOpenDocOptions_ReadOnly = 2
    if silent:
        options |= 1  # swOpenDocOptions_Silent = 1

    model = sw.OpenDoc6(file_path, doc_type, options, "", errors, warnings)
    if model:
        print(f"Opened: {file_path}")
    else:
        message = f"Open failed, error code: {errors.value}, warning code: {warnings.value}"
        if raise_on_error:
            raise RuntimeError(message)
        print(message)
    return model


def save_document(model, file_path=None):
    """
    Save a document.

    Args:
        model: IModelDoc2 object
        file_path: save-as path; None saves to the current location

    Returns:
        bool success/failure
    """
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    if file_path:
        file_path = _expand_path(file_path)
        _ensure_parent_dir(file_path)
        success = model.Extension.SaveAs(
            file_path, 0, 1, create_empty_dispatch_variant(), errors, warnings
        )
    else:
        success = model.Save3(1, errors, warnings)

    if success:
        print(f"Save succeeded: {file_path or get_com_member(model, 'GetPathName')}")
    else:
        print(f"Save failed, error code: {errors.value}, warning code: {warnings.value}")
    return bool(success)


def mm(value):
    """Convert millimeters to meters (SolidWorks API units)."""
    return value / 1000.0


def deg(value):
    """Convert degrees to radians."""
    import math
    return value * math.pi / 180.0
