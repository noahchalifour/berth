import asyncio

import pytest

from emulator_hub.models import BootFailed, Busy, Invalid, LeaseNotActive, NotFound
from emulator_hub.pods import pod_name


async def test_acquire_boots_a_pod_and_returns_endpoints(engine, pods):
    grant = await engine.acquire("phone", "test-agent", ttl_minutes=30, wait_seconds=1)
    assert grant.adb == "172.24.3.155:5555"
    assert grant.in_cluster == "slot-0.emulator-hub.svc.cluster.local:5555"
    assert pod_name(0, grant.lease.id) in pods.pods
    assert grant.lease.state == "leased"
    assert engine.store.list_slots()[0].state == "leased"


async def test_three_slots_then_busy(engine):
    for _ in range(3):
        await engine.acquire("phone", "a", 30, 1)
    with pytest.raises(Busy) as err:
        await engine.acquire("phone", "a", 30, wait_seconds=0.05)
    assert err.value.position == 1
    assert engine.queue_depth() == 0


async def test_waiter_gets_the_released_slot_in_fifo_order(engine):
    grants = [await engine.acquire("phone", "a", 30, 1) for _ in range(3)]
    first = asyncio.create_task(engine.acquire("tablet", "first", 30, 5))
    await asyncio.sleep(0)
    second = asyncio.create_task(engine.acquire("tv", "second", 30, 5))
    await asyncio.sleep(0)
    assert engine.queue_depth() == 2
    await engine.release(grants[1].lease.id)
    got = await first
    assert got.lease.slot == 1 and got.lease.holder == "first"
    assert not second.done()
    await engine.release(grants[0].lease.id)
    assert (await second).lease.slot == 0


async def test_boot_timeout_frees_the_slot(engine, probe, clock, pods):
    probe.after = 10**9

    async def tick_clock():
        while True:
            clock.advance(10)
            await asyncio.sleep(0)

    ticker = asyncio.create_task(tick_clock())
    try:
        with pytest.raises(BootFailed):
            await engine.acquire("phone", "a", 30, 1)
    finally:
        ticker.cancel()
    assert pods.pods == {}
    assert engine.store.free_slots() == [0, 1, 2]
    assert engine.store.recent_leases()[0].end_reason == "boot_failed"


async def test_pod_exit_during_boot_is_boot_failed(engine, pods, probe):
    probe.after = 3
    original_create = pods.create

    async def create_then_fail(manifest):
        await original_create(manifest)
        pods.failed.add(manifest["metadata"]["name"])

    pods.create = create_then_fail
    with pytest.raises(BootFailed, match="kvm"):
        await engine.acquire("phone", "a", 30, 1)
    assert engine.store.free_slots() == [0, 1, 2]


async def test_create_error_is_boot_failed(engine, pods):
    pods.create_error = RuntimeError("quota exceeded")
    with pytest.raises(BootFailed, match="quota exceeded"):
        await engine.acquire("phone", "a", 30, 1)
    assert engine.store.free_slots() == [0, 1, 2]


async def test_heartbeat_extends_but_never_past_max_age(engine, clock):
    grant = await engine.acquire("phone", "a", ttl_minutes=30, wait_seconds=1)
    clock.advance(20 * 60)
    assert engine.heartbeat(grant.lease.id).lease.expires_at == clock() + 30 * 60
    clock.advance(4 * 3600 - 20 * 60 - 60)
    capped = engine.heartbeat(grant.lease.id).lease.expires_at
    assert capped == grant.lease.created_at + 4 * 3600


async def test_reap_expires_ages_out_and_detects_lost(engine, clock, pods):
    expired = await engine.acquire("phone", "a", ttl_minutes=1, wait_seconds=1)
    lost = await engine.acquire("phone", "b", ttl_minutes=60, wait_seconds=1)
    kept = await engine.acquire("phone", "c", ttl_minutes=60, wait_seconds=1)
    pods.failed.add(pod_name(lost.lease.slot, lost.lease.id))
    clock.advance(61)
    ended = dict(await engine.reap())
    assert ended == {expired.lease.id: "expired", lost.lease.id: "lost"}
    assert engine.store.get_lease(kept.lease.id).state == "leased"
    clock.advance(4 * 3600)
    assert dict(await engine.reap()) == {kept.lease.id: "max_age"}
    assert pods.pods == {}


async def test_release_twice_and_heartbeat_after_release(engine):
    grant = await engine.acquire("phone", "a", 30, 1)
    await engine.release(grant.lease.id)
    with pytest.raises(LeaseNotActive):
        await engine.release(grant.lease.id)
    with pytest.raises(LeaseNotActive, match="acquire a new one"):
        engine.heartbeat(grant.lease.id)


async def test_invalid_requests(engine):
    with pytest.raises(NotFound):
        await engine.acquire("watch", "a", 30, 1)
    with pytest.raises(Invalid):
        await engine.acquire("phone", "a", 0, 1)
    with pytest.raises(Invalid):
        await engine.acquire("phone", "  ", 30, 1)


async def test_cancelled_acquire_releases_its_slot(engine, probe):
    probe.after = 10**9
    task = asyncio.create_task(engine.acquire("phone", "a", 30, 1))
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.store.free_slots() == [0, 1, 2]
    assert engine.store.recent_leases()[0].end_reason == "cancelled"


async def test_reconcile_cleans_up_after_a_crash(engine, store, pods, probe, config, clock):
    from emulator_hub.leases import LeaseEngine

    survivor = await engine.acquire("phone", "a", 60, 1)
    vanished = await engine.acquire("phone", "b", 60, 1)
    del pods.pods[pod_name(vanished.lease.slot, vanished.lease.id)]
    pods.pods["emu-slot-2-deadbeef"] = {"metadata": {"labels": {"emulator-hub/lease": "deadbeef" * 4}}}

    restarted = LeaseEngine(store, pods, probe, config, clock=clock)
    await restarted.reconcile()

    assert store.get_lease(survivor.lease.id).state == "leased"
    assert store.get_lease(vanished.lease.id).end_reason == "lost"
    assert set(pods.pods) == {pod_name(0, survivor.lease.id)}
    assert [s.state for s in store.list_slots()] == ["leased", "free", "free"]
