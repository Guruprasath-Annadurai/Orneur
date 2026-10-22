"""Fault injection around atomic publication."""
from __future__ import annotations

import os

import pytest

from orca.pretrain_foundation.faults import InjectedFault, destination_unchanged, publish_bytes


@pytest.mark.parametrize("mode", ["disk_full", "partial_write", "after_write_before_rename"])
def test_injected_fault_leaves_the_destination_unchanged(tmp_path, mode):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"previous")
    before = path.read_bytes()
    with pytest.raises(InjectedFault):
        publish_bytes(path, b"new-content-bytes", inject=mode)
    assert destination_unchanged(path, before)


def test_successful_publish_replaces_bytes(tmp_path):
    path = tmp_path / "artifact.bin"
    publish_bytes(path, b"hello")
    assert path.read_bytes() == b"hello"


def test_symlink_destination_is_refused(tmp_path):
    target = tmp_path / "target.bin"
    target.write_bytes(b"secret")
    link = tmp_path / "link.bin"
    os.symlink(target, link)
    with pytest.raises(InjectedFault, match="symlink"):
        publish_bytes(link, b"overwrite")
    assert target.read_bytes() == b"secret"
