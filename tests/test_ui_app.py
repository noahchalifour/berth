import httpx

from emulator_hub.app import create_ui_app
from tests.fakes import FakeScreen

UI = {"X-authentik-username": "noah"}
BEARER = {"Authorization": "Bearer s3cret"}


def ui_client(engine):
    app = create_ui_app(engine, screen_factory=FakeScreen)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub")


async def test_ui_port_requires_authentik_header_only(engine):
    async with ui_client(engine) as c:
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.get("/api/status")).status_code == 401
        assert (await c.get("/api/status", headers=BEARER)).status_code == 401  # bearer means nothing here
        assert (await c.get("/api/status", headers=UI)).status_code == 200
        assert (await c.get("/", headers=UI)).status_code == 200
        assert (await c.get("/api/me", headers=UI)).json() == {"user": "noah"}


async def test_ui_serves_berth_branding(engine):
    async with ui_client(engine) as c:
        page = await c.get("/", headers=UI)
    assert page.status_code == 200
    assert "<title>Berth</title>" in page.text
    assert 'alt="">Berth</div>' in page.text
    assert "Emulator Hub" not in page.text


async def test_ui_serves_selected_logo_and_favicon(engine):
    from html.parser import HTMLParser
    from io import BytesIO

    from PIL import Image

    class ImagesAndLinks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.images = []
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "img":
                self.images.append(dict(attrs))
            elif tag == "link":
                self.links.append(dict(attrs))

    async with ui_client(engine) as c:
        page = await c.get("/", headers=UI)
        parser = ImagesAndLinks()
        parser.feed(page.text)
        mark = next((image for image in parser.images if image.get("class") == "brand-mark"), None)
        assert mark is not None, "Header must display the selected Berth symbol"
        assert mark["alt"] == ""  # Adjacent Berth text provides the accessible name.
        icon = next(link for link in parser.links if link.get("rel") == "icon")
        for path in (mark["src"], icon["href"]):
            assert (await c.get(path)).status_code == 401
            response = await c.get(path, headers=UI)
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            with Image.open(BytesIO(response.content)) as image:
                assert image.width == image.height
                assert image.mode == "RGBA"
                assert image.getpixel((0, 0))[3] == 0


async def test_ui_lease_is_attributed_and_other_peoples_release_is_forced(engine):
    async with ui_client(engine) as c:
        mine = (await c.post("/api/leases", json={"profile": "phone"}, headers=UI)).json()
        assert engine.store.get_lease(mine["lease_id"]).holder == "ui:noah"
        assert (await c.delete(f"/api/leases/{mine['lease_id']}", headers=UI)).json()["end_reason"] == "released"
        agent = await engine.acquire("tv", "claude-code@mac", 30, 1)
        ended = (await c.delete(f"/api/leases/{agent.lease.id}", headers=UI)).json()
        assert ended["end_reason"] == "forced"


async def test_profile_crud_validates_against_catalog(engine):
    body = {
        "form_factor": "tv",
        "system_image": "android-35-google-apis",
        "device": "tv_1080p",
        "ram_mb": 2048,
        "cores": 2,
    }
    async with ui_client(engine) as c:
        bad = await c.put("/api/profiles/watch", json=body, headers=UI)
        assert bad.status_code == 422 and "cannot boot a tv" in bad.text
        ok = await c.put(
            "/api/profiles/tv-720",
            json=body | {"system_image": "android-36-android-tv", "device": "tv_720p"},
            headers=UI,
        )
        assert ok.status_code == 200
        assert (await c.delete("/api/profiles/tv-720", headers=UI)).status_code == 204


async def test_busy_is_409_with_position(engine):
    async with ui_client(engine) as c:
        for _ in range(3):
            assert (await c.post("/api/leases", json={"profile": "phone"}, headers=UI)).status_code == 200
        busy = await c.post("/api/leases", json={"profile": "phone"}, headers=UI)
        assert busy.status_code == 409 and busy.json()["detail"]["position"] == 1


async def test_rest_acquire_returns_a_booting_grant_past_boot_wait(engine, probe):
    probe.after = 10**9  # never boots during this test
    async with ui_client(engine) as c:
        r = await c.post("/api/leases", json={"profile": "phone", "boot_wait_seconds": 0}, headers=UI)
    assert r.status_code == 200 and r.json()["state"] == "booting"
