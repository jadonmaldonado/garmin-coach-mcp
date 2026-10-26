import json

import mcp_handler
import mcp_protocol
import mcp_tools


def _post(body, token="secret"):
    return {
        "pathParameters": {"token": token},
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def _setup(monkeypatch):
    monkeypatch.setattr(mcp_handler, "_TOKEN", "secret")


def test_wrong_token_is_404(monkeypatch):
    _setup(monkeypatch)
    resp = mcp_handler.lambda_handler(_post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token="nope"), None)
    assert resp["statusCode"] == 404


def test_initialize_negotiates_version(monkeypatch):
    _setup(monkeypatch)
    resp = mcp_handler.lambda_handler(_post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}},
    }), None)
    result = json.loads(resp["body"])["result"]
    assert resp["statusCode"] == 200
    assert result["protocolVersion"] == "2025-06-18"
    assert "tools" in result["capabilities"]


def test_unknown_version_gets_latest_supported():
    out = mcp_protocol.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                       "params": {"protocolVersion": "1999-01-01"}})
    assert out["result"]["protocolVersion"] == mcp_protocol.SUPPORTED_VERSIONS[0]


def test_notification_returns_202(monkeypatch):
    _setup(monkeypatch)
    resp = mcp_handler.lambda_handler(_post({"jsonrpc": "2.0", "method": "notifications/initialized"}), None)
    assert resp["statusCode"] == 202 and resp["body"] == ""


def test_tools_list_matches_registry():
    out = mcp_protocol.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in out["result"]["tools"]}
    assert names == set(mcp_tools.TOOLS)
    for t in out["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object"


def test_tool_call_success_and_bad_args(monkeypatch):
    monkeypatch.setitem(mcp_tools.TOOLS["get_sync_status"], "fn", lambda: {"status": "ok"})
    ok = mcp_protocol.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                      "params": {"name": "get_sync_status", "arguments": {}}})
    assert ok["result"]["isError"] is False
    assert json.loads(ok["result"]["content"][0]["text"]) == {"status": "ok"}
    bad = mcp_protocol.handle_message({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                       "params": {"name": "get_sync_status", "arguments": {"bogus": 1}}})
    assert bad["result"]["isError"] is True


def test_unknown_method_and_parse_error():
    out = mcp_protocol.handle_message({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert out["error"]["code"] == -32601
    status, payload = mcp_protocol.handle_body("{not json")
    assert status == 400 and payload["error"]["code"] == -32700


def test_get_is_405(monkeypatch):
    _setup(monkeypatch)
    event = {"pathParameters": {"token": "secret"}, "requestContext": {"http": {"method": "GET"}}}
    assert mcp_handler.lambda_handler(event, None)["statusCode"] == 405


def test_training_load_with_fake_store(monkeypatch):
    acts = [{"activity_id": str(i), "date": f"2026-10-{i:02d}", "start_local": f"2026-10-{i:02d}T07:00:00",
             "sport": "run" if i % 2 else "bike", "duration_min": 60, "garmin_load": 80} for i in range(1, 18)]
    monkeypatch.setattr(mcp_tools.store, "activity_items", lambda s, e: [dict(a) for a in acts])
    monkeypatch.setattr(mcp_tools.store, "day_items", lambda s, e: [{"date": "2026-10-17", "resting_hr": 48}])
    out = mcp_tools.get_training_load(end_date="2026-10-17", days=14)
    assert out["current"]["fitness_ctl"] > 0
    assert out["current"]["fatigue_atl"] > out["current"]["fitness_ctl"]
    assert "run" in out["by_sport_last_7_days"]
    assert out["data_coverage"]["note"]  # only 17 days of history
