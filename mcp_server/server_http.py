"""
server_http.py — Streamable HTTP transport for the Meridian Port Authority MCP server.

Runs the same JSON-RPC dispatch logic as server.py (stdio transport) but
exposes it over HTTP instead of stdin/stdout, so any HTTP client can connect
without spawning a subprocess.

Usage:
    python -m mcp_server.server_http          # default: http://localhost:8000
    python -m mcp_server.server_http --port 9000

Endpoint:
    POST /mcp
    Content-Type: application/json
    Body: any JSON-RPC 2.0 message (or a JSON array of messages for batching)

The session is per-request (stateless HTTP), so each POST starts with a fresh
Session object. For multi-turn workflows that need authentication to persist,
send the badge_code on every request or use the stdio server instead.
"""

import json
import argparse
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from mcp_server import db, protocol
from mcp_server.auth import Session
from mcp_server.server import dispatch


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify the database is reachable before accepting traffic."""
    conn = db.get_connection()
    conn.close()
    print("  Database connection OK.")
    yield


app = FastAPI(
    title="Meridian Port Authority — MCP HTTP",
    description="Streamable HTTP transport for the Meridian Port Authority MCP server.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# /mcp endpoint
# ---------------------------------------------------------------------------

def _handle_single(conn, session: Session, msg: dict) -> dict:
    """Dispatch one JSON-RPC message and return a response dict."""
    if protocol.is_notification(msg):
        # notifications have no id and need no response
        return None

    msg_id = msg.get("id")
    try:
        result = dispatch(conn, session, msg)
        return protocol.make_response(msg_id, result)
    except protocol.JSONRPCError as exc:
        return protocol.make_error_response(msg_id, exc)
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        err = protocol.JSONRPCError(protocol.INTERNAL_ERROR, f"Internal error: {exc}")
        return protocol.make_error_response(msg_id, err)


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """
    Accept a single JSON-RPC 2.0 message or a JSON array of messages.
    Returns the corresponding response object or array.
    """
    try:
        body = await request.json()
    except Exception:
        err = protocol.JSONRPCError(protocol.PARSE_ERROR, "Invalid JSON in request body.")
        return JSONResponse(protocol.make_error_response(None, err), status_code=400)

    conn = db.get_connection()
    session = Session()

    try:
        # Batch request (array)
        if isinstance(body, list):
            responses = []
            for msg in body:
                resp = _handle_single(conn, session, msg)
                if resp is not None:
                    responses.append(resp)
            return JSONResponse(responses)

        # Single request
        if isinstance(body, dict):
            resp = _handle_single(conn, session, body)
            if resp is None:
                # notification — 204 No Content
                return JSONResponse(None, status_code=204)
            return JSONResponse(resp)

        err = protocol.JSONRPCError(protocol.PARSE_ERROR, "Body must be a JSON object or array.")
        return JSONResponse(protocol.make_error_response(None, err), status_code=400)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "server": "meridian-port-authority", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Meridian Port Authority — HTTP transport")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    args = parser.parse_args()

    print(f"Starting Meridian Port Authority MCP server (HTTP) on {args.host}:{args.port}")
    print(f"  Endpoint : POST http://{args.host}:{args.port}/mcp")
    print(f"  Health   : GET  http://{args.host}:{args.port}/health")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
