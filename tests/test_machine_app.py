import httpx

from emulator_hub.app import create_machine_app

UI = {"X-authentik-username": "noah"}
BEARER = {"Authorization": "Bearer s3cret"}


def machine_client(engine):
    app = create_machine_app(engine, api_token="s3cret")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub")


async def test_machine_port_requires_bearer_only(engine):
    async with machine_client(engine) as c:
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.get("/metrics")).status_code == 200
        assert (await c.post("/mcp", json={}, headers=UI)).status_code == 401  # spoofed header means nothing here
        assert (await c.get("/api/status", headers=BEARER)).status_code == 404  # no REST API on this port


async def test_metrics_report_slots_and_boot_durations(engine):
    await engine.acquire("phone", "a", 30, 1)
    async with machine_client(engine) as c:
        body = (await c.get("/metrics")).text
    assert "emulator_hub_slots_in_use 1.0" in body
    assert "emulator_hub_boot_seconds_count" in body
