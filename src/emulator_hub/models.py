from dataclasses import asdict, dataclass

from emulator_hub.catalog import DEVICES, FORM_FACTORS, SYSTEM_IMAGES

LEASE_BOOTING = "booting"
LEASE_LEASED = "leased"
LEASE_ENDED = "ended"
ACTIVE_LEASE_STATES = (LEASE_BOOTING, LEASE_LEASED)

SLOT_FREE = "free"
SLOT_BOOTING = "booting"
SLOT_LEASED = "leased"
SLOT_DRAINING = "draining"

END_REASONS = ("released", "expired", "max_age", "boot_failed", "lost", "forced", "cancelled")


class HubError(Exception):
    """Base for failures a caller is expected to see and act on."""


class NotFound(HubError):
    pass


class Invalid(HubError):
    pass


class Busy(HubError):
    def __init__(self, position: int):
        super().__init__(f"no emulator slot free; you were number {position} in the queue")
        self.position = position


class BootFailed(HubError):
    pass


class LeaseNotActive(HubError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    form_factor: str
    system_image: str
    device: str
    ram_mb: int
    cores: int

    def validate(self) -> None:
        if not self.name or not self.name.replace("-", "").isalnum() or len(self.name) > 40:
            raise Invalid("name must be 1-40 characters of letters, digits and '-'")
        if self.form_factor not in FORM_FACTORS:
            raise Invalid(f"form_factor must be one of {', '.join(FORM_FACTORS)}")
        image = SYSTEM_IMAGES.get(self.system_image)
        if image is None:
            raise Invalid(f"system_image must be one of {', '.join(SYSTEM_IMAGES)}")
        if self.form_factor not in image.form_factors:
            raise Invalid(f"{self.system_image} cannot boot a {self.form_factor}")
        if self.device not in DEVICES[self.form_factor]:
            raise Invalid(f"device for a {self.form_factor} must be one of {', '.join(DEVICES[self.form_factor])}")
        if not 1024 <= self.ram_mb <= 4096:
            raise Invalid("ram_mb must be between 1024 and 4096")
        if not 1 <= self.cores <= 4:
            raise Invalid("cores must be between 1 and 4")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Lease:
    id: str
    profile: str
    slot: int
    holder: str
    ttl_minutes: int
    state: str
    created_at: float
    expires_at: float | None
    ended_at: float | None
    end_reason: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Slot:
    slot: int
    state: str
    lease_id: str | None
