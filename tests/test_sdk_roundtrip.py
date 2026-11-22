"""Drive the real Anthropic SDK against a local mock server (no network, no cost).

Checks that the agent loop serialises correctly when SDK response objects are
appended back into the conversation, and that tool definitions go out as sent.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from scopeeval.agents import ClaudeAgent
from scopeeval.attacks import template_attacks
from scopeeval.experiment import run_episode
from scopeeval.tasks import TASKS


def _message(content, stop_reason):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


SCRIPT = [
    _message([{"type": "tool_use", "id": "toolu_1", "name": "read_email", "input": {"email_id": "e1"}}], "tool_use"),
    _message(
        [
            {"type": "tool_use", "id": "toolu_2", "name": "lookup_customer", "input": {"customer_id": "C-1042"}},
        ],
        "tool_use",
    ),
    _message([{"type": "text", "text": "Northwind, Contoso and the 2024 invoices."}], "end_turn"),
]


def test_real_sdk_roundtrip():
    requests = []
    script = list(SCRIPT)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(json.loads(body))
            payload = json.dumps(script.pop(0)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = anthropic.Anthropic(api_key="test", base_url=f"http://127.0.0.1:{server.server_port}", max_retries=0)
        attack = next(a for a in template_attacks() if a.goal == "exfiltrate")
        row = run_episode(ClaudeAgent(client), TASKS["action_items"], attack, "scoped_write")
    finally:
        server.shutdown()

    assert row["outcome"] == "completed", row.get("detail")
    assert row["task_success"] is True
    assert row["pii_accessed"] is True and row["harms"] == []
    assert len(requests) == 3
    first, last = requests[0], requests[-1]
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"] == {"effort": "medium"}
    assert all(t["strict"] is True for t in first["tools"])
    assert "delete_file" not in {t["name"] for t in first["tools"]}
    # The assistant tool_use turn was echoed back and followed by its tool_result.
    assert last["messages"][1]["content"][0]["type"] == "tool_use"
    assert last["messages"][2]["content"][0]["tool_use_id"] == "toolu_1"
    assert "Northwind" in last["messages"][2]["content"][0]["content"]
