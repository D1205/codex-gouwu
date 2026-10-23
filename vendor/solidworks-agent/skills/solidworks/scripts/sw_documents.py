"""Document ownership: close only what this process created or opened.

An agent often shares a SolidWorks session with a human who has their own documents
open. Titles and paths are diagnostics, never proof of ownership: a new unsaved
``Part1`` or a reopened file can reuse a title or path that belongs to someone else.
Ownership is the canonical COM ``IUnknown`` identity of the object returned by this
process's own create/open/import call plus that object's real dependency graph.
pywin32 compares ``PyIUnknown`` objects by COM identity. Identities are never
serialized and never carry over to another process or application session.
"""
from __future__ import annotations

try:
    from .sw_connect import get_com_member
except ImportError:
    from sw_connect import get_com_member


def com_identity(document):
    """Canonical COM identity of a dispatch wrapper."""
    import pythoncom

    return document._oleobj_.QueryInterface(pythoncom.IID_IUnknown)


def document_dependencies(model, member=get_com_member):
    """Documents that ``model`` actually references: components or drawing views.

    ``IDrawingDoc.GetViews`` returns one array of views per sheet. Members of those
    nested SAFEARRAYs can arrive as raw ``PyIDispatch`` objects, so each view is
    wrapped before its ``ReferencedDocument`` is read.
    """
    kind = member(model, "GetType")
    if kind == 2:
        return [member(component, "GetModelDoc2")
                for component in list(model.GetComponents(False) or [])]
    if kind == 3:
        from win32com.client import dynamic

        views = [dynamic.DumbDispatch(getattr(view, "_oleobj_", view))
                 for sheet in list(member(model, "GetViews") or []) for view in sheet]
        return [document for view in views
                if (document := view.ReferencedDocument) is not None]
    return []


class DocumentOwnership:
    """Ephemeral, in-process record of documents this run may close.

    Call ``validate()`` immediately before an operation that creates or opens a
    document, then ``claim_returned(result)``. ``close``/``close_all`` refuse to act
    if any unknown document is open, so a mixed inventory closes nothing.
    """

    def __init__(self, application, member=get_com_member, dependencies=document_dependencies,
                 identity=com_identity):
        self.application = application
        self.member = member
        self.dependencies = dependencies
        self.identity = identity
        self._owned = []

    def inventory(self):
        return list(self.member(self.application, "GetDocuments") or [])

    def _owns(self, document):
        key = self.identity(document)
        return any(key == owned for owned in self._owned)

    def describe(self, document):
        return {"title": self.member(document, "GetTitle"),
                "path": self.member(document, "GetPathName")}

    def require_empty(self):
        """Refuse to start when any document is open; closes nothing."""
        documents = self.inventory()
        if documents:
            raise RuntimeError("Unowned documents open at stage start; no documents closed: "
                               + repr([self.describe(doc) for doc in documents]))

    def validate(self):
        """Return the inventory if every open document is owned and titles are unique."""
        documents = self.inventory()
        unknown = [self.describe(doc) for doc in documents if not self._owns(doc)]
        if unknown:
            raise RuntimeError("Unowned documents open; no close authorized: " + repr(unknown))
        titles = [self.member(doc, "GetTitle").casefold() for doc in documents]
        if len(set(titles)) != len(titles) or any(not title for title in titles):
            raise RuntimeError("Ambiguous document titles; no close authorized")
        return documents

    def claim_returned(self, root):
        """Claim only the returned object and its real native dependency graph.

        Never claim an arbitrary post-operation inventory or a filename match.
        """
        pending = [root]
        visited = []
        while pending:
            document = pending.pop()
            if document is None:
                raise RuntimeError("Null document in returned dependency graph")
            key = self.identity(document)
            if any(key == seen for seen in visited):
                continue
            visited.append(key)
            if not self._owns(document):
                self._owned.append(key)
            pending.extend(self.dependencies(document))
        self.validate()

    def close(self, document):
        documents = self.validate()  # Whole inventory first: mixed inventories close nothing.
        key = self.identity(document)
        matches = [doc for doc in documents if self.identity(doc) == key]
        if len(matches) != 1:
            raise RuntimeError("Close target is not exactly one currently owned document")
        self.application.CloseDoc(self.member(matches[0], "GetTitle"))
        # Referenced parts may stay loaded until their owning assembly closes. Forget
        # every object that disappeared, so reopening requires a new claim.
        current = [self.identity(doc) for doc in self.inventory()]
        self._owned = [owned for owned in self._owned if any(owned == key for key in current)]

    def close_all(self):
        documents = self.validate()
        # Closing an assembly can also unload its components. Re-check the entire
        # inventory before each close and skip objects already unloaded.
        for document in documents:
            current = self.validate()
            if any(self.identity(doc) == self.identity(document) for doc in current):
                self.close(document)
        self.require_empty()


def _byref_i4():
    from win32com.client import VARIANT
    import pythoncom

    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def new_owned(app, ownership, template_path):
    """Create a document from a template and claim it."""
    ownership.validate()
    model = app.NewDocument(str(template_path), 0, 0, 0)
    if model is None:
        raise RuntimeError(f"NewDocument returned null for template {template_path}")
    ownership.claim_returned(model)
    return model


def open_owned(app, ownership, path, doc_type, options=1):
    """Open a native document (options 1 = silent) and claim it.

    ``doc_type`` is swDocumentTypes_e: 1 part, 2 assembly, 3 drawing.
    """
    errors, warnings = _byref_i4(), _byref_i4()
    ownership.validate()
    model = app.OpenDoc6(str(path), int(doc_type), int(options), "", errors, warnings)
    if model is None or errors.value:
        raise RuntimeError(f"OpenDoc6 failed for {path}: errors={errors.value}, "
                           f"warnings={warnings.value}")
    ownership.claim_returned(model)
    return model, int(warnings.value)


def import_owned(app, ownership, path):
    """Import a neutral file (STEP, IGES, ...) with LoadFile4 and claim the result.

    Imported assemblies create generated part documents; they are claimed through
    the returned document's dependency graph, never by name.
    """
    errors = _byref_i4()
    data = app.GetImportFileData(str(path))
    ownership.validate()
    model = app.LoadFile4(str(path), "r", data, errors)
    if model is None or errors.value:
        raise RuntimeError(f"LoadFile4 failed for {path}: errors={errors.value}")
    ownership.claim_returned(model)
    return model


def open_document_report(app, member=get_com_member):
    """Read-only list of open documents, for telling the user what is already open."""
    return [{"title": member(doc, "GetTitle"), "path": member(doc, "GetPathName"),
             "type": member(doc, "GetType")}
            for doc in list(member(app, "GetDocuments") or [])]
