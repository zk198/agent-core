import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/systemone":
            self._send(404, {"detail": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        assert isinstance(request.get("questions"), dict)
        self._send(
            200,
            {
                "model": "e2e/mock-laya",
                "routing": {"model": "e2e/mock-laya"},
                "answers": {
                    "allowed": {"noul": True},
                    "request_type": {"noul": "knowledge"},
                },
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
