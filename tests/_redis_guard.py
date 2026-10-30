"""Never FLUSHDB a Redis database that holds anything but ORNEUR's own keys.

Several suites clear their dedicated test DB (14/15) between tests. Those URLs are hard-coded, but a developer's Redis may well use the same DB
numbers for something else; wiping that would be unrecoverable. ``safe_flush`` refuses unless every key present is an ORNEUR key."""
from __future__ import annotations

_ORNEUR_PREFIXES = ("orca:", "orneur:")


def safe_flush(client) -> None:
    foreign = []
    for key in client.scan_iter(match="*", count=500):
        name = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
        if not name.startswith(_ORNEUR_PREFIXES):
            foreign.append(name)
            if len(foreign) >= 3:
                break
    if foreign:
        raise RuntimeError(f"refusing to FLUSHDB: this Redis database holds non-ORNEUR keys (e.g. {foreign}); point the test at a dedicated database")
    client.flushdb()
