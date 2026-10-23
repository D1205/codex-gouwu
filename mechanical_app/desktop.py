"""Windows desktop entry point; packaged resources, one local server, no CAD launch."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import ctypes
import importlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time
import traceback
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser

from .paths import DEFAULT_STORE, FROZEN, HELPERS, LOCAL_STATE, PROJECT_ROOT, SKILL_PATH

APP_NAME = "codex的构物"
_HELPER_ARGUMENTS = {
    "sw_preflight.py": ("--no-install",),
    "sw_resource_guard.py": ("--target", "solidworks", "--allow-reuse"),
}


def _helper(filename: str, destination: Path, arguments: list[str]) -> int:
    if filename not in _HELPER_ARGUMENTS or tuple(arguments) != _HELPER_ARGUMENTS[filename]:
        raise ValueError("Only packaged, read-only preflight commands are supported")
    stdout, stderr = io.StringIO(), io.StringIO()
    returncode = 0
    previous = sys.argv
    if str(HELPERS) not in sys.path:
        sys.path.insert(0, str(HELPERS))
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            sys.argv = [str(HELPERS / filename), *arguments]
            try:
                runpy.run_path(str(HELPERS / filename), run_name="__main__")
            except SystemExit as error:
                returncode = int(error.code or 0)
            except Exception:
                traceback.print_exc()
                returncode = 1
    finally:
        sys.argv = previous
    destination.write_text(json.dumps({"returncode": returncode, "stdout": stdout.getvalue(),
                                       "stderr": stderr.getvalue()}, ensure_ascii=False), encoding="utf-8")
    return returncode


def _configure_com_cache() -> None:
    if not FROZEN:
        return
    # EnsureModule must be able to generate wrappers for this machine's installed
    # SolidWorks type libraries. Nothing is written into the executable bundle.
    import win32com
    import win32com.client.gencache as gencache
    import win32com.gen_py
    generated = LOCAL_STATE / "gen_py"
    generated.mkdir(parents=True, exist_ok=True)
    win32com.__gen_path__ = str(generated)
    win32com.gen_py.__path__ = [str(generated)]
    gencache.is_readonly = False


def _health(port: int) -> dict | None:
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(Request(f"http://127.0.0.1:{port}/api/health"), timeout=1) as response:
            result = json.load(response)
    except URLError as error:
        if isinstance(error.reason, (ConnectionRefusedError, TimeoutError, OSError)):
            return None
        raise RuntimeError(f"Cannot inspect local port {port}") from error
    except (OSError, TimeoutError):
        return None
    except (ValueError, TypeError) as error:
        raise RuntimeError(f"Port {port} does not belong to this application") from error
    if result.get("app") != "mechanical-design-app" or result.get("status") != "ready":
        raise RuntimeError(f"Port {port} does not belong to this application")
    return result


def _open_browser(port: int, disabled: bool) -> None:
    if not disabled:
        webbrowser.open(f"http://127.0.0.1:{port}", new=2)


def _self_check(destination: Path) -> int:
    from .rules import verify_skill_lock
    from .cad import _helper_process, _sw
    from .agent import PROVIDER_PATH
    report = {"app": APP_NAME, "frozen": FROZEN, "project_resources": str(PROJECT_ROOT),
              "store": str(DEFAULT_STORE), "config_directory": str(LOCAL_STATE), "checks": {}}
    checks = report["checks"]
    try:
        checks["ui"] = (PROJECT_ROOT / "ui" / "dist" / "index.html").is_file()
        checks["locked_skill"] = SKILL_PATH.is_file() and not verify_skill_lock()
        checks["provider_discovery"] = PROVIDER_PATH.is_file()
        spec = importlib.util.spec_from_file_location("desktop_provider_check", PROVIDER_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        checks["provider_discovery_import"] = True
        for name in ("pythoncom", "win32com.client", "comtypes", "PIL.Image", "shapely"):
            importlib.import_module(name)
            checks[f"import:{name}"] = True
        _sw()  # Import dependency graph only; never attach, open, or create CAD.
        checks["cad_helpers_import"] = True
        report["helpers"] = {}
        for name, arguments in _HELPER_ARGUMENTS.items():
            result = _helper_process(name, list(arguments))
            report["helpers"][name] = {"returncode": result.returncode,
                                        "stdout": result.stdout, "stderr": result.stderr}
            checks[f"helper:{name}"] = result.returncode == 0
        report["passed"] = all(checks.values())
    except Exception:
        report["passed"] = False
        report["error"] = traceback.format_exc()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


def _run_server(args) -> int:
    if _health(args.port):
        _open_browser(args.port, args.no_browser)
        return 0
    mutex = None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        mutex = kernel.CreateMutexW(None, False, f"Local\\CodexGouwuDesktop-{args.port}")
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(mutex)
            for _ in range(40):
                if _health(args.port):
                    _open_browser(args.port, args.no_browser)
                    return 0
                time.sleep(0.3)
            raise RuntimeError("The application is already starting; see the local desktop log")
    try:
        from http.server import ThreadingHTTPServer
        from .server import Application, handler_for
        application = Application(args.store)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(application, args.port))
        record = LOCAL_STATE / f"desktop-{args.port}.json"
        record.write_text(json.dumps({"pid": os.getpid(), "executable": sys.executable,
                                     "url": f"http://127.0.0.1:{args.port}", "store": str(args.store)},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        def show_when_ready():
            for _ in range(30):
                if _health(args.port):
                    _open_browser(args.port, args.no_browser)
                    return
                time.sleep(0.2)
        threading.Thread(target=show_when_ready, daemon=True).start()
        try:
            server.serve_forever()
        finally:
            server.server_close()
            application.pool.shutdown(wait=True)
            record.unlink(missing_ok=True)
    finally:
        if mutex:
            kernel.CloseHandle(mutex)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop launcher")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-check", type=Path)
    parser.add_argument("--helper", choices=tuple(_HELPER_ARGUMENTS))
    parser.add_argument("--helper-result", type=Path)
    parser.add_argument("helper_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.helper:
        if args.helper_result is None:
            raise ValueError("A helper report destination is required")
        arguments = args.helper_arguments[1:] if args.helper_arguments[:1] == ["--"] else args.helper_arguments
        return _helper(args.helper, args.helper_result, arguments)
    LOCAL_STATE.mkdir(parents=True, exist_ok=True)
    try:
        _configure_com_cache()
        if args.self_check:
            return _self_check(args.self_check)
        if not 1024 <= args.port <= 65535:
            raise ValueError("Choose a local application port between 1024 and 65535")
        return _run_server(args)
    except Exception:
        details = traceback.format_exc()
        log = LOCAL_STATE / "desktop.log"
        if log.is_file() and log.stat().st_size > 1024 * 1024:
            log.replace(log.with_suffix(".previous.log"))
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n{details}")
        if args.self_check:
            args.self_check.write_text(json.dumps({"passed": False, "error": details}), encoding="utf-8")
        elif os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, f"无法启动{APP_NAME}。\n请查看：{log}\n\n{details.splitlines()[-1]}",
                                            APP_NAME, 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
