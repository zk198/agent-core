from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def choose_tool(request: dict) -> tuple[str, dict, str]:
    names = {
        item.get("function", {}).get("name")
        for item in request.get("tools", [])
        if isinstance(item, dict)
    }
    invalid_args = any(
        "RAG_E2E_INVALID_ARGS" in str(message.get("content", ""))
        for message in request.get("messages", [])
        if isinstance(message, dict) and message.get("role") == "user"
    )
    if "web__web_search" in names:
        return (
            "web__web_search",
            {"query": "E2E_TOOLS_WEB_MARKER", "limit": 3},
            "WEB_E2E_OK: web MCP tool through SearXNG.",
        )
    if "code__run_python" in names:
        return (
            "code__run_python",
            {"code": "print('E2E_TOOLS_CODE_MARKER')", "timeout_seconds": 5},
            "CODE_E2E_OK: code MCP tool and sandbox worker.",
        )
    return (
        "rag__search_knowledge",
        {
            "query": "RAG_E2E_MARKER",
            "limit": "invalid" if invalid_args else 3,
        },
        "RAG_E2E_OK: indexed marker through MCP.",
    )


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in {"/health", "/v1/models"}:
            self.send_json({"status": "ok", "data": []})
        else:
            self.send_json({"error": {"message": "not found"}}, 404)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_json({"error": {"message": "not found"}}, 404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        messages = request.get("messages", [])
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        tool_name, arguments, success_marker = choose_tool(request)

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
                marker = (
                    "RAG_E2E_STREAM_OK: indexed marker through MCP."
                    if tool_name == "rag__search_knowledge"
                    else success_marker
                )
                payload = {
                    "id": "e2e-final",
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": marker},
                        "finish_reason": "stop",
                    }],
                }
            raw = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if not has_tool_result:
            self.send_json({
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
        if any(marker in tool_content for marker in (
            "E2E_TOOLS_WEB_MARKER",
            "E2E_TOOLS_CODE_MARKER",
            "RAG_E2E_MARKER",
        )):
            content = success_marker
        else:
            content = "E2E_TOOL_FAIL: expected tool marker was not returned."

        self.send_json({
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
