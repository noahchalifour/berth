import pytest

from emulator_hub.leases import EngineConfig, LeaseEngine
from emulator_hub.store import Store
from tests.fakes import FakeClock, FakePods, FakeProbe


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def pods():
    return FakePods()


@pytest.fixture
def probe():
    return FakeProbe()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "hub.db", slot_count=3)


@pytest.fixture
def config():
    return EngineConfig(
        namespace="emulator-hub",
        emulator_image="ghcr.io/noahchalifour/emulator-hub-emulator:test",
        slot_ips=("172.24.3.155", "172.24.3.156", "172.24.3.157"),
        boot_timeout_s=30,
        boot_poll_s=0,
    )


@pytest.fixture
def engine(store, pods, probe, config, clock):
    return LeaseEngine(store, pods, probe, config, clock=clock)
