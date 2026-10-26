"""API Gateway (HTTP API, payload v2) -> MCP.

Auth: the connector URL contains a long random path token (/mcp/{token}) stored in
SSM. Wrong token -> 404 so the endpoint doesn't reveal it exists. The token never
reaches logs: API Gateway access logs record the route template, not the raw path,
and this function never logs the path.
"""

import base64
import hmac
import json
import logging
import os

import mcp_protocol

log = logging.getLogger()
log.setLevel(logging.INFO)

_TOKEN: str | None = None
JSON_HEADERS = {"Content-Type": "application/json", "Cache-Control": "no-store"}


def expected_token() -> str:
    global _TOKEN
    if _TOKEN is None:  # cached per warm container
        import boto3

        _TOKEN = boto3.client("ssm").get_parameter(
            Name=os.environ["MCP_TOKEN_PARAM"], WithDecryption=True
        )["Parameter"]["Value"]
    return _TOKEN


def _resp(status: int, payload=None, headers=None) -> dict:
    out = {"statusCode": status, "headers": {**JSON_HEADERS, **(headers or {})}}
    out["body"] = json.dumps(payload, default=str) if payload is not None else ""
    return out


def lambda_handler(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    if not token or not hmac.compare_digest(token.encode(), expected_token().encode()):
        return _resp(404, {"message": "Not Found"})

    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "POST":
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        status, payload = mcp_protocol.handle_body(body)
        return _resp(status, payload)
    if method == "OPTIONS":
        return _resp(204, headers={"Allow": "POST, OPTIONS"})
    # GET (server-initiated SSE stream) and DELETE (session end) aren't used by a stateless server.
    return _resp(405, {"message": "Method Not Allowed"}, {"Allow": "POST, OPTIONS"})
