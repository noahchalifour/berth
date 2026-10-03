from tests.e2e.hub import acquire_leased


async def test_harness_smoke(mcp, env, profile, holder):
    grant = await acquire_leased(mcp, env, profile, holder)
    assert grant["state"] == "leased"
    await mcp.call("release", lease_id=grant["lease_id"])
