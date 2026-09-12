from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import InvalidArtifactId, UnsupportedSchemaVersion
from tests.ocl.conftest import make_artifact


def test_current_schema_version_compiles():
    compile_artifact(make_artifact())


def test_unsupported_major_version_fails_closed():
    draft = make_artifact()
    from dataclasses import replace
    draft = replace(draft, schema_version="99.0.0")
    with pytest.raises(UnsupportedSchemaVersion):
        compile_artifact(draft)


def test_empty_artifact_id_rejected():
    from dataclasses import replace
    draft = replace(make_artifact(), artifact_id="")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(draft)
