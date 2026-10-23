"""Read-only resources and writable local data for source and desktop builds."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


FROZEN = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = (Path(sys._MEIPASS) / "resources" / "mechanical-design-app"
                if FROZEN else Path(__file__).resolve().parents[1])
VENDOR_ROOT = PROJECT_ROOT / "vendor"


def _dependency_root(name: str) -> Path:
    """Prefer the pinned in-repository snapshot; retain legacy source checkouts."""
    bundled = VENDOR_ROOT / name
    return bundled if bundled.is_dir() or FROZEN else PROJECT_ROOT.parent / name


SKILL_PATH = _dependency_root("mechanical-design-sop") / "SKILL.md"
HELPERS = _dependency_root("solidworks-agent") / "skills" / "solidworks" / "scripts"
PROVIDER_PATH = (_dependency_root("solidworks-automation-skill")
                 / "apps" / "desktop" / "cad_workbench" / "agent_providers.py")
LOCAL_STATE = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "CodexGouwu"

if FROZEN:
    # New releases use user-local storage. Read legacy packages' explicit store
    # as well so their existing absolute artifact paths stay valid.
    _defaults = json.loads((PROJECT_ROOT / "desktop-defaults.json").read_text(encoding="utf-8"))
    DEFAULT_STORE = (LOCAL_STATE / "data" if _defaults.get("store_mode") == "local_appdata"
                     else Path(_defaults["store"]).resolve())
else:
    DEFAULT_STORE = PROJECT_ROOT / "results" / "integration"
