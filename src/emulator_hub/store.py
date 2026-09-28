"""SQLite persistence. Single process, single event loop: every call is short
and synchronous, so the event loop itself serializes writers."""

import sqlite3
from pathlib import Path

from emulator_hub.catalog import DEFAULT_PROFILES
from emulator_hub.models import (
    ACTIVE_LEASE_STATES,
    LEASE_BOOTING,
    LEASE_ENDED,
    LEASE_LEASED,
    SLOT_FREE,
    Invalid,
    Lease,
    NotFound,
    Profile,
    Slot,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    name TEXT PRIMARY KEY,
    form_factor TEXT NOT NULL,
    system_image TEXT NOT NULL,
    device TEXT NOT NULL,
    ram_mb INTEGER NOT NULL,
    cores INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
    slot INTEGER PRIMARY KEY,
    state TEXT NOT NULL,
    lease_id TEXT
);
CREATE TABLE IF NOT EXISTS leases (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    slot INTEGER NOT NULL,
    holder TEXT NOT NULL,
    ttl_minutes INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL,
    ended_at REAL,
    end_reason TEXT
);
CREATE INDEX IF NOT EXISTS leases_by_state ON leases (state);
"""


class Store:
    def __init__(self, path: str | Path, slot_count: int):
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        for n in range(slot_count):
            self._db.execute("INSERT OR IGNORE INTO slots (slot, state) VALUES (?, ?)", (n, SLOT_FREE))
        self._db.execute("DELETE FROM slots WHERE slot >= ?", (slot_count,))
        if self._db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0:
            for p in DEFAULT_PROFILES:
                self.upsert_profile(Profile(**p))

    # profiles
    def list_profiles(self) -> list[Profile]:
        return [Profile(**dict(r)) for r in self._db.execute("SELECT * FROM profiles ORDER BY name")]

    def get_profile(self, name: str) -> Profile:
        row = self._db.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise NotFound(f"no profile named {name!r}")
        return Profile(**dict(row))

    def upsert_profile(self, profile: Profile) -> Profile:
        profile.validate()
        self._db.execute(
            "INSERT INTO profiles VALUES (:name, :form_factor, :system_image, :device, :ram_mb, :cores) "
            "ON CONFLICT(name) DO UPDATE SET form_factor=excluded.form_factor, system_image=excluded.system_image, "
            "device=excluded.device, ram_mb=excluded.ram_mb, cores=excluded.cores",
            profile.to_dict(),
        )
        return profile

    def delete_profile(self, name: str) -> None:
        self.get_profile(name)
        in_use = self._db.execute(
            f"SELECT COUNT(*) FROM leases WHERE profile = ? AND state IN {ACTIVE_LEASE_STATES}", (name,)
        ).fetchone()[0]
        if in_use:
            raise Invalid(f"profile {name!r} has an active lease; release it first")
        self._db.execute("DELETE FROM profiles WHERE name = ?", (name,))

    # slots
    def list_slots(self) -> list[Slot]:
        return [Slot(**dict(r)) for r in self._db.execute("SELECT * FROM slots ORDER BY slot")]

    def free_slots(self) -> list[int]:
        return [r[0] for r in self._db.execute("SELECT slot FROM slots WHERE state = ? ORDER BY slot", (SLOT_FREE,))]

    def set_slot(self, slot: int, state: str, lease_id: str | None) -> None:
        self._db.execute("UPDATE slots SET state = ?, lease_id = ? WHERE slot = ?", (state, lease_id, slot))

    # leases
    def insert_lease(self, lease: Lease) -> None:
        self._db.execute(
            "INSERT INTO leases VALUES (:id, :profile, :slot, :holder, :ttl_minutes, :state, "
            ":created_at, :expires_at, :ended_at, :end_reason)",
            lease.to_dict(),
        )

    def get_lease(self, lease_id: str) -> Lease:
        row = self._db.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if row is None:
            raise NotFound(f"no lease {lease_id!r}")
        return Lease(**dict(row))

    def activate_lease(self, lease_id: str, expires_at: float) -> bool:
        cur = self._db.execute(
            "UPDATE leases SET state = ?, expires_at = ? WHERE id = ? AND state = ?",
            (LEASE_LEASED, expires_at, lease_id, LEASE_BOOTING),
        )
        return cur.rowcount == 1

    def extend_lease(self, lease_id: str, expires_at: float) -> None:
        self._db.execute(
            "UPDATE leases SET expires_at = ? WHERE id = ? AND state = ?", (expires_at, lease_id, LEASE_LEASED)
        )

    def end_lease(self, lease_id: str, reason: str, now: float) -> bool:
        cur = self._db.execute(
            "UPDATE leases SET state = ?, end_reason = ?, ended_at = ? "
            f"WHERE id = ? AND state IN {ACTIVE_LEASE_STATES}",
            (LEASE_ENDED, reason, now, lease_id),
        )
        return cur.rowcount == 1

    def active_leases(self) -> list[Lease]:
        return [
            Lease(**dict(r))
            for r in self._db.execute(f"SELECT * FROM leases WHERE state IN {ACTIVE_LEASE_STATES} ORDER BY created_at")
        ]

    def recent_leases(self, limit: int = 100) -> list[Lease]:
        return [
            Lease(**dict(r))
            for r in self._db.execute("SELECT * FROM leases ORDER BY created_at DESC LIMIT ?", (limit,))
        ]
