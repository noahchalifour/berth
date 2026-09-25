class FakePods:
    def __init__(self):
        self.pods: dict[str, dict] = {}
        self.failed: set[str] = set()
        self.create_error: Exception | None = None

    async def create(self, manifest: dict) -> None:
        if self.create_error:
            raise self.create_error
        self.pods[manifest["metadata"]["name"]] = manifest

    async def delete(self, name: str) -> None:
        self.pods.pop(name, None)

    async def list_emulators(self) -> dict[str, str]:
        return {n: m["metadata"]["labels"]["emulator-hub/lease"] for n, m in self.pods.items()}

    async def pod_ip(self, name: str) -> str | None:
        return "10.233.0.9" if name in self.pods else None

    async def is_failed(self, name: str) -> bool:
        return name not in self.pods or name in self.failed


class FakeProbe:
    """Reports booted on the Nth call (default: immediately)."""

    def __init__(self, after: int = 1):
        self.after = after
        self.calls = 0

    async def booted(self, pod_ip: str) -> bool:
        self.calls += 1
        return self.calls >= self.after


class FakeScreen:
    """Emits `frames` then idles like a static emulator screen; records input."""

    def __init__(self, pod_ip: str, frames: int = 3):
        self.pod_ip = pod_ip
        self._frames = frames
        self.inputs: list[tuple] = []
        self.closed = False

    async def frames(self):
        import asyncio

        for i in range(self._frames):
            yield f"jpeg-{i}".encode()
        await asyncio.Event().wait()

    async def snapshot(self, width: int = 240) -> bytes:
        return b"thumb"

    async def touch(self, x, y, down):
        self.inputs.append(("touch", x, y, down))

    async def key(self, key):
        self.inputs.append(("key", key))

    async def text(self, text):
        self.inputs.append(("text", text))

    async def close(self):
        self.closed = True


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds
