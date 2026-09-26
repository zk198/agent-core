from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

MARKER = "RAG_E2E_MARKER"


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send({"status": "ok"})
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path != "/search":
            self._send({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if request.get("query") != MARKER:
            self._send([])
            return
        self._send([{
            "chunk_id": "e2e-chunk",
            "parent_kind": "document",
            "score": 1.0,
            "text": MARKER,
            "source_name": "e2e",
            "parent": {"id": "e2e-document"},
        }])

    def log_message(self, *_args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8100), Handler).serve_forever()
