"""Loopback-only UI verification transport over the same validated business layer.

This thin development adapter does not introduce another CAD/agent implementation.
The eventual Tauri transport can dispatch the same operations without HTTP.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from urllib.parse import parse_qs, unquote, urlparse
import uuid

from .service import DesignService
from .reference_images import (MAX_UPLOAD_REQUEST_BYTES, get_reference_images, public_reference,
                               read_reference_image, save_reference_image)
from .storage import read_json, safe_id, sha256
from .model_settings import SettingsStore
from .paths import PROJECT_ROOT as PROJECT, DEFAULT_STORE



def _conversation(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 80:
        raise ValueError("Conversation must contain at most 80 user or assistant messages")
    messages, total = [], 0
    for item in value:
        if (not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}
                or not isinstance(item.get("text"), str) or len(item["text"]) > 10000):
            raise ValueError("Conversation requires user/assistant roles and text of at most 10,000 characters")
        total += len(item["text"])
        if total > 40000:
            raise ValueError("Conversation text must contain at most 40,000 characters")
        messages.append({"role": item["role"], "text": item["text"]})
    return messages


class Application:
    def __init__(self, store: Path, settings: SettingsStore | None = None):
        self.service = DesignService(store)
        self.settings = settings if settings is not None else SettingsStore()
        self.assets: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mechanical-task")
        self.lock = threading.Lock()
        self.active: str | None = None

    def _assets(self, result: dict) -> list[dict]:
        assets = []
        for item in result.get("artifacts", []):
            path = Path(item["path"]).resolve()
            if not path.is_relative_to(self.service.root):
                raise ValueError("Artifact is outside the application store")
            artifact_id = item["sha256"]
            self.assets[artifact_id] = {**item, "path": path}
            assets.append({"kind": item["kind"], "url": f"/api/artifacts/{artifact_id}",
                           "filename": path.name, "sha256": artifact_id, "size_bytes": item["size_bytes"]})
        return assets

    def current(self, task_id: str | None = None) -> dict:
        pattern = f"{safe_id(task_id)}/pending-review.json" if task_id else "*/pending-review.json"
        pending_files = sorted((self.service.root / "tasks").glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        pending_id = read_json(pending_files[0])["job_id"] if pending_files else None
        if task_id is None:
            tasks = sorted((self.service.root / "tasks").glob("*/current.json"),
                           key=lambda path: path.stat().st_mtime, reverse=True)
            if not tasks:
                return {"status": "empty", "state": None, "result": None, "assets": [], "pending_job_id": pending_id}
            task_id = tasks[0].parent.name
        state = self.service.current(task_id)
        if state is None:
            return {"status": "empty", "state": None, "result": None, "assets": [], "pending_job_id": pending_id}
        self.service._verify_current(state)
        result = read_json(Path(state["result_path"]))
        return {**self._payload(state, result, "ready", state["job_id"]), "pending_job_id": pending_id}

    def _payload(self, state: dict, result: dict, status: str, job_id: str) -> dict:
        public_state = {key: state[key] for key in ("task_id", "revision", "semantic_hash", "task")}
        public_result = {key: copy.deepcopy(result[key]) for key in
                         ("status", "checks", "mapping", "visual_review", "not_covered", "geometry") if key in result}
        assets = self._assets(result)
        public_result["artifacts"] = assets
        return {"status": status, "state": public_state, "result": public_result,
                "assets": assets, "job_id": job_id}

    def job(self, job_id: str) -> dict:
        receipt = read_json(self.service.root / "jobs" / f"{safe_id(job_id)}.json")
        if "result" not in receipt:
            return {key: value for key, value in receipt.items() if key in ("status", "job_id", "error")}
        output = Path(receipt["output_dir"])
        task, plan = read_json(output / "task.json"), read_json(output / "plan.json")
        state = {"task_id": task["task_id"], "revision": task["revision"], "semantic_hash": plan["semantic_hash"], "task": task}
        return self._payload(state, receipt["result"], receipt["status"], job_id)

    def start(self, function) -> dict:
        with self.lock:
            if self.active is not None:
                raise RuntimeError("Another model/CAD operation is still running")
            operation_id = uuid.uuid4().hex
            self.active = operation_id
            self.operations[operation_id] = {"operation_id": operation_id, "status": "running"}
        def work():
            try:
                result = function()
                operation = {"operation_id": operation_id, "status": "done", "result": result}
            except Exception as error:
                operation = {"operation_id": operation_id, "status": "failed",
                             "error": f"{type(error).__name__}: {error}"}
            with self.lock:
                self.operations[operation_id] = operation
                self.active = None
        self.pool.submit(work)
        return {"operation_id": operation_id, "status": "running"}

    def dispatch(self, route: str, payload: dict) -> dict:
        if route == "/api/settings":
            return self.settings.save(payload)
        if route == "/api/settings/test":
            config = self.settings.snapshot()
            def test_model():
                if config.kind == "codex":
                    from .agent import probe_cli
                    probe = probe_cli()
                    return {"ok": probe["available"], "status": "ready" if probe["available"] else "failed", "provider": "codex",
                            "model": config.model or "CLI default",
                            "message": "Codex CLI 已登录且支持结构化输出。" if probe["available"] else "Codex CLI 不可用或未登录。"}
                from .model_providers import test_connection
                return test_connection(config)
            return self.start(test_model)
        if route == "/api/reference-images":
            return public_reference(save_reference_image(self.service.root, payload.get("name"), payload.get("data_url")))
        if route == "/api/interpret":
            from .agent import interpret_brief
            brief = payload.get("brief", "")
            references = get_reference_images(self.service.root, payload.get("image_ids", []))
            conversation = _conversation(payload.get("conversation"))
            if not isinstance(brief, str) or len(brief) > 20000 or (not brief.strip() and not references):
                raise ValueError("Provide a brief of at most 20,000 characters or at least one reference image")
            brief = brief.strip() or "请根据这些参考图整理工程建模需求，并询问缺少的尺寸和结构信息。"
            current = payload.get("current_task")
            selection = payload.get("selection")
            if current is not None:
                state = self.service.current(current.get("task_id", ""))
                if state is None or current != state["task"]:
                    raise ValueError("Only the current published task can be used as a modification baseline")
                self.service._verify_current(state)
                if selection is not None:
                    if (selection.get("task_id") != state["task_id"]
                            or selection.get("revision") != state["revision"]
                            or selection.get("semantic_hash") != state["semantic_hash"]):
                        raise ValueError("The selected object belongs to a stale preview")
                    name = str(selection.get("parameter_id", "")).split("/")[-1]
                    if name not in current["parameters"]:
                        raise ValueError("Unknown semantic parameter")
            config = self.settings.snapshot()
            return self.start(lambda: interpret_brief(brief, current_task=current, selection=selection,
                                                      output_dir=self.service.root / "agent", reference_images=references,
                                                      conversation=conversation, model_config=config))
        if route == "/api/validate":
            from .rules import compile_plan
            plan = compile_plan(payload["task"]).model_dump(mode="json")
            return {"status": "ready", "plan": plan}
        if route == "/api/run":
            from .rules import compile_plan
            task = payload["task"]
            compile_plan(task)  # Reject invalid dimensions before scheduling any CAD write.
            return self.start(lambda: self.service.submit(task))
        if route == "/api/review":
            return self.start(lambda: self.service.complete_review(
                payload["job_id"], approved=payload["approved"], reviewer=payload["reviewer"], notes=payload["notes"]))
        raise KeyError("Unknown API route")


def handler_for(application: Application, port: int):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, value) -> None:
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _origin_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in {
                f"http://127.0.0.1:{port}", f"http://localhost:{port}",
                "http://127.0.0.1:5175", "http://localhost:5175",
            }

        def do_GET(self):
            if not self._origin_allowed():
                return self._json(403, {"error": "Local application origin required"})
            parsed = urlparse(self.path)
            route = parsed.path
            try:
                if route == "/api/health":
                    return self._json(200, {"app": "mechanical-design-app", "status": "ready", "scope": "geometry_review", "transport": "local_ui_validation"})
                if route == "/api/settings":
                    return self._json(200, application.settings.public())
                if route == "/api/current":
                    task_id = parse_qs(parsed.query).get("task_id", [None])[0]
                    return self._json(200, application.current(task_id))
                if route.startswith("/api/job/"):
                    return self._json(200, application.job(route.rsplit("/", 1)[1]))
                if route.startswith("/api/operations/"):
                    operation_id = safe_id(route.rsplit("/", 1)[1])
                    with application.lock:
                        operation = application.operations.get(operation_id)
                    return self._json(200 if operation else 404, operation or {"error": "Unknown operation"})
                if route.startswith("/api/artifacts/"):
                    item = application.assets.get(route.rsplit("/", 1)[1])
                    if item is None:
                        return self._json(404, {"error": "Unknown artifact; reload the current model"})
                    path = item["path"]
                    if not path.is_file() or path.stat().st_size != item["size_bytes"] or sha256(path) != item["sha256"]:
                        return self._json(409, {"error": "Artifact changed after verification"})
                    return self._file(path)
                if route.startswith("/api/reference-images/"):
                    _, data = read_reference_image(application.service.root, unquote(route.rsplit("/", 1)[1]))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    return self.wfile.write(data)
                if route.startswith("/api/"):
                    return self._json(404, {"error": "Unknown API route"})
                root = (PROJECT / "ui" / "dist").resolve()
                path = (root / unquote(route).lstrip("/")).resolve()
                if not path.is_relative_to(root):
                    return self._json(403, {"error": "Invalid asset path"})
                if path.is_dir():
                    path /= "index.html"
                if not path.is_file():
                    return self._json(404, {"error": "UI build not present; use the Vite preview on port 5175"})
                return self._file(path)
            except (KeyError, ValueError, OSError, RuntimeError) as error:
                self._json(409, {"error": str(error)})

        def _file(self, path: Path):
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self._origin_allowed():
                return self._json(403, {"error": "Local application origin required"})
            try:
                route = urlparse(self.path).path
                size = int(self.headers.get("Content-Length", "0"))
                limit = MAX_UPLOAD_REQUEST_BYTES if route == "/api/reference-images" else 1024 * 1024
                if not 0 < size <= limit or not self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._json(400, {"error": "A bounded JSON request is required"})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Request must be a JSON object")
                self._json(200, application.dispatch(route, payload))
            except (KeyError, ValueError, TypeError) as error:
                self._json(400, {"error": str(error)})
            except RuntimeError as error:
                self._json(409, {"error": str(error)})

        def log_message(self, format, *args):
            # Do not log prompts, headers, credentials or query strings.
            pass
    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args(argv)
    application = Application(args.store)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(application, args.port))
    print(f"Mechanical Design local UI: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.pool.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
