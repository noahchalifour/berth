"""MCP tools. Thin: every tool delegates to the LeaseEngine and converts
HubError into ToolError so the model reads the reason instead of a crash."""

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from emulator_hub.leases import LeaseEngine
from emulator_hub.models import HubError

INSTRUCTIONS = """\
Android emulators (phone, tablet, TV) for testing. Workflow:
1. list_profiles to see what can be booted.
2. acquire(profile, holder) - blocks until the emulator has booted (up to ~3 min).
   Returns an `adb` address: run `adb connect <adb>` then use adb, flutter run,
   or any tool you like. Inside the cluster use `in_cluster` instead.
3. heartbeat(lease_id) at least every ttl_minutes or the emulator is destroyed.
4. release(lease_id) as soon as you are done. Every lease gets a fresh device;
   nothing you install survives release.
Locking is cooperative: only use a device you hold a lease for.
"""


class ProfileInfo(BaseModel):
    name: str
    form_factor: str
    system_image: str
    device: str
    ram_mb: int
    cores: int


class ProfileList(BaseModel):
    profiles: list[ProfileInfo]
    free_slots: int
    queue_depth: int


class LeaseGrant(BaseModel):
    lease_id: str
    profile: str
    slot: int
    adb: str
    in_cluster: str
    expires_at: float | None


class Released(BaseModel):
    lease_id: str
    state: str
    end_reason: str | None


class SlotInfo(BaseModel):
    slot: int
    state: str
    lease_id: str | None
    profile: str | None
    holder: str | None
    expires_at: float | None


class HubStatus(BaseModel):
    slots: list[SlotInfo]
    queue_depth: int


def build_mcp(engine: LeaseEngine) -> MCPServer:
    mcp = MCPServer("emulator-hub", instructions=INSTRUCTIONS)

    def fail(exc: HubError) -> ToolError:
        return ToolError(str(exc))

    @mcp.tool()
    async def list_profiles() -> ProfileList:
        """List bootable emulator profiles and how many slots are free right now."""
        return ProfileList(
            profiles=[ProfileInfo(**p.to_dict()) for p in engine.store.list_profiles()],
            free_slots=len(engine.store.free_slots()),
            queue_depth=engine.queue_depth(),
        )

    @mcp.tool()
    async def acquire(profile: str, holder: str, ttl_minutes: int = 30, wait_seconds: int = 300) -> LeaseGrant:
        """Boot a fresh emulator from `profile` and lease it to you.

        holder: who you are, e.g. "claude-code@mac/LAB-71" (shown in the UI).
        ttl_minutes: lease expires this long after the last heartbeat (1-120).
        wait_seconds: how long to queue if all slots are busy before giving up (0-600).
        """
        try:
            grant = await engine.acquire(profile, holder, ttl_minutes, max(0, min(wait_seconds, 600)))
        except HubError as exc:
            raise fail(exc) from exc
        return LeaseGrant(**grant.to_dict())

    @mcp.tool()
    async def heartbeat(lease_id: str) -> LeaseGrant:
        """Extend a lease by its ttl_minutes. Leases hard-stop 4 hours after acquire."""
        try:
            return LeaseGrant(**engine.heartbeat(lease_id).to_dict())
        except HubError as exc:
            raise fail(exc) from exc

    @mcp.tool()
    async def release(lease_id: str) -> Released:
        """Destroy your emulator and free its slot for the next agent."""
        try:
            lease = await engine.release(lease_id)
        except HubError as exc:
            raise fail(exc) from exc
        return Released(lease_id=lease.id, state=lease.state, end_reason=lease.end_reason)

    @mcp.tool()
    async def status() -> HubStatus:
        """Every slot with its current lease, plus queue depth."""
        return HubStatus(**engine_status(engine))

    return mcp


def engine_status(engine: LeaseEngine) -> dict:
    leases = {lease.id: lease for lease in engine.store.active_leases()}
    slots = []
    for s in engine.store.list_slots():
        lease = leases.get(s.lease_id) if s.lease_id else None
        slots.append(
            {
                "slot": s.slot,
                "state": s.state,
                "lease_id": s.lease_id,
                "profile": lease.profile if lease else None,
                "holder": lease.holder if lease else None,
                "expires_at": lease.expires_at if lease else None,
            }
        )
    return {"slots": slots, "queue_depth": engine.queue_depth()}
