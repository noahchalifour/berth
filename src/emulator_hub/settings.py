from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HUB_")

    namespace: str = "emulator-hub"
    emulator_image: str
    # Comma-separated LAN IPs of slot-0..N LoadBalancer Services, in slot order.
    slot_ips: str
    db_path: str = "/data/hub.db"
    api_token: str
    reap_interval_s: float = 15
    boot_timeout_s: float = 180
    # Directory holding `adbkey` and `adbkey.pub` (an `adb keygen` pair, e.g. a
    # mounted Secret). Every emulator trusts this key and agents are given it,
    # so adb works on images that enforce adb auth (android-tv user builds).
    # Unset: each emulator generates its own key and only the google_apis
    # images accept other clients.
    adb_key_dir: str | None = None
    # Hard stop for a lease regardless of heartbeats.
    max_age_s: float = 4 * 3600
    ui_port: int = 8080
    machine_port: int = 8081

    @property
    def slot_ip_list(self) -> tuple[str, ...]:
        return tuple(ip.strip() for ip in self.slot_ips.split(",") if ip.strip())

    def adb_key(self) -> tuple[str, str] | None:
        """(private PEM, public key line) from adb_key_dir, or None."""
        if not self.adb_key_dir:
            return None
        from pathlib import Path

        d = Path(self.adb_key_dir)
        return (d / "adbkey").read_text().strip(), (d / "adbkey.pub").read_text().strip()
