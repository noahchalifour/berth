import json

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from emulator_hub.app import create_ui_app
from tests.fakes import FakeScreen


@pytest.fixture
def screens():
    return []


@pytest.fixture
def app(engine, screens):
    def factory(pod_ip):
        s = FakeScreen(pod_ip)
        screens.append(s)
        return s

    return create_ui_app(engine, screen_factory=factory)


async def test_live_streams_frames_and_forwards_input(engine, app, screens):
    grant = await engine.acquire("phone", "a", 30, 1)
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/api/leases/{grant.lease.id}/live", headers={"X-authentik-username": "noah"}) as ws,
    ):
        assert [ws.receive_bytes() for _ in range(3)] == [b"jpeg-0", b"jpeg-1", b"jpeg-2"]
        ws.send_text(json.dumps({"t": "touch", "x": 0.5, "y": 0.25, "down": True}))
        ws.send_text(json.dumps({"t": "key", "key": "GoHome"}))
        ws.send_text(json.dumps({"t": "key", "key": "rm -rf"}))  # not in KEYS: dropped
        ws.send_text(json.dumps({"t": "touch", "x": 7, "y": 0.1, "down": True}))  # out of range: dropped
        ws.send_text(json.dumps({"t": "text", "text": "hello"}))
        ws.close()
    assert screens[0].pod_ip == "10.233.0.9"
    assert screens[0].inputs == [("touch", 0.5, 0.25, True), ("key", "GoHome"), ("text", "hello")]
    assert screens[0].closed


async def test_live_refuses_unknown_lease_and_missing_auth(engine, app):
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as err,
            client.websocket_connect("/api/leases/nope/live", headers={"X-authentik-username": "noah"}) as ws,
        ):
            ws.receive_bytes()
        assert err.value.code == 4404


async def test_live_requires_auth(engine, app):
    grant = await engine.acquire("phone", "a", 30, 1)
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as err,
            client.websocket_connect(f"/api/leases/{grant.lease.id}/live") as ws,
        ):
            ws.receive_bytes()
        assert err.value.code == 4401


async def test_snapshot_is_a_jpeg_for_a_live_lease(engine, app):
    grant = await engine.acquire("phone", "a", 30, 1)
    with TestClient(app) as client:
        ok = client.get(f"/api/leases/{grant.lease.id}/snapshot", headers={"X-authentik-username": "noah"})
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg" and ok.content == b"thumb"
        assert client.get("/api/leases/nope/snapshot", headers={"X-authentik-username": "noah"}).status_code == 404
