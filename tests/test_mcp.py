from mcp import Client

from emulator_hub.mcp_server import build_mcp


def connect(engine):
    return Client(build_mcp(engine), raise_exceptions=False)


async def test_tools_are_exactly_the_lease_api(engine):
    async with connect(engine) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools == {"list_profiles", "acquire", "heartbeat", "release", "status"}


async def test_acquire_heartbeat_release_round_trip(engine):
    async with connect(engine) as client:
        grant = (await client.call_tool("acquire", {"profile": "tv", "holder": "pytest"})).structured_content
        assert grant["adb"] == "172.24.3.155:5555"
        hb = await client.call_tool("heartbeat", {"lease_id": grant["lease_id"]})
        assert not hb.is_error
        rel = (await client.call_tool("release", {"lease_id": grant["lease_id"]})).structured_content
        assert rel == {"lease_id": grant["lease_id"], "state": "ended", "end_reason": "released"}
        status = (await client.call_tool("status", {})).structured_content
        assert [s["state"] for s in status["slots"]] == ["free", "free", "free"]


async def test_hub_errors_reach_the_model_as_readable_text(engine):
    async with connect(engine) as client:
        result = await client.call_tool("acquire", {"profile": "watch", "holder": "pytest"})
        assert result.is_error
        assert "no profile named 'watch'" in result.content[0].text


async def test_busy_reports_queue_position(engine):
    async with connect(engine) as client:
        for _ in range(3):
            await client.call_tool("acquire", {"profile": "phone", "holder": "p"})
        result = await client.call_tool("acquire", {"profile": "phone", "holder": "p", "wait_seconds": 0})
        assert result.is_error and "number 1 in the queue" in result.content[0].text


async def test_acquire_answers_before_a_slow_boot_finishes(engine):
    engine.probe.after = 10**9
    async with connect(engine) as client:
        grant = (
            await client.call_tool("acquire", {"profile": "phone", "holder": "p", "boot_wait_seconds": 0})
        ).structured_content
        assert grant["state"] == "booting" and grant["lease_id"]
        hb = (await client.call_tool("heartbeat", {"lease_id": grant["lease_id"]})).structured_content
        assert hb["state"] == "booting"
