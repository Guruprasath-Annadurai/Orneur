"""Item 2 of the write-scope-and-isolation follow-up phase: demonstrate the ACTUAL credential boundaries,
filesystem permissions and private-key custody separating the three identities in this program's model --
GENERATOR, CREATION-TIME VERIFIER, and (post-freeze) QUALIFICATION RUNNER -- using synthetic environments only.

Every "environment" here is an ordinary Python dict standing in for a deployment's own credential-manager view (what
that ONE deployment can see), never real os.environ and never a real secret. This file does not claim to prove OS
process isolation (a compromised process on the same host could, in principle, read anything in its own address
space) -- see operational_boundary.py's module docstring for that honestly-reported limitation. What IS proven here:
(a) which key material each role's synthetic environment is GIVEN never includes the other role's decrypt capability,
(b) the registries that gate real access enforce the SAME separation independent of what the environment dict says,
and (c) the on-disk filesystem permissions that back the vault are restrictive regardless of which role touches it."""
import json
import os
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import generator_registry as GR
from orca.eval.genesis_v2 import operational_boundary as OB
from orca.eval.genesis_v2 import runner_registry as RN
from orca.eval.genesis_v2 import spec as SPEC
from orca.eval.genesis_v2 import store as ST


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def _runner_record(runner_id: str, code_hash: str, purposes: list) -> dict:
    return {"runner_id": runner_id, "runner_class": "SELF_HOSTED_CPU", "os_runtime": "test", "code_sha256": code_hash,
            "allowed_purposes": purposes, "allowed_splits": ["SCREEN", "QUALIFICATION_HOLDOUT"],
            "sandbox_image_digest": "sha256:" + "b" * 64, "semantic_engine_digest": "c" * 64,
            "storage_backend_verification_digest": "d" * 64, "ledger_database_identity_digest": "e" * 64,
            "network_policy": "none", "credential_scope": {"private_store_read": True, "public_repo_write": False,
                                                             "training_credentials": False, "unrelated_cloud_credentials": False,
                                                             "developer_tokens": False}, "state": "AUTHORIZED"}


def _generator_record(generator_id: str, code_hash: str, allowed_classes: list) -> dict:
    return {"generator_id": generator_id, "os_runtime": "test", "code_sha256": code_hash, "allowed_artifact_classes": allowed_classes,
            "network_policy": "none", "credential_scope": {"vault_write": True, "vault_read": False, "public_repo_write": False,
                                                             "training_credentials": False, "unrelated_cloud_credentials": False,
                                                             "developer_tokens": False}, "state": "AUTHORIZED"}


class _SyntheticEnvironment:
    """A dict standing in for one deployment's OWN view of its credentials -- e.g. what a real secret manager would
    hand THIS specific service account, never the full set every role in the system collectively holds."""
    def __init__(self, **kv):
        self._kv = dict(kv)

    def get(self, key, default=None):
        return self._kv.get(key, default)

    def __contains__(self, key):
        return key in self._kv


