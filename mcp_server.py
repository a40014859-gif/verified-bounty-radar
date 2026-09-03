#!/usr/bin/env python3
"""Minimal dependency-free MCP stdio server for Verified Bounty Radar."""
import contextlib
import io
import json
import sys
import urllib.request

import verify

SERVER_INFO = {"name": "verified-bounty-radar", "version": "0.3.0"}

TOOLS = [
    {
        "name": "verify_github_bounty",
        "description": "Verify canonical state, assignees, reward signals, claim signals, and competing PRs for a public GitHub issue before implementation work begins.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Public GitHub issue URL, e.g. https://github.com/OWNER/REPO/issues/123",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_radar_bounties",
        "description": "Fetch the current public Verified Bounty Radar feed. Optionally filter by recommendation and minimum verified reward.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recommendation": {"type": "string"},
                "min_reward": {"type": "number", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "additionalProperties": False,
        },
    },
]


def text_result(payload, is_error=False):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
        "isError": is_error,
    }


def call_verify(url):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            verify.main(url)
        raw = buf.getvalue().strip()
        payload = json.loads(raw) if raw else {}
        return text_result(payload)
    except BaseException as exc:
        return text_result({"error": str(exc)}, True)


def call_feed(args):
    try:
        req = urllib.request.Request(
            "https://a40014859-gif.github.io/verified-bounty-radar/feed.json",
            headers={"User-Agent": "verified-bounty-radar-mcp/0.3"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            feed = json.load(resp)
        recommendation = args.get("recommendation")
        min_reward = float(args.get("min_reward", 0) or 0)
        limit = int(args.get("limit", 20) or 20)
        rows = []
        for item in feed.get("records", []):
            if recommendation and item.get("recommendation") != recommendation:
                continue
            amount = ((item.get("reward") or {}).get("amount") or 0)
            if amount < min_reward:
                continue
            rows.append(item)
            if len(rows) >= limit:
                break
        return text_result(
            {
                "generated_at": feed.get("generated_at"),
                "record_count": len(rows),
                "records": rows,
            }
        )
    except Exception as exc:
        return text_result({"error": str(exc)}, True)


def handle(request):
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion") or "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "verify_github_bounty":
            return call_verify(args.get("url", ""))
        if name == "list_radar_bounties":
            return call_feed(args)
        return text_result({"error": f"unknown tool: {name}"}, True)
    return None


def send(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            continue
        if request.get("method", "").startswith("notifications/"):
            continue
        result = handle(request)
        if "id" in request:
            if result is None:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                )
            else:
                send({"jsonrpc": "2.0", "id": request["id"], "result": result})


if __name__ == "__main__":
    main()
