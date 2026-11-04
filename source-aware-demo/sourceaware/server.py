"""Zero-dependency HTTP server for the source-aware localization PoC."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .catalog import Catalog, CatalogError, UnknownStringKey
from .config import LLMConfig, TARGET_LOCALES
from .retrieval import MAX_RESULTS, search
from .translate import TranslationError, Translator

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DEMO_PROJECT_DIR = BASE_DIR / "demo_project"
MAX_BODY = 8 * 1024
MAX_KEY_CHARS = 120

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}
STATIC_SUFFIXES = set(MIME)
CSP = (
    "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'none'; img-src 'self' data:; style-src 'self'; "
    "script-src 'self'; connect-src 'self'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CSP,
}


def _safe_join(base: Path, relative: str) -> Optional[Path]:
    relative = unquote(relative).lstrip("/")
    if not relative or "\x00" in relative:
        return None
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    if candidate.suffix.lower() not in STATIC_SUFFIXES:
        return None
    return candidate if candidate.is_file() else None


class App:
    """Request-scoped logic; injected into the HTTP handler for tests."""

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        project_root: Optional[Path] = None,
        web_root: Optional[Path] = None,
        translator: Optional[Translator] = None,
    ) -> None:
        self.project_root = Path(project_root or DEMO_PROJECT_DIR).resolve()
        self.web_root = Path(web_root or WEB_DIR).resolve()
        self.config = config or LLMConfig.from_env()
        self.catalog = Catalog(self.project_root)
        self.translator = translator or Translator(self.config)

    def health(self) -> Dict[str, Any]:
        configured = self.config.enabled
        model = self.config.public()
        return {
            "status": "ok",
            "version": __version__,
            "synthetic": True,
            "read_only": True,
            "project": {
                "name": self.catalog.project_name,
                "root": "demo_project",
                "string_table": "Assets/Localization/en.json",
                "code": "Assets/Scripts/**/*.cs",
            },
            "model": model,
            "mode": "live-capable" if configured else "retrieval-only",
            "message": (
                "已配置 API Key：可执行同模型对照翻译（真实调用，结果会明确标注 LIVE）。"
                if configured
                else "仅上下文检索演示、未调用模型（未配置 SOURCEAWARE_API_KEY）。"
            ),
            "target_locales": TARGET_LOCALES,
            "limits": {
                "max_body_bytes": MAX_BODY,
                "max_results": MAX_RESULTS,
                "timeout_seconds": self.config.timeout,
                "max_output_tokens": self.config.max_output_tokens,
                "max_context_chars": self.config.max_context_chars,
            },
        }

    def strings(self) -> Dict[str, Any]:
        return {
            "synthetic": True,
            "project": {"name": self.catalog.project_name, "root": "demo_project"},
            "target_locales": TARGET_LOCALES,
            "strings": [record.public() for record in self.catalog.strings()],
        }

    def evidence(self, key: str) -> Dict[str, Any]:
        return search(self.catalog, key)

    def compare(self, key: str, target_locale: str) -> Dict[str, Any]:
        record = self.catalog.get(key)
        payload = search(self.catalog, key)
        return self.translator.compare(record, payload["evidence"], target_locale)


class Handler(BaseHTTPRequestHandler):
    server_version = "SourceAwarePoC/" + __version__
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    # -- response helpers -------------------------------------------------
    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            pass

    def _json(self, status: int, data: Any, extra: Optional[Dict[str, str]] = None) -> None:
        headers = {"Cache-Control": "no-store"}
        headers.update(extra or {})
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Content-Length 无效")
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_BODY:
            raise ValueError("请求体超过 %d 字节上限" % MAX_BODY)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    # -- routing ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if path == "/api/health":
                self._json(200, self.app.health())
                return
            if path == "/api/strings":
                self._json(200, self.app.strings())
                return
            if path == "/api/evidence":
                key = (query.get("key") or [""])[0].strip()
                if not key:
                    self._error(400, "缺少 key 参数")
                    return
                if len(key) > MAX_KEY_CHARS:
                    self._error(400, "key 过长")
                    return
                try:
                    self._json(200, self.app.evidence(key))
                except UnknownStringKey as exc:
                    self._error(404, str(exc))
                except CatalogError as exc:
                    self._error(500, str(exc))
                return
            if path in ("/", "/index.html"):
                target = self.app.web_root / "index.html"
            else:
                target = _safe_join(self.app.web_root, path)
            if target is None or not target.is_file():
                self._error(404, "未找到资源")
                return
            body = target.read_bytes()
            content_type = MIME.get(target.suffix.lower(), "application/octet-stream")
            self._send(200, body, content_type, {"Cache-Control": "no-store"})
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            return
        except Exception as exc:  # pragma: no cover - defensive boundary
            self._error(500, "服务器内部错误: %s" % exc)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/compare":
            self._error(404, "未找到接口")
            return
        try:
            data = self._read_json()
        except ValueError as exc:
            self._error(400, str(exc))
            return
        key = data.get("key")
        locale = data.get("target_locale")
        if not isinstance(key, str) or not key.strip():
            self._error(400, "缺少 key")
            return
        if len(key) > MAX_KEY_CHARS:
            self._error(400, "key 过长")
            return
        if not isinstance(locale, str) or locale not in {item["code"] for item in TARGET_LOCALES}:
            self._error(400, "不支持的目标语言")
            return
        try:
            result = self.app.compare(key.strip(), locale)
        except UnknownStringKey as exc:
            self._error(404, str(exc))
            return
        except CatalogError as exc:
            self._error(500, str(exc))
            return
        except TranslationError as exc:
            self._json(
                502,
                {
                    "status": "error",
                    "live": True,
                    "stage": exc.stage or "translation",
                    "message": "模型调用失败，未生成译文：%s" % exc,
                },
            )
            return
        self._json(200, result)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], app: App) -> None:
        super().__init__(address, Handler)
        self.app = app


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="源码检索 → 证据 → 可选同模型 API 翻译对照 PoC"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8010, help="监听端口（默认 8010）")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args(argv)

    try:
        app = App()
    except CatalogError as exc:
        print("无法加载合成演示工程: %s" % exc, file=sys.stderr)
        return 2

    try:
        server = Server((args.host, args.port), app)
    except OSError as exc:
        print("无法监听 %s:%s: %s" % (args.host, args.port, exc), file=sys.stderr)
        return 2

    host, port = server.server_address[:2]
    url = "http://%s:%s/" % (host, port)
    print("源码感知翻译 PoC  %s" % __version__)
    print("  合成演示工程: %s（只读）" % app.project_root)
    if app.config.enabled:
        print(
            "  模型: %s @ %s（已配置 Key；只在点击“运行对照翻译”时真实调用）"
            % (app.config.model, app.config.base_host)
        )
    else:
        print("  模型: 未配置 SOURCEAWARE_API_KEY —— 仅上下文检索演示，不会调用模型")
    if not _is_loopback(args.host):
        print("  ⚠️ 当前监听 %s：API Key 仅保存在本机服务进程中，请勿暴露到公网" % args.host)
    print("  打开: %s" % url)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
