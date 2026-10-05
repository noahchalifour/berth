"""CancelOnDisconnect, over a real socket (ASGITransport never disconnects)."""

import asyncio
import socket

import httpx
import pytest
import uvicorn

from emulator_hub.disconnect import CancelOnDisconnect


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def serve():
    servers = []

    async def start(app):
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning", lifespan="off"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        servers.append((server, task))
        return f"http://127.0.0.1:{port}"

    yield start
    for server, task in servers:
        server.should_exit = True
        await task


def slow_app(events, respond_first=False):
    async def app(scope, receive, send):
        body = (await receive())["body"]
        events.append(("body", body))
        try:
            if respond_first:
                await send({"type": "http.response.start", "status": 200, "headers": []})
            await asyncio.sleep(3)
            events.append("finished")
            if not respond_first:
                await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    return app


async def leave_early(url, path="/slow"):
    with pytest.raises(httpx.ReadTimeout):
        async with httpx.AsyncClient(timeout=0.5) as c:
            await c.post(url + path, content=b"payload")
    await asyncio.sleep(0.5)


async def test_handler_is_cancelled_when_the_client_leaves(serve):
    events = []
    url = await serve(CancelOnDisconnect(slow_app(events), paths=("/slow",)))
    await leave_early(url)
    assert events == [("body", b"payload"), "cancelled"]


async def test_a_started_response_is_never_cancelled(serve):
    events = []
    url = await serve(CancelOnDisconnect(slow_app(events, respond_first=True), paths=("/slow",)))
    async with httpx.AsyncClient(timeout=10) as c:
        async with c.stream("POST", url + "/slow", content=b"payload") as r:
            assert r.status_code == 200  # headers arrived; now leave
    await asyncio.sleep(3)
    assert "cancelled" not in events and "finished" in events


async def test_other_paths_are_untouched(serve):
    events = []
    url = await serve(CancelOnDisconnect(slow_app(events), paths=("/elsewhere",)))
    await leave_early(url)
    await asyncio.sleep(3)
    assert "cancelled" not in events and "finished" in events


async def test_a_completed_request_is_unaffected(serve):
    events = []
    url = await serve(CancelOnDisconnect(slow_app(events), paths=("/slow",)))
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(url + "/slow", content=b"payload")
    assert r.text == "ok" and events[-1] == "finished"


async def test_mcp_caller_that_leaves_the_queue_is_forgotten(engine, serve):
    """End to end through the machine app: a queued MCP acquire whose client
    disconnects leaves the queue, and the next release frees the slot."""
    from emulator_hub.app import create_machine_app

    for i in range(3):
        await engine.acquire("phone", f"h{i}", 30, 1)
    app = create_machine_app(engine, api_token="t")
    # lifespan is off in `serve`; the MCP session manager needs its task group.
    async with app.router.lifespan_context(app):
        url = await serve(app)
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "acquire", "arguments": {"profile": "phone", "holder": "gone", "wait_seconds": 60}},
        }
        headers = {"Authorization": "Bearer t", "Accept": "application/json, text/event-stream"}
        with pytest.raises(httpx.ReadTimeout):
            async with httpx.AsyncClient(timeout=1) as c:
                await c.post(url + "/mcp", json=call, headers=headers)
        for _ in range(50):
            if engine.queue_depth() == 0:
                break
            await asyncio.sleep(0.1)
        assert engine.queue_depth() == 0
        held = engine.store.active_leases()[0]
        await engine.release(held.id)
        assert held.slot in engine.store.free_slots()
