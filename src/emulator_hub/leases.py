"""The lease engine: slot claiming, the FIFO queue, boot waiting, expiry and
startup reconciliation.

Concurrency model: one process, one asyncio loop, synchronous SQLite calls.
Every decision that reads-then-writes slot state happens between two awaits,
so no other coroutine can interleave with it. That is the lock; there is no
other.
"""

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from emulator_hub.models import (
    LEASE_BOOTING,
    LEASE_LEASED,
    SLOT_BOOTING,
    SLOT_FREE,
    SLOT_LEASED,
    BootFailed,
    Busy,
    Invalid,
    Lease,
    LeaseNotActive,
)
from emulator_hub.pods import PodBackend, build_pod, pod_name
from emulator_hub.store import Store


class BootProbe(Protocol):
    async def booted(self, pod_ip: str) -> bool: ...


@dataclass(frozen=True)
class EngineConfig:
    namespace: str
    emulator_image: str
    slot_ips: tuple[str, ...]
    boot_timeout_s: float = 180
    boot_poll_s: float = 3
    max_age_s: float = 4 * 3600
    min_ttl_minutes: int = 1
    max_ttl_minutes: int = 120


@dataclass(frozen=True)
class Grant:
    lease: Lease
    adb: str
    in_cluster: str

    def to_dict(self) -> dict:
        return {
            "lease_id": self.lease.id,
            "state": self.lease.state,
            "profile": self.lease.profile,
            "slot": self.lease.slot,
            "adb": self.adb,
            "in_cluster": self.in_cluster,
            "expires_at": self.lease.expires_at,
        }


