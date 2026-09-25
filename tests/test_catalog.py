"""The catalog and the emulator image must agree, or a profile could name a
system image that isn't installed and every lease for it would boot-fail."""

import re
from pathlib import Path

from emulator_hub.catalog import DEFAULT_PROFILES, DEVICES, FORM_FACTORS, SYSTEM_IMAGES
from emulator_hub.models import Profile

DOCKERFILE = Path(__file__).parent.parent / "emulator" / "Dockerfile"


def test_every_catalog_image_is_installed_by_the_emulator_dockerfile():
    installed = set(re.findall(r'"(system-images;[^"]+)"', DOCKERFILE.read_text()))
    assert {img.package for img in SYSTEM_IMAGES.values()} == installed


def test_every_form_factor_has_an_image_and_a_device():
    for ff in FORM_FACTORS:
        assert any(ff in img.form_factors for img in SYSTEM_IMAGES.values()), ff
        assert DEVICES[ff], ff


def test_default_profiles_are_valid():
    for p in DEFAULT_PROFILES:
        Profile(**p).validate()
    assert {p["form_factor"] for p in DEFAULT_PROFILES} == set(FORM_FACTORS)
