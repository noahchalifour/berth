from prometheus_client import Counter, Gauge, Histogram

SLOTS_IN_USE = Gauge("emulator_hub_slots_in_use", "Slots booting or leased")
QUEUE_DEPTH = Gauge("emulator_hub_queue_depth", "Callers waiting for a slot")
BOOT_SECONDS = Histogram(
    "emulator_hub_boot_seconds", "Acquire-to-booted duration", buckets=(15, 30, 45, 60, 90, 120, 180)
)
LEASES_ENDED = Counter("emulator_hub_leases_ended_total", "Leases ended, by reason", ["reason"])
