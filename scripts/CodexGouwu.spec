# -*- mode: python ; coding: utf-8 -*-
"""Explicit resource allowlist: no source results, .local settings, or credentials."""
import json
import importlib.metadata
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH).resolve().parent
resource = "resources/mechanical-design-app"
vendor = project / "vendor"
skill = vendor / "mechanical-design-sop"
helpers = vendor / "solidworks-agent/skills/solidworks/scripts"
provider = vendor / "solidworks-automation-skill/apps/desktop/cad_workbench/agent_providers.py"
defaults = project / ".local/desktop-package-data/desktop-defaults.json"
defaults.parent.mkdir(parents=True, exist_ok=True)
defaults.write_text(json.dumps({"store_mode": "local_appdata"}), encoding="utf-8")
lock = json.loads((project / "rules/lock.json").read_text(encoding="utf-8"))
datas = [(str(project / "ui/dist"), resource + "/ui/dist"),
         (str(project / "rules/lock.json"), resource + "/rules"),
         (str(defaults), resource),
         (str(project / "THIRD_PARTY.md"), resource),
         (str(project / "ACKNOWLEDGEMENTS.md"), resource),
         (str(project / "vendor/SOURCES.json"), resource + "/vendor"),
         (str(project / "docs/DESKTOP.md"), resource + "/docs"),
         (str(provider), resource + "/vendor/solidworks-automation-skill/apps/desktop/cad_workbench"),
         (str(vendor / "solidworks-agent/LICENSE"), resource + "/vendor/solidworks-agent"),
         (str(vendor / "solidworks-agent/NOTICE"), resource + "/vendor/solidworks-agent"),
         (str(vendor / "solidworks-automation-skill/LICENSE"), resource + "/vendor/solidworks-automation-skill")]
for source in sorted((project / "licenses").rglob("*")):
    if source.is_file():
        datas.append((str(source), str(Path(resource) / "licenses" / source.relative_to(project / "licenses").parent)))
for relative in lock["files"]:
    target = Path(resource) / "vendor/mechanical-design-sop" / Path(relative).parent
    datas.append((str(skill / relative), str(target)))
# Runtime imports in _sw() use these original, unmodified helper modules.
helper_modules = ["sw_preflight", "sw_resource_guard", "sw_connect", "sw_documents", "sw_inspect",
                  "sw_part", "sw_review", "sw_runtime", "sw_evidence"]
for name in helper_modules:
    datas.append((str(helpers / f"{name}.py"), resource + "/vendor/solidworks-agent/skills/solidworks/scripts"))

datas.append((str(Path(sys.base_prefix) / "LICENSE.txt"), "resources/licenses/python"))
for name in ("pydantic", "pydantic_core", "pillow", "shapely", "numpy", "pywin32", "comtypes",
             "annotated-types", "typing_extensions", "typing-inspection", "setuptools", "packaging", "pyinstaller"):
    distribution = importlib.metadata.distribution(name)
    for relative in distribution.files or []:
        parts = relative.parts
        if "licenses" in parts and any(str(part).endswith(".dist-info") for part in parts):
            license_relative = Path(*parts[parts.index("licenses") + 1:])
            datas.append((str(distribution.locate_file(relative)),
                          str(Path("resources/licenses") / name / license_relative.parent)))
for name in ("react", "react-dom", "three"):
    datas.append((str(project / "ui/node_modules" / name / "LICENSE"), "resources/licenses/" + name))

hidden = helper_modules + ["pythoncom", "pywintypes", "win32crypt", "win32com.client"]
hidden += collect_submodules("comtypes", filter=lambda name: not name.startswith("comtypes.test"))
a = Analysis([str(project / "scripts/desktop_entry.py")], pathex=[str(project), str(helpers)],
             binaries=[], datas=datas, hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["pytest", "tkinter", "matplotlib", "IPython", "numpy.tests"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="codex的构物", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, version=str(project / "scripts/desktop-version.txt"),
          icon=str(project / "ui/public/brand/app.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="codex的构物")
