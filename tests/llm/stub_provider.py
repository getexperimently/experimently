"""A stand-in for the Anthropic and OpenAI HTTP APIs, for the Docker Smoke job.

The API image's LLM proxy (``POST /api/v1/llm-experiments/{id}/complete``)
calls the provider SDKs, and the SDKs honour ``ANTHROPIC_BASE_URL`` and
``OPENAI_BASE_URL``. Pointed here, one ``/complete`` per provider goes through
the real SDK code in the real image -- import, client construction, request
serialisation, response parsing -- and never leaves the compose network. No
key, no bill, no flake from a third party.

It answers exactly two routes, with the minimum each SDK parses:

  POST /v1/messages          Anthropic Messages API
  POST /v1/chat/completions  OpenAI Chat Completions (base URL ends in /v1)

and ``GET /requests``, the paths it has served so far, so the smoke step can
show the call reached it rather than inferring that from a 200. Anything else
is a 404, so a changed request path fails the step instead of passing it.

Standard library only; it runs under the API image's own python.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANTHROPIC_TEXT = "stub-anthropic-ok"
OPENAI_TEXT = "stub-openai-ok"

SERVED: list[str] = []


def _anthropic(body: dict) -> dict:
    return {
        "id": "msg_stub",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "stub"),
        "content": [{"type": "text", "text": ANTHROPIC_TEXT}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }


def _openai(body: dict) -> dict:
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", "stub"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": OPENAI_TEXT},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


ROUTES = {
    "/v1/messages": ("x-api-key", _anthropic),
    "/v1/chat/completions": ("authorization", _openai),
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
        if self.path == "/requests":
            self._send(200, SERVED)
        elif self.path == "/healthz":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": f"no route {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        route = ROUTES.get(path)
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if route is None:
            self._send(404, {"error": f"no route {path}"})
            return
        auth_header, respond = route
        if not self.headers.get(auth_header):
            # The SDK sent no credential: the key did not reach the client.
            self._send(401, {"error": f"no {auth_header} header"})
            return
        SERVED.append(path)
        self._send(200, respond(body))

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("stub-provider: " + (fmt % args) + "\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
