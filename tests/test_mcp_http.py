"""MCP over real HTTP through the full app: lifespan, auth middleware and the
/mcp route together. ASGITransport skips lifespan, so this needs uvicorn."""

import asyncio
import socket

import httpx
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from emulator_hub.app import create_machine_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_mcp_over_http_with_bearer(engine):
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_machine_app(engine, api_token="s3cret"), port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        async with httpx.AsyncClient() as raw:
            assert (await raw.post(url, json={})).status_code == 401
        http = httpx.AsyncClient(headers={"Authorization": "Bearer s3cret"})
        async with Client(streamable_http_client(url, http_client=http)) as c:
            result = await c.call_tool("list_profiles", {})
            assert {p["name"] for p in result.structured_content["profiles"]} == {"phone", "tablet", "tv"}
    finally:
        server.should_exit = True
        await task
