from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in {"/health", "/v1/models"}:
            self._send({"status": "ok", "data": []})
            return
        self._send({"error": {"message": "not found"}}, 404)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send({"error": {"message": "not found"}}, 404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        messages = request.get("messages", [])
        has_tool_result = any(message.get("role") == "tool" for message in messages)

        if not has_tool_result:
            self._send({
                "id": "e2e-tool-call",
                "object": "chat.completion",
                "choices": [{
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call-rag-search",
                            "type": "function",
                            "function": {
                                "name": "rag__search_knowledge",
                                "arguments": json.dumps({
                                    "query": "RAG_E2E_MARKER",
                                    "limit": 3,
                                }),
                            },
                        }],
                    },
                }],
            })
            return

        tool_content = next(
            (message.get("content", "") for message in reversed(messages)
             if message.get("role") == "tool"),
            "",
        )
        if "RAG_E2E_MARKER" in tool_content:
            content = "RAG_E2E_OK: retrieved the indexed marker through MCP."
        else:
            content = "RAG_E2E_FAIL: expected marker was not returned by RAG search."

        self._send({
            "id": "e2e-final",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }],
        })

    def log_message(self, *_args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