class LeaseEngine:
    def __init__(
        self,
        store: Store,
        pods: PodBackend,
        probe: BootProbe,
        config: EngineConfig,
        clock: Callable[[], float] = time.time,
    ):
        self.store = store
        self.pods = pods
        self.probe = probe
        # lease id -> emulator Pod IP, for the live view. Rebuilt by reconcile().
        self.devices: dict[str, str] = {}
        self.config = config
        self.clock = clock
        self._waiters: deque[asyncio.Future[int]] = deque()
        # lease id -> the task booting its emulator, while it is booting.
        self._boots: dict[str, asyncio.Task[None]] = {}
        # Boot durations since the last /metrics scrape; drained into the histogram there.
        self.boot_seconds: list[float] = []

    # ---- queries
    def queue_depth(self) -> int:
        return sum(1 for f in self._waiters if not f.done())

    def endpoints(self, slot: int) -> tuple[str, str]:
        return (
            f"{self.config.slot_ips[slot]}:5555",
            f"slot-{slot}.{self.config.namespace}.svc.cluster.local:5555",
        )

    def grant(self, lease: Lease) -> Grant:
        adb, in_cluster = self.endpoints(lease.slot)
        return Grant(lease=lease, adb=adb, in_cluster=in_cluster)

    # ---- acquire
    async def acquire(
        self,
        profile_name: str,
        holder: str,
        ttl_minutes: int,
        wait_seconds: float,
        boot_wait_seconds: float | None = None,
    ) -> Grant:
        """Claim a slot and boot it. Waits at most boot_wait_seconds (None: the
        whole boot) for the emulator; past that it returns a grant in state
        "booting" and the boot finishes in the background, so a client with a
        request timeout shorter than a cold boot still gets its lease id."""
        profile = self.store.get_profile(profile_name)
        if not self.config.min_ttl_minutes <= ttl_minutes <= self.config.max_ttl_minutes:
            raise Invalid(
                f"ttl_minutes must be between {self.config.min_ttl_minutes} and {self.config.max_ttl_minutes}"
            )
        if not holder.strip():
            raise Invalid("holder must say who you are, e.g. 'claude-code@mac/LAB-71'")
        slot = await self._claim_slot(wait_seconds)
        lease = Lease(
            id=uuid.uuid4().hex,
            profile=profile.name,
            slot=slot,
            holder=holder.strip()[:120],
            ttl_minutes=ttl_minutes,
            state=LEASE_BOOTING,
            created_at=self.clock(),
            expires_at=None,
            ended_at=None,
            end_reason=None,
        )
        self.store.insert_lease(lease)
        self.store.set_slot(slot, SLOT_BOOTING, lease.id)
        task = asyncio.create_task(self._boot(lease, profile))
        self._boots[lease.id] = task
        task.add_done_callback(lambda t: self._boots.pop(lease.id, None) and None)
        # Consumed here so a background failure is never an unretrieved exception;
        # the lease row already says boot_failed.
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        try:
            await asyncio.wait_for(asyncio.shield(task), boot_wait_seconds)
        except TimeoutError:
            pass  # still booting: hand back the lease id, heartbeat reports progress
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise
        return self.grant(self.store.get_lease(lease.id))

    async def _boot(self, lease: Lease, profile) -> None:
        try:
            await self.pods.create(
                build_pod(
                    namespace=self.config.namespace,
                    image=self.config.emulator_image,
                    slot=lease.slot,
                    lease_id=lease.id,
                    profile=profile,
                )
            )
            started = self.clock()
            self.devices[lease.id] = await self._wait_for_boot(pod_name(lease.slot, lease.id))
            self.boot_seconds.append(self.clock() - started)
        except asyncio.CancelledError:
            await self._end(lease.id, "cancelled")
            raise
        except BootFailed:
            await self._end(lease.id, "boot_failed")
            raise
        except Exception as exc:
            await self._end(lease.id, "boot_failed")
            raise BootFailed(f"could not start the emulator: {exc}") from exc
        # False when the lease was released while the boot was finishing.
        if self.store.activate_lease(lease.id, self.clock() + lease.ttl_minutes * 60):
            self.store.set_slot(lease.slot, SLOT_LEASED, lease.id)

    async def _claim_slot(self, wait_seconds: float) -> int:
        free = self.store.free_slots()
        if free and self.queue_depth() == 0:
            self.store.set_slot(free[0], SLOT_BOOTING, None)
            return free[0]
        fut: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        position = self.queue_depth()
        try:
            return await asyncio.wait_for(asyncio.shield(fut), wait_seconds)
        except TimeoutError:
            if fut.done():  # granted in the same tick the timeout fired
                return fut.result()
            fut.cancel()
            raise Busy(position) from None
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self._hand_off(fut.result())
            else:
                fut.cancel()
            raise
        finally:
            if fut in self._waiters:
                self._waiters.remove(fut)

    async def _wait_for_boot(self, name: str) -> str:
        deadline = self.clock() + self.config.boot_timeout_s
        while self.clock() < deadline:
            if await self.pods.is_failed(name):
                raise BootFailed("the emulator Pod exited during boot (is /dev/kvm available?)")
            ip = await self.pods.pod_ip(name)
            if ip and await self.probe.booted(ip):
                return ip
            await asyncio.sleep(self.config.boot_poll_s)
        raise BootFailed(f"the emulator did not finish booting within {int(self.config.boot_timeout_s)}s")

    # ---- slot hand-off
    def _hand_off(self, slot: int) -> None:
        """Give a freed slot to the oldest live waiter, or mark it free."""
        while self._waiters:
            fut = self._waiters.popleft()
            if not fut.done():
                self.store.set_slot(slot, SLOT_BOOTING, None)
                fut.set_result(slot)
                return
        self.store.set_slot(slot, SLOT_FREE, None)

    async def _end(self, lease_id: str, reason: str) -> bool:
        lease = self.store.get_lease(lease_id)
        if not self.store.end_lease(lease_id, reason, self.clock()):
            return False
        self.devices.pop(lease_id, None)
        try:
            await self.pods.delete(pod_name(lease.slot, lease.id))
        finally:
            self._hand_off(lease.slot)
        return True

    # ---- lease operations
    def _active(self, lease_id: str) -> Lease:
        lease = self.store.get_lease(lease_id)
        if lease.state != LEASE_LEASED:
            raise LeaseNotActive(
                f"lease {lease_id} is {lease.state}"
                + (f" ({lease.end_reason})" if lease.end_reason else "")
                + "; acquire a new one"
            )
        return lease

    def heartbeat(self, lease_id: str) -> Grant:
        """Extend a lease. On a lease that is still booting it only reports the
        state, which is how a caller polls a boot that outlived acquire."""
        lease = self.store.get_lease(lease_id)
        if lease.state == LEASE_BOOTING:
            return self.grant(lease)
        lease = self._active(lease_id)
        hard_stop = lease.created_at + self.config.max_age_s
        self.store.extend_lease(lease_id, min(self.clock() + lease.ttl_minutes * 60, hard_stop))
        return self.grant(self.store.get_lease(lease_id))

    async def release(self, lease_id: str, reason: str = "released") -> Lease:
        lease = self.store.get_lease(lease_id)
        if lease.state not in (LEASE_BOOTING, LEASE_LEASED):
            raise LeaseNotActive(f"lease {lease_id} already ended ({lease.end_reason})")
        await self._end(lease_id, reason)
        boot = self._boots.pop(lease_id, None)
        if boot is not None:
            boot.cancel()
            await asyncio.gather(boot, return_exceptions=True)
            # The cancelled boot may have created its Pod after _end deleted it.
            await self.pods.delete(pod_name(lease.slot, lease.id))
        return self.store.get_lease(lease_id)

    # ---- background
    async def reap(self) -> list[tuple[str, str]]:
        """End every lease that expired, aged out, or lost its Pod. Returns (lease_id, reason)."""
        ended = []
        now = self.clock()
        for lease in self.store.active_leases():
            if lease.state != LEASE_LEASED:
                continue
            reason = None
            if now - lease.created_at >= self.config.max_age_s:
                reason = "max_age"
            elif lease.expires_at is not None and now >= lease.expires_at:
                reason = "expired"
            elif await self.pods.is_failed(pod_name(lease.slot, lease.id)):
                reason = "lost"
            if reason and await self._end(lease.id, reason):
                ended.append((lease.id, reason))
        return ended

    async def reconcile(self) -> None:
        """Run once at startup, before serving. Makes Pods, slots and leases agree."""
        now = self.clock()
        pods = await self.pods.list_emulators()
        active = {lease.id: lease for lease in self.store.active_leases()}
        for lease in active.values():
            # A booting lease's caller died with the previous process; a leased
            # one without a Pod has nothing behind it.
            if lease.state == LEASE_BOOTING or pod_name(lease.slot, lease.id) not in pods:
                self.store.end_lease(lease.id, "lost", now)
        live = {lease.id for lease in self.store.active_leases()}
        for lease in self.store.active_leases():
            ip = await self.pods.pod_ip(pod_name(lease.slot, lease.id))
            if ip:
                self.devices[lease.id] = ip
        for name, lease_id in pods.items():
            if lease_id not in live:
                await self.pods.delete(name)
        for slot in self.store.list_slots():
            if slot.lease_id not in live:
                self.store.set_slot(slot.slot, SLOT_FREE, None)
