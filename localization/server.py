"""Zero-dependency web server for the localization preflight prototype.

Run with ``python3 app.py``. Only the Python standard library and Pillow are
required; there is no npm build step and no external service.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .dataset import DatasetError, build_dataset, list_demos, load_demo, parse_text
from .engine import analyze
from .llm import LLMConfig
from .report import export as export_report

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
ASSET_DIR = ROOT / "assets"
MAX_BODY = 2 * 1024 * 1024

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}


def _safe_join(base: Path, relative: str) -> Optional[Path]:
    relative = unquote(relative).lstrip("/")
    if not relative:
        return None
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalizationPreflight/" + __version__
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):  # pragma: no cover - client gone
                pass

    def _json(self, status: int, data: Any, extra: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _attachment(self, content: str, mime: str, filename: str, charset: str = "utf-8") -> None:
        body = content.encode(charset)
        self._send(
            200,
            body,
            mime,
            {"Content-Disposition": 'attachment; filename="%s"' % filename},
        )

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_BODY:
            raise ValueError("请求体超过 2MB 上限")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是合法 JSON: %s" % exc) from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    # -- routing ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/health":
            config = LLMConfig.from_env()
            self._json(
                200,
                {
                    "status": "ok",
                    "engine": "deterministic",
                    "version": __version__,
                    "llm_configured": config.enabled,
                    "llm_model": config.model if config.enabled else "",
                    "font_present": (ASSET_DIR / "fonts" / "NotoSans-Variable.ttf").exists(),
                    "core_checks": [
                        "placeholder integrity",
                        "font-metric width risk",
                    ],
                    "experimental_checks": [
                        "term disambiguation",
                        "source-context gaps",
                        "register risk",
                    ],
                },
            )
            return
        if path == "/api/demos":
            self._json(200, {"demos": list_demos()})
            return
        if path == "/api/demo":
            name = (query.get("name") or ["zh_ptbr"])[0]
            try:
                payload, _ = load_demo(name)
            except DatasetError as exc:
                self._error(404, str(exc))
                return
            self._json(200, payload)
            return
        if path in ("/", "/index.html"):
            self._serve(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            self._serve_path(WEB_DIR, path[len("/static/") :])
            return
        if path.startswith("/assets/"):
            self._serve_path(ASSET_DIR, path[len("/assets/") :])
            return
        self._error(404, "页面不存在")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._read_json()
        except ValueError as exc:
            self._error(400, str(exc))
            return
        try:
            dataset = self._dataset_from_request(data)
        except (DatasetError, ValueError) as exc:
            self._error(400, str(exc))
            return
        if path == "/api/analyze":
            try:
                report = analyze(
                    dataset,
                    llm_enhance=bool(data.get("llm_enhance")),
                    llm_config=LLMConfig.from_env(),
                )
            except Exception:  # pragma: no cover - defensive, return safe message
                traceback.print_exc()
                self._error(500, "分析过程中出现内部错误")
                return
            self._json(200, report.to_dict())
            return
        if path == "/api/export":
            query = parse_qs(parsed.query)
            fmt = (query.get("format") or [data.get("format") or "json"])[0]
            try:
                report = analyze(dataset)
                bundle = export_report(report, fmt)
            except ValueError as exc:
                self._error(400, str(exc))
                return
            except Exception:  # pragma: no cover
                traceback.print_exc()
                self._error(500, "导出过程中出现内部错误")
                return
            charset = "utf-8-sig" if bundle["mime"].endswith("utf-8-sig") else "utf-8"
            self._attachment(bundle["content"], bundle["mime"], bundle["filename"], charset)
            return
        self._error(404, "接口不存在")

    # -- request helpers -------------------------------------------------
    def _dataset_from_request(self, data: Dict[str, Any]):
        overrides = data.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError("overrides 必须是对象")
        overrides = overrides or {}
        for name in ("target_locale", "source_locale", "ui_profile", "project"):
            if data.get(name):
                overrides[name] = data[name]
        if data.get("text") is not None:
            return parse_text(str(data["text"]), str(data.get("format") or "auto"), overrides)
        if data.get("dataset") is not None:
            return build_dataset(data["dataset"], overrides)
        raise ValueError("缺少 text 或 dataset 字段")

    # -- static files ----------------------------------------------------
    def _serve(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "文件不存在")
            return
        self._send(200, body, content_type, {"Cache-Control": "no-cache"})

    def _serve_path(self, base: Path, relative: str) -> None:
        path = _safe_join(base, relative)
        if not path:
            self._error(404, "文件不存在")
            return
        content_type = MIME.get(path.suffix.lower(), "application/octet-stream")
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "文件不存在")
            return
        cache = "public, max-age=3600" if path.suffix.lower() in (".ttf", ".woff2", ".png", ".svg") else "no-cache"
        self._send(200, body, content_type, {"Cache-Control": cache})

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - server log
        sys.stderr.write("[preflight] %s - %s\n" % (self.address_string(), fmt % args))


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="本地化预检 Web 原型")
    parser.add_argument("--host", default=os.environ.get("PREFLIGHT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PREFLIGHT_PORT", "8000")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print("本地化预检台已启动: http://%s:%d" % (args.host, server.server_address[1]))
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":  # pragma: no cover
    main()
