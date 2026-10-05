"""REST API for the web UI and scripts. Same operations as the MCP tools,
plus profile management and history, which only a human needs."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from emulator_hub.auth import ui_user
from emulator_hub.catalog import DEVICES, SYSTEM_IMAGES
from emulator_hub.leases import LeaseEngine
from emulator_hub.mcp_server import engine_status
from emulator_hub.models import (
    Busy,
    HubError,
    Invalid,
    LeaseNotActive,
    NotFound,
    Profile,
)


class AcquireBody(BaseModel):
    profile: str
    ttl_minutes: int = 30
    wait_seconds: int = Field(default=0, ge=0, le=600)
    # Past this the grant comes back "booting" (the UI's refresh shows it
    # finish), so the request never outlives an ingress read timeout.
    boot_wait_seconds: int = Field(default=30, ge=0, le=600)


class ProfileBody(BaseModel):
    form_factor: str
    system_image: str
    device: str
    ram_mb: int
    cores: int


def to_http(exc: HubError) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, Busy):
        return HTTPException(409, {"message": str(exc), "position": exc.position})
    if isinstance(exc, (Invalid, LeaseNotActive)):
        return HTTPException(422 if isinstance(exc, Invalid) else 409, str(exc))
    return HTTPException(502, str(exc))


def build_api(engine: LeaseEngine) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/catalog")
    async def catalog():
        return {
            "system_images": {
                k: {"api_level": v.api_level, "form_factors": v.form_factors} for k, v in SYSTEM_IMAGES.items()
            },
            "devices": DEVICES,
        }

    @r.get("/status")
    async def status():
        return engine_status(engine)

    @r.get("/leases")
    async def history(limit: int = 100):
        return [lease.to_dict() for lease in engine.store.recent_leases(min(limit, 500))]

    @r.get("/profiles")
    async def profiles():
        return [p.to_dict() for p in engine.store.list_profiles()]

    @r.put("/profiles/{name}")
    async def put_profile(name: str, body: ProfileBody):
        try:
            return engine.store.upsert_profile(Profile(name=name, **body.model_dump())).to_dict()
        except HubError as exc:
            raise to_http(exc) from exc

    @r.delete("/profiles/{name}", status_code=204)
    async def delete_profile(name: str):
        try:
            engine.store.delete_profile(name)
        except HubError as exc:
            raise to_http(exc) from exc

    @r.post("/leases")
    async def acquire(body: AcquireBody, request: Request):
        holder = f"ui:{ui_user(request.headers)}"
        try:
            grant = await engine.acquire(
                body.profile, holder, body.ttl_minutes, body.wait_seconds, boot_wait_seconds=body.boot_wait_seconds
            )
            return grant.to_dict()
        except HubError as exc:
            raise to_http(exc) from exc

    @r.post("/leases/{lease_id}/heartbeat")
    async def heartbeat(lease_id: str):
        try:
            return engine.heartbeat(lease_id).to_dict()
        except HubError as exc:
            raise to_http(exc) from exc

    @r.delete("/leases/{lease_id}")
    async def release(lease_id: str, request: Request):
        try:
            mine = engine.store.get_lease(lease_id).holder == f"ui:{ui_user(request.headers)}"
            return (await engine.release(lease_id, reason="released" if mine else "forced")).to_dict()
        except HubError as exc:
            raise to_http(exc) from exc

    return r
