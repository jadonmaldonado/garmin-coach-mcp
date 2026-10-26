"""Minimal, stateless MCP server over Streamable HTTP (JSON responses, no SSE).

Implements the subset a tools-only server needs: initialize, ping, tools/list,
tools/call, notifications. Each POST is self-contained, which fits Lambda's
request/response model with no session store.
"""

import json
import logging
import os
import time

import mcp_tools

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "garmin-coach", "title": "Garmin Coach", "version": "1.0.0"}


def _instructions() -> str:
    goals = os.environ.get("ATHLETE_GOALS", "").strip()
    return (
        "Garmin Coach gives read access to the athlete's Garmin data (synced to a database several "
        "times a day): sleep, HRV, readiness, workouts, and computed training load. "
        "Load metrics use Garmin's activity load, not TrainingPeaks TSS; reason from trends. "
        "If recent data looks missing, check get_sync_status and call refresh_data. "
        + (f"Athlete goals: {goals}. " if goals else "")
        + "This is training data, not medical advice."
    )


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _call_tool(msg_id, params: dict) -> dict:
    name = params.get("name")
    tool = mcp_tools.TOOLS.get(name)
    if not tool:
        return _error(msg_id, -32602, f"Unknown tool: {name}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _error(msg_id, -32602, "arguments must be an object")
    started = time.time()
    try:
        data = tool["fn"](**args)
        is_error = False
        text = json.dumps(data, default=str, separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # bad arguments: tell the model so it can retry
        is_error, text = True, f"Invalid arguments: {exc}"
    except Exception as exc:  # noqa: BLE001 - surface a clean message, log the stack
        log.exception("Tool %s failed", name)
        is_error, text = True, f"{name} failed: {type(exc).__name__}: {str(exc)[:300]}"
    log.info(json.dumps({"event": "tool_call", "tool": name, "error": is_error,
                         "ms": int((time.time() - started) * 1000)}))
    return _result(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


def handle_message(msg) -> dict | None:
    """Returns a JSON-RPC response, or None for notifications/client responses."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid Request")
    msg_id = msg.get("id")
    method = msg.get("method")
    if method is None or "id" not in msg:  # notification or a response to us: nothing to send back
        return None
    params = msg.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": _instructions(),
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        tools = [{"name": n, "description": t["description"], "inputSchema": t["inputSchema"],
                  "annotations": t["annotations"]} for n, t in mcp_tools.TOOLS.items()]
        return _result(msg_id, {"tools": tools})
    if method == "tools/call":
        return _call_tool(msg_id, params)
    return _error(msg_id, -32601, f"Method not found: {method}")


def handle_body(body: str) -> tuple[int, dict | list | None]:
    """HTTP status + JSON payload for one POST body (single message or batch)."""
    try:
        payload = json.loads(body or "")
    except json.JSONDecodeError:
        return 400, _error(None, -32700, "Parse error")
    if isinstance(payload, list):
        if not payload:
            return 400, _error(None, -32600, "Empty batch")
        responses = [r for r in (handle_message(m) for m in payload) if r is not None]
        return (200, responses) if responses else (202, None)
    response = handle_message(payload)
    return (200, response) if response is not None else (202, None)
