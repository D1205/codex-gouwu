"""
SolidWorks automation skill startup preflight.

This module specifically handles two entry-point risks:
1. When Python COM dependencies are missing, ask the user for authorization
   first, then run the pip install automatically.
2. When SolidWorks is not detected, stop immediately and tell the user to
   install it manually or repair the COM registration.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence


PIP_REQUIREMENTS = ("pywin32>=305", "comtypes>=1.2.0")
DEPENDENCY_PROMPT = "The current Python environment is missing comtypes / win32com. Allow the agent to install them now? [Y/N]"


def _configure_stdio_utf8() -> None:
    """Prefer UTF-8 output on legacy Windows code pages so non-ASCII messages display correctly."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_configure_stdio_utf8()


class DependencyInstallDeclined(RuntimeError):
    """The user declined automatic installation of the Python COM dependencies."""


class SolidWorksNotInstalledError(RuntimeError):
    """SolidWorks was not detected on this system."""


@dataclass
class PreflightResult:
    """Preflight check result."""

    missing_packages: List[str]
    dependencies_ready: bool
    solidworks_ready: Optional[bool]


def _module_available(module_name: str) -> bool:
    """Check whether a Python module can be imported."""
    try:
        importlib.import_module(module_name)
        return True
    except ModuleNotFoundError as exc:
        requested_root = module_name.split(".", 1)[0]
        if exc.name in {module_name, requested_root}:
            return False
        raise


def missing_com_dependencies() -> List[str]:
    """Return the names of missing COM dependency packages."""
    checks = (
        ("comtypes", "comtypes>=1.2.0"),
        ("pythoncom", "pywin32>=305"),
        ("win32com.client", "pywin32>=305"),
    )
    missing: List[str] = []
    for module_name, requirement in checks:
        if not _module_available(module_name) and requirement not in missing:
            missing.append(requirement)
    return missing


def pip_install_command(
    python_executable: Optional[str] = None,
    requirements: Sequence[str] = PIP_REQUIREMENTS,
) -> List[str]:
    """Build the pip command that installs the missing dependencies."""
    return [python_executable or sys.executable, "-m", "pip", "install", *requirements]


def shell_command_text(command: Sequence[str]) -> str:
    """Build command text suitable for pasting into a Windows shell."""
    special_chars = set(' <>&|^"')
    parts = []
    for part in command:
        text = str(part)
        if any(char in special_chars for char in text):
            parts.append('"' + text.replace('"', r'\"') + '"')
        else:
            parts.append(text)
    return " ".join(parts)


def install_com_dependencies(
    python_executable: Optional[str] = None,
    requirements: Sequence[str] = PIP_REQUIREMENTS,
) -> None:
    """Run pip install to add the missing Python COM dependencies."""
    subprocess.check_call(pip_install_command(python_executable, requirements))
    importlib.invalidate_caches()


def ask_install_permission(
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> bool:
    """Ask the user for authorization to configure the local Python environment automatically."""
    output_func(DEPENDENCY_PROMPT)
    try:
        answer = input_func("").strip().lower()
    except EOFError:
        answer = ""
    return answer in {"y", "yes"}


def ensure_com_dependencies(
    allow_install: Optional[bool] = None,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> List[str]:
    """
    Make sure comtypes / pywin32 are available.

    Args:
        allow_install: True=install directly, False=do not install, None=ask interactively.
        input_func: input function, swappable for testing.
        output_func: output function, swappable for testing.

    Returns:
        the list of initially missing dependencies.
    """
    missing = missing_com_dependencies()
    if not missing:
        return []

    should_install = allow_install
    if should_install is None:
        should_install = ask_install_permission(input_func=input_func, output_func=output_func)

    if not should_install:
        command = shell_command_text(pip_install_command())
        raise DependencyInstallDeclined(
            "The current Python environment is missing the SolidWorks COM dependencies. "
            "Please run manually:\n"
            f"{command}"
        )

    install_com_dependencies(requirements=tuple(missing))
    still_missing = missing_com_dependencies()
    if still_missing:
        raise ModuleNotFoundError(
            "Still unable to import after installing dependencies: " + ", ".join(still_missing)
        )
    return missing


def import_com_dependencies(allow_install: Optional[bool] = None):
    """
    Import pythoncom, win32com, and VARIANT.

    This function replaces a top-level module import so a ModuleNotFoundError
    does not surface as a bare, unhelpful error.
    """
    ensure_com_dependencies(allow_install=allow_install)
    pythoncom = importlib.import_module("pythoncom")
    client = importlib.import_module("win32com.client")
    return pythoncom, client, client.VARIANT


def _is_windows() -> bool:
    """Check whether the current system is Windows."""
    return os.name == "nt" or platform.system().lower().startswith("win")


def _solidworks_com_registered() -> bool:
    """Check whether the SolidWorks COM ProgID is registered."""
    if not _is_windows():
        return False
    try:
        import winreg

        winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID")
        return True
    except Exception:
        return False


def _solidworks_exe_candidates() -> Iterable[str]:
    """Enumerate common SolidWorks executable paths."""
    patterns = [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*\SLDWORKS.exe",
        r"C:\Program Files\Dassault Systemes\SOLIDWORKS*\SLDWORKS.exe",
    ]
    for pattern in patterns:
        yield from glob.glob(os.path.expandvars(pattern))


def solidworks_installed() -> bool:
    """Determine whether SolidWorks is installed or COM-registered on this machine."""
    if not _is_windows():
        return False
    if _solidworks_com_registered():
        return True
    return any(os.path.exists(path) for path in _solidworks_exe_candidates())


def ensure_solidworks_installed() -> None:
    """Stop immediately with a clear message if SolidWorks is not detected."""
    if solidworks_installed():
        return
    raise SolidWorksNotInstalledError(
        "SolidWorks was not detected. Please install SolidWorks manually and start it "
        "at least once to complete COM registration before using this skill."
    )


def run_preflight(
    allow_install: Optional[bool] = None,
    check_solidworks: bool = True,
) -> PreflightResult:
    """Run the dependency and SolidWorks installation preflight checks."""
    solidworks_ready: Optional[bool] = None
    if check_solidworks:
        ensure_solidworks_installed()
        solidworks_ready = True
    missing = ensure_com_dependencies(allow_install=allow_install)
    return PreflightResult(
        missing_packages=missing,
        dependencies_ready=True,
        solidworks_ready=solidworks_ready,
    )


def _parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="SolidWorks automation skill startup preflight.")
    parser.add_argument("--yes", action="store_true", help="Authorize installation automatically if dependencies are missing.")
    parser.add_argument("--no-install", action="store_true", help="Do not install automatically if dependencies are missing.")
    parser.add_argument("--no-solidworks-check", action="store_true", help="Skip the SolidWorks installation check.")
    return parser.parse_args()


def main() -> int:
    """Command-line entry point."""
    args = _parse_args()
    allow_install = True if args.yes else False if args.no_install else None
    result = run_preflight(
        allow_install=allow_install,
        check_solidworks=not args.no_solidworks_check,
    )
    print("SolidWorks automation skill preflight passed.")
    if result.missing_packages:
        print("Installed missing dependencies: " + ", ".join(result.missing_packages))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DependencyInstallDeclined as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2)
    except SolidWorksNotInstalledError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(3)