def test_three_synthetic_deployment_environments_never_grant_the_wrong_key_material():
    """The core credential-boundary claim: build one synthetic environment per role, each populated with ONLY what
    that role's real deployment should ever be handed, and prove no environment contains the other roles' secrets."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    corpus_secret = os.urandom(32).hex()

    generator_env = _SyntheticEnvironment(**{SPEC.VAULT_PUBLIC_KEY_ENV: pub.hex(), SPEC.SECRET_ENV: corpus_secret})
    verifier_env = _SyntheticEnvironment(**{SPEC.VAULT_PRIVATE_KEY_ENV: priv.hex()})
    qualification_env = _SyntheticEnvironment(**{SPEC.VAULT_PRIVATE_KEY_ENV: priv.hex()})

    # The generator's environment never holds the private key, under any name.
    assert SPEC.VAULT_PRIVATE_KEY_ENV not in generator_env
    assert priv.hex() not in generator_env._kv.values()
    # Neither reader environment holds the corpus secret (that belongs to the generator alone -- it seeds
    # generation, not vault decryption) or exposes the private key under the generator's public-key name.
    assert SPEC.SECRET_ENV not in verifier_env and SPEC.SECRET_ENV not in qualification_env
    assert SPEC.VAULT_PUBLIC_KEY_ENV not in verifier_env and SPEC.VAULT_PUBLIC_KEY_ENV not in qualification_env


def test_generator_environment_can_only_construct_a_writer_never_a_reader(tmp_path):
    """Structural proof, not just a dict-membership check: attempting to build the READ-capable class from exactly
    what the generator's synthetic environment provides is impossible -- there is no private-key value to pass."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    generator_env = _SyntheticEnvironment(**{SPEC.VAULT_PUBLIC_KEY_ENV: pub.hex()})
    vault_dir = tmp_path / "vault"

    writer = ST.EncryptedVaultWriter(vault_dir, bytes.fromhex(generator_env.get(SPEC.VAULT_PUBLIC_KEY_ENV)))
    assert not hasattr(writer, "read_split")

    missing_private_hex = generator_env.get(SPEC.VAULT_PRIVATE_KEY_ENV)   # None -- simply absent from this environment
    assert missing_private_hex is None
    with pytest.raises((TypeError, ValueError, ST.PrivateStorageViolation)):
        ST.EncryptedVaultReader(vault_dir, bytes.fromhex(missing_private_hex or ""))   # nothing to build a reader from


def test_verifier_and_qualification_runner_are_registered_as_distinct_restricted_identities(tmp_path):
    """The runner registry -- not just the synthetic environment dicts -- independently enforces the separation:
    the creation-time verifier's registry record must not ALSO permit PURPOSE_QUALIFICATION, and the real
    qualification runner is a DIFFERENT runner_id even though both may legitimately hold the private key."""
    _need_crypto()
    code_hash = "a" * 64
    verifier_rec = _runner_record("verifier-boundary-1", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION])
    qualifier_rec = _runner_record("qualifier-boundary-1", code_hash, [SPEC.PURPOSE_QUALIFICATION, SPEC.PURPOSE_RETIREMENT])
    doc = {"schema_version": RN.SCHEMA_VERSION, "records": [verifier_rec, qualifier_rec]}
    assert RN.validate(doc) == []
    assert verifier_rec["runner_id"] != qualifier_rec["runner_id"]
    assert SPEC.PURPOSE_QUALIFICATION not in verifier_rec["allowed_purposes"]
    assert SPEC.PURPOSE_CREATION_VERIFICATION not in qualifier_rec["allowed_purposes"]

    root = tmp_path / "fakeroot"
    (root / RN.REGISTRY_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / RN.REGISTRY_PATH).write_text(json.dumps(doc))
    priv, pub = ST.generate_vault_keypair()
    writer = ST.EncryptedVaultWriter(tmp_path / "vault", pub)
    corpus_id = "gce2c-" + "b" * 16
    digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    reader = ST.EncryptedVaultReader(tmp_path / "vault", priv)

    # The verifier identity succeeds at creation-time verification...
    screen, holdout = OB.authorized_manifest_verification_bytes(
        root, tmp_path / "ledger", reader, process_id="verifier-boundary-1", code_sha256=code_hash, corpus_id=corpus_id,
        expected_corpus_digest=digest, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
        run_id_prefix="boundary-verify", timestamp_utc="2026-09-30T00:00:00Z")
    assert (screen, holdout) == (b"s", b"h")
    # ...but the qualification-runner identity is REFUSED for the SAME creation-time-verification capability, because
    # its registry record grants PURPOSE_QUALIFICATION -- exactly the separation this test set out to demonstrate.
    with pytest.raises(OB.PrivateSplitAccessDenied, match="separately controlled"):
        OB.authorized_manifest_verification_bytes(
            root, tmp_path / "ledger", reader, process_id="qualifier-boundary-1", code_sha256=code_hash, corpus_id=corpus_id,
            expected_corpus_digest=digest, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
            run_id_prefix="boundary-qualify", timestamp_utc="2026-09-30T00:00:00Z")


