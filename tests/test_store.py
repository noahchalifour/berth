import pytest

from emulator_hub.models import Invalid, NotFound, Profile
from emulator_hub.store import Store


def test_first_start_seeds_default_profiles_and_slots(tmp_path):
    s = Store(tmp_path / "db", slot_count=2)
    assert [p.name for p in s.list_profiles()] == ["phone", "tablet", "tv"]
    assert [(x.slot, x.state) for x in s.list_slots()] == [(0, "free"), (1, "free")]


def test_restart_keeps_edits_and_resizes_slots(tmp_path):
    s = Store(tmp_path / "db", slot_count=3)
    s.delete_profile("tablet")
    s = Store(tmp_path / "db", slot_count=2)
    assert [p.name for p in s.list_profiles()] == ["phone", "tv"]  # not re-seeded
    assert [x.slot for x in s.list_slots()] == [0, 1]


def test_upsert_validates(tmp_path):
    s = Store(tmp_path / "db", slot_count=1)
    with pytest.raises(Invalid, match="cannot boot a tv"):
        s.upsert_profile(Profile("x", "tv", "android-35-google-apis", "tv_1080p", 2048, 2))
    with pytest.raises(Invalid, match="ram_mb"):
        s.upsert_profile(Profile("x", "phone", "android-35-google-apis", "pixel_8", 512, 2))
    with pytest.raises(NotFound):
        s.delete_profile("nope")
