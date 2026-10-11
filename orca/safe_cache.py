"""A diskcache `Disk` that never executes data it reads (Workstream A; PYSEC-2026-2447).

`diskcache.Cache` stores every non-primitive value -- and every non-primitive KEY -- with `pickle` and `pickle.load`s it on read. Whoever can write the cache
directory or its SQLite file therefore gets code execution in the server process. Audit #007 closed the ways an attacker could reach that directory (owner-only,
canonical, sealed); this removes the dangerous primitive itself, so a tampered cache file is an error, not a shell.

* New values: JSON (a new storage mode), written without pickle. Only JSON-representable values (dict/list/str/int/float/bool/None) are accepted; sets, objects,
  NaN/Infinity raise TypeError/ValueError at write time. `str`/`int`/`float`/`bytes` keep diskcache's native storage.
* Existing pickled entries (written by earlier releases) stay readable through an unpickler that can load NO global, so `dict/list/str/int/float/bool/None`
  load and anything needing `find_class` (every `__reduce__` payload) raises `UnsafeCacheEntry`. No data migration is needed.
* Keys: only `str`/`int`/`float`/`bytes`; pickled keys are neither written nor read.
"""
from __future__ import annotations

import io
import json
import math
import pickle
import sqlite3
from typing import Any

import diskcache
from diskcache.core import MODE_PICKLE, UNKNOWN

MODE_JSON = 5


class UnsafeCacheEntry(ValueError):
    """A cache entry could not be loaded without executing or importing something. Treat the cache file as tampered with."""


class _NoGlobalsUnpickler(pickle.Unpickler):
    def find_class(self, module, name):                                # any callable/class reference = code-execution primitive
        raise UnsafeCacheEntry(f"refusing to load global {module}.{name} from a cache entry")

    def persistent_load(self, pid):
        raise UnsafeCacheEntry("refusing persistent id in a cache entry")


def _safe_loads(data: bytes) -> Any:
    try:
        return _NoGlobalsUnpickler(io.BytesIO(data)).load()
    except UnsafeCacheEntry:
        raise
    except Exception as e:                                              # truncated/garbled pickle
        raise UnsafeCacheEntry("cache entry is not a loadable plain-data pickle") from e


def _jsonable(value: Any) -> bool:
    t = type(value)
    if value is None or t is bool or t is int or t is str:
        return True
    if t is float:
        return math.isfinite(value)
    if t is list or t is tuple:
        return all(_jsonable(v) for v in value)
    if t is dict:
        return all(type(k) is str and _jsonable(v) for k, v in value.items())
    return False


class SafeDisk(diskcache.Disk):
    def put(self, key):
        t = type(key)
        if t in (bytes, str, int, float):
            return super().put(key)
        raise TypeError(f"cache keys must be str/int/float/bytes, not {t.__name__}")

    def get(self, key, raw):
        if raw:
            return super().get(key, raw)
        return _safe_loads(bytes(key))

    def store(self, value, read, key=UNKNOWN):
        t = type(value)
        if read or t in (bytes, str, int, float):
            if t is float and not math.isfinite(value):
                raise ValueError("non-finite floats are not storable")
            return super().store(value, read, key)
        if not _jsonable(value):
            raise TypeError(f"cache values must be JSON-representable plain data, not {t.__name__}")
        data = json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(data) < self.min_file_size:
            return 0, MODE_JSON, None, sqlite3.Binary(data)
        filename, full_path = self.filename(key, value)
        self._write(full_path, io.BytesIO(data), "xb")
        return len(data), MODE_JSON, filename, None

    def fetch(self, mode, filename, value, read):
        if mode == MODE_JSON:
            if value is None:
                with open(self._directory + "/" + filename, "rb") as fh:
                    data = fh.read()
            else:
                data = bytes(value)
            try:
                return json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise UnsafeCacheEntry("cache entry is not valid JSON") from e
        if mode == MODE_PICKLE:
            if value is None:
                with open(self._directory + "/" + filename, "rb") as fh:
                    return _safe_loads(fh.read())
            return _safe_loads(bytes(value))
        return super().fetch(mode, filename, value, read)


def open_cache(directory: str, **kwargs) -> diskcache.Cache:
    """The only way ORNEUR opens a diskcache store (enforced by tests/test_a_safe_cache.py)."""
    return diskcache.Cache(str(directory), disk=SafeDisk, **kwargs)