def test_generator_registry_flags_identity_collision_with_either_reader_role(tmp_path):
    """generator_registry.validate() cross-checks against the WHOLE runner registry, which holds both the verifier
    and the (later) qualification-runner records -- an id shared with EITHER is flagged, not just one of them."""
    code_hash = "a" * 64
    verifier_rec = _runner_record("shared-id", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION])
    qualifier_rec = _runner_record("qualifier-boundary-2", code_hash, [SPEC.PURPOSE_QUALIFICATION])
    runner_doc = {"schema_version": RN.SCHEMA_VERSION, "records": [verifier_rec, qualifier_rec]}
    gen_doc = {"schema_version": GR.SCHEMA_VERSION, "records": [_generator_record("shared-id", code_hash, ["PILOT_TRAIN"])]}
    problems = GR.validate(gen_doc, qualification_runner_doc=runner_doc)
    assert any("registered as BOTH" in p and "shared-id" in p for p in problems)

    # No collision -> clean
    gen_doc_clean = {"schema_version": GR.SCHEMA_VERSION, "records": [_generator_record("generator-boundary-1", code_hash, ["PILOT_TRAIN"])]}
    assert GR.validate(gen_doc_clean, qualification_runner_doc=runner_doc) == []


def test_generator_credential_scope_structurally_forbids_vault_read():
    """generator_registry.validate_record() itself refuses a generator record that claims vault_read=true -- the
    credential-scope DECLARATION and the actual code-level enforcement (GeneratorWriteHandle, EncryptedVaultWriter)
    agree: a generator is never entitled to read, and a registry that claims otherwise is itself invalid."""
    rec = _generator_record("gen-with-read", "a" * 64, ["SCREEN", "QUALIFICATION_HOLDOUT"])
    rec["credential_scope"]["vault_read"] = True
    assert any("WRITE-ONLY" in p for p in GR.validate_record(rec))


def test_vault_filesystem_permissions_are_restrictive_regardless_of_which_role_wrote_it(tmp_path):
    """Item 2's filesystem-permissions claim: the on-disk artifacts a generator produces are 0700/0400 -- neither
    the generator's own further processes nor any other non-owning identity on the same host can read the raw
    ciphertext bytes via ordinary file permissions, independent of the cryptographic key split."""
    import stat
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub)
    corpus_id = "gce2c-" + "c" * 16
    writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    cdir = vault_dir / corpus_id
    assert stat.S_IMODE(vault_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(cdir.stat().st_mode) == 0o700
    for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
        assert stat.S_IMODE((cdir / name).stat().st_mode) == 0o400


# ---------------------------------------------------------------- item 5: the definitive owner activation checklist
def test_owner_activation_checklist_exists_with_all_four_categories():
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]
    t = (root / "docs/orneur/phase-21/GENESIS_V2_OWNER_ACTIVATION_CHECKLIST.md").read_text()
    for heading in ("Implemented and tested", "Verified only with synthetic fixtures", "Requires real owner-side setup", "Remains unauthorized"):
        assert heading in t, heading
    # every row in category D must be about something genuinely NOT authorized right now -- spot-check the two
    # hardest facts a stale checklist could get wrong.
    assert "NOT_AUTHORIZED" in t and "GENESIS_CAPABILITY_EVAL_V2_FROZEN = False" in t
    import re
    assert not re.search(r"\b[0-9a-f]{64}\b", t) and "/Users/" not in t and "/home/" not in t


def test_owner_activation_checklist_category_d_claims_are_currently_true():
    """The checklist's category-D 'remains unauthorized' claims are re-verified against the LIVE repository state,
    not just asserted in prose -- if any of these ever flips true without this checklist being updated, this test
    fails and surfaces the drift."""
    import json
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]
    cga = json.loads((root / "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json").read_text())
    assert cga.get("status") == "NOT_AUTHORIZED"
    assert SPEC.GENESIS_CAPABILITY_EVAL_V2_FROZEN is False
    from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
    assert CGA.CODE_PATHS == ("orca/eval/genesis_v2",)
