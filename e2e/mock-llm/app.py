from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def _tool_choice(request: dict) -> tuple[str, dict, str]:
    tools = request.get("tools", [])
    names = {
        tool.get("function", {}).get("name")
        for tool in tools
        if isinstance(tool, dict)
    }
    if "web__web_search" in names:
        return (
            "web__web_search",
            {"query": "E2E_TOOLS_WEB_MARKER", "limit": 3},
            "WEB_E2E_OK: agent-core called the web MCP tool through SearXNG.",
        )
    if "code__run_python" in names:
        return (
            "code__run_python",
            {"code": "print('E2E_TOOLS_CODE_MARKER')", "timeout_seconds": 5},
            "CODE_E2E_OK: agent-core called the code MCP tool and received sandbox output.",
        )
    return (
        "rag__search_knowledge",
        {"query": "RAG_E2E_MARKER", "limit": 3},
        "RAG_E2E_OK: retrieved the indexed marker through MCP.",
    )


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

        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        messages = request.get("messages", [])
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        tool_name, arguments, success_marker = _tool_choice(request)

        if request.get("stream"):
            if not has_tool_result:
                payload = {
                    "id": "e2e-tool-call",
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [{
                                "index": 0,
                                "id": "call-e2e-tool",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments),
                                },
                            }],
                        },
                        "finish_reason": "tool_calls",
                    }],
                }
            else:
                payload = {
                    "id": "e2e-final",
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": success_marker},
                        "finish_reason": "stop",
                    }],
                }
            data = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

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
                            "id": "call-e2e-tool",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }],
                    },
                }],
            })
            return

        tool_content = next(
            (
                message.get("content", "")
                for message in reversed(messages)
                if message.get("role") == "tool"
            ),
            "",
        )
        if "E2E_TOOLS_WEB_MARKER" in tool_content:
            content = success_marker
        elif "E2E_TOOLS_CODE_MARKER" in tool_content:
            content = success_marker
        elif "RAG_E2E_MARKER" in tool_content:
            content = success_marker
        else:
            content = "E2E_TOOL_FAIL: expected tool marker was not returned."

        self._send({
            "id": "e2e-final",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }],
        })

    def log_message(self, *_args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
