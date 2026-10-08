"""ローカル HTTP フィクスチャ。テストは実ネットワークに出ません。"""

import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest


class FixtureHandler(BaseHTTPRequestHandler):
    """パスに応じたステータスコードを返すだけのハンドラです。"""

    def do_GET(self) -> None:
        self.server.hits.append(self.path)
        path = urlsplit(self.path).path
        if path.startswith("/flaky/"):
            # 最初の n 回は応答せずに切断し、その後は 200 を返します。
            self.server.attempts[path] = self.server.attempts.get(path, 0) + 1
            if self.server.attempts[path] <= int(path.rsplit("/", 1)[1]):
                self.close_connection = True
                return None
            return self._respond(200)
        if path == "/sleep":
            time.sleep(0.5)
            return self._respond(200)
        if path == "/need-auth":
            authorized = self.headers.get("Authorization") == "Bearer secret"
            return self._respond(200 if authorized else 401)
        if path == "/ua":
            ua = self.headers.get("User-Agent", "")
            return self._respond(200 if ua == "status-code-checker" else 403)
        match = re.fullmatch(r"/status/(\d{3})", path)
        code = int(match.group(1)) if match else 200
        return self._respond(code)

    def _respond(self, code: int) -> None:
        self.send_response(code)
        if 300 <= code < 400:
            self.send_header("Location", "/redirected")
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.hits: list[str] = []
        self.attempts: dict[str, int] = {}

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def handle_error(self, request: object, client_address: object) -> None:
        pass  # クライアント側タイムアウト後の書き込み失敗は無視します。


@pytest.fixture
def server():
    srv = FixtureServer()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def closed_port() -> int:
    """誰も listen していないポート番号を返します。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
