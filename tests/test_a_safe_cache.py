"""Workstream A -- the cache read path must not execute data (PYSEC-2026-2447: diskcache unpickles values AND keys)."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path

import diskcache
import pytest

from orca.safe_cache import MODE_JSON, SafeDisk, UnsafeCacheEntry, open_cache

ROOT = Path(__file__).resolve().parents[1]


class Evil:
    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        return (os.system, (f"touch {self.marker}",))


def _plant(directory, key, value):
    """Write exactly what an attacker with write access to the directory could: a default-Disk cache entry (pickle)."""
    with diskcache.Cache(str(directory)) as c:
        c[key] = value


def test_positive_control_the_default_diskcache_really_executes_a_planted_entry(tmp_path):
    marker = tmp_path / "pwned-default"
    _plant(tmp_path / "c", "k", Evil(marker))
    try:
        diskcache.Cache(str(tmp_path / "c")).get("k")
    except Exception:
        pass
    assert marker.exists()                                          # the vulnerability is real, so the next tests are not vacuous


def test_a_planted_pickle_value_is_refused_and_nothing_runs(tmp_path):
    marker = tmp_path / "pwned-safe"
    _plant(tmp_path / "c", "k", Evil(marker))
    c = open_cache(tmp_path / "c")
    with pytest.raises(UnsafeCacheEntry):
        c.get("k")
    assert not marker.exists()


def test_a_planted_large_pickle_file_is_refused_and_nothing_runs(tmp_path):
    marker = tmp_path / "pwned-file"

    class BigEvil(Evil):
        def __reduce__(self):
            return (os.system, (f"touch {self.marker}",), None, None, None) if False else (os.system, (f"touch {self.marker} # " + "x" * 70_000,))

    _plant(tmp_path / "c", "k", BigEvil(marker))
    c = open_cache(tmp_path / "c")
    with pytest.raises(UnsafeCacheEntry):
        c.get("k")
    assert not marker.exists()


def test_a_planted_pickled_KEY_is_never_loaded(tmp_path):
    marker = tmp_path / "pwned-key"
    _plant(tmp_path / "c", Evil(marker), "value")                  # the key itself is the payload
    c = open_cache(tmp_path / "c")
    with pytest.raises(UnsafeCacheEntry):
        list(c.iterkeys())
    assert not marker.exists()


def test_a_value_swapped_in_the_sqlite_file_after_the_fact_is_refused(tmp_path):
    marker = tmp_path / "pwned-sql"
    c = open_cache(tmp_path / "c")
    c["k"] = {"a": 1}
    c.close()
    # attacker edits the DB: replace the JSON blob with a pickle payload and flip the mode to pickle (4)
    import pickle
    evil = pickle.dumps(Evil(marker))
    con = sqlite3.connect(tmp_path / "c" / "cache.db")
    con.execute("UPDATE Cache SET mode=4, value=? WHERE key='k'", (sqlite3.Binary(evil),))
    con.commit()
    con.close()
    c2 = open_cache(tmp_path / "c")
    with pytest.raises(UnsafeCacheEntry):
        c2.get("k")
    assert not marker.exists()


@pytest.mark.parametrize("value", ["text", 7, 2.5, True, None, [1, "a", None, [2, 3]], {"a": {"b": [1, 2]}, "c": "d"}, {"big": "x" * 100_000}, "é☃" * 10])
def test_plain_data_round_trips(tmp_path, value):
    c = open_cache(tmp_path / "c")
    c["k"] = value
    assert c.get("k") == value
    c.close()
    assert open_cache(tmp_path / "c").get("k") == value             # also after reopening


def test_new_dict_values_are_stored_as_json_not_pickle(tmp_path):
    c = open_cache(tmp_path / "c")
    c["k"] = {"a": 1}
    c.close()
    con = sqlite3.connect(tmp_path / "c" / "cache.db")
    assert con.execute("SELECT mode FROM Cache WHERE key='k'").fetchone()[0] == MODE_JSON


@pytest.mark.parametrize("bad", [{1, 2}, object(), Evil("x"), float("nan"), float("inf"), {"k": {1, 2}}, {1: "non-string key"}, lambda: 1])
def test_non_json_values_are_rejected_at_write_time(tmp_path, bad):
    c = open_cache(tmp_path / "c")
    with pytest.raises((TypeError, ValueError)):
        c["k"] = bad
    assert "k" not in c


def test_pickled_keys_are_rejected_at_write_time(tmp_path):
    c = open_cache(tmp_path / "c")
    with pytest.raises(TypeError):
        c[("a", "tuple")] = 1


def test_legacy_plain_pickles_written_by_earlier_releases_stay_readable(tmp_path):
    for k, v in (("a", {"x": [1, 2, 3]}), ("b", ["l"]), ("c", "s"), ("d", 5)):
        _plant(tmp_path / "c", k, v)
    c = open_cache(tmp_path / "c")
    assert c.get("a") == {"x": [1, 2, 3]} and c.get("b") == ["l"] and c.get("c") == "s" and c.get("d") == 5


def test_concurrent_writers_and_readers(tmp_path):
    c = open_cache(tmp_path / "c")
    errs = []

    def go(i):
        try:
            for j in range(40):
                c[f"k{i}-{j}"] = {"i": i, "j": j}
                assert c.get(f"k{i}-{j}") == {"i": i, "j": j}
        except Exception as e:                                      # pragma: no cover
            errs.append(repr(e))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs


def test_the_two_production_stores_use_the_safe_disk(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    import orca.lens.queue as q
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(mode=0o700)
    monkeypatch.setattr(mem, "CACHE_DIR", cache_dir)
    sm = mem.SemanticMemory()
    assert isinstance(sm._cache.disk, SafeDisk)
    sm.store_concept("c", "d")
    assert sm.all_concepts() == {"c": "d"}
    assert "open_cache" in Path(q.__file__).read_text()


def test_no_module_opens_a_raw_diskcache_cache():
    import ast
    offenders = []
    for py in (ROOT / "orca").rglob("*.py"):
        if py.name == "safe_cache.py":
            continue
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("Cache", "FanoutCache", "Index", "Deque") \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "diskcache":
                offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, offenders
