"""Task B -- an environment flag must never promote an unqualified model to the public.

Synthetic Ed25519 keys only; no model, Ollama, network, key material from the repository, or real user. Every test asserts the SAFE behaviour.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from orca.gateway import serving_authority as sa
from orca.gateway import wiring
from orca.gateway.errors import ModelNotRoutableError
from orca.serve.errors import public_error
from orca.serve.registry import TierResolution

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + "ab" * 32
OTHER_DIGEST = "sha256:" + "cd" * 32
LABEL = "Experimental model: ORNEUR Novus is not qualified and may be wrong; invited testers only."
NOVUS = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    def make():
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        return priv, pub

    return make


@pytest.fixture
def world(keys, monkeypatch):
    """A registry with one active synthetic authority, its pin patched into the module, and a grant factory."""
    priv, pub = keys()
    registry = {"schema_version": sa.REGISTRY_SCHEMA, "records": [{
        "id": "synthetic-founder", "public_key_hex": pub, "activation_timestamp": _ts(NOW - timedelta(days=30)), "expiry": None, "revoked": False}]}
    monkeypatch.setattr(sa, "PINNED_REGISTRY_SHA256", sa.registry_digest(registry))

    def grant(**over):
        g = {
            "schema": sa.GRANT_SCHEMA, "grant_id": "g-1", "purpose": sa.PURPOSE, "model_family": "orneur-novus", "tier": "core",
            "ollama_tag": "orca-core-combined-v2", "ollama_digest": DIGEST, "not_before": _ts(NOW - timedelta(hours=1)),
            "expires_at": _ts(NOW + timedelta(days=7)), "eligibility": {"user_ids": ["u-invited"], "signup_seq_max": None},
            "label": LABEL, "authorizing_authority": "synthetic-founder",
        }
        g.update(over)
        g.pop("signature", None)
        g["signature"] = priv.sign(sa.signing_bytes(g)).hex()
        return g

    class W:
        pass

    w = W()
    w.priv, w.registry, w.grant = priv, registry, grant
    w.trust = lambda *grants, revoked=(): (registry, {"schema_version": sa.GRANT_SCHEMA, "grants": list(grants)},
                                          {"schema_version": sa.GRANT_SCHEMA, "revoked_ids": list(revoked)})
    return w


def decide(w, *grants, viewer=sa.Viewer("u-invited", 7), tag="orca-core-combined-v2", tier="core", family="orneur-novus", digest=DIGEST, edge=True,
           revoked=(), trust=None):
    return sa.decide_self_hosted(model_family=family, tier=tier, ollama_tag=tag, public_edge=edge, viewer=viewer, installed_digest=digest, now=NOW,
                                 trust_files=trust or w.trust(*grants, revoked=revoked))


# ── the flag ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_flag_alone_never_authorizes_public_serving(monkeypatch):
    wiring.reset_for_tests()
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    monkeypatch.setenv("ORNEUR_ALLOW_EXPERIMENTAL_SERVING", "1")
    brain = wiring.brain_for_tier_resolution(NOVUS)
    assert brain.allow_experimental is False
    with pytest.raises(ModelNotRoutableError):
        brain._gateway.resolve_deployment(brain.model_id, brain.model_version, brain.allow_experimental)
    pol = wiring.serving_policy()
    assert pol["operator_acknowledged_experimental_serving"] is True and pol["experimental_flag_has_authorizing_effect"] is False
    assert pol["experimental_self_hosted_models_served"] is False
    wiring.reset_for_tests()


def test_private_deployments_are_unchanged(world):
    d = decide(world, edge=False, viewer=sa.Viewer())
    assert d.allowed and d.lifecycle == "EXPERIMENTAL" and "not qualified" in d.label.lower()


# ── a valid grant, and nothing wider than it ─────────────────────────────────────────────────────────────────────────────────────

def test_a_valid_grant_serves_exactly_what_it_names_with_its_own_label(world):
    d = decide(world, world.grant())
    assert d.allowed and d.grant_id == "g-1" and d.label == LABEL
    assert d.lifecycle == "EXPERIMENTAL"           # a grant is not a promotion


@pytest.mark.parametrize("why,kwargs", [
    ("other user", {"viewer": sa.Viewer("u-stranger", 500)}),
    ("anonymous", {"viewer": sa.Viewer()}),
    ("other tag (alias)", {"tag": "orca-core"}),
    ("other tier", {"tier": "ultra"}),
    ("other family", {"family": "orneur-aeternum"}),
    ("re-pulled / different artifact under the same tag", {"digest": OTHER_DIGEST}),
    ("artifact missing / runtime unreachable", {"digest": None}),
])
def test_scope_is_exact(world, why, kwargs):
    assert decide(world, world.grant(), **kwargs).allowed is False, why


def test_cohort_eligibility_by_signup_order(world):
    g = world.grant(eligibility={"user_ids": [], "signup_seq_max": 100})
    assert decide(world, g, viewer=sa.Viewer("u-x", 100)).allowed
    assert not decide(world, g, viewer=sa.Viewer("u-y", 101)).allowed
    assert not decide(world, g, viewer=sa.Viewer("u-z", None)).allowed


def test_a_step_down_is_not_silently_covered_by_another_tiers_grant(world):
    """An 'ultra' request that the registry steps down to the core artifact is judged as ultra/<core tag>: a core grant does not cover it."""
    assert decide(world, world.grant(), tier="ultra", family="orneur-aeternum").allowed is False
    explicit = world.grant(grant_id="g-2", model_family="orneur-aeternum", tier="ultra")      # an explicit, signed fallback approval
    assert decide(world, explicit, tier="ultra", family="orneur-aeternum").allowed is True


# ── forgery, tampering, time, revocation ───────────────────────────────────────────────────────────────────────────────────────────

def test_unsigned_and_wrongly_signed_grants_are_denied(world, keys):
    g = world.grant()
    assert not decide(world, {**g, "signature": ""}).allowed
    attacker, _ = keys()
    forged = {k: v for k, v in g.items() if k != "signature"}
    forged["signature"] = attacker.sign(sa.signing_bytes(forged)).hex()
    assert not decide(world, forged).allowed


@pytest.mark.parametrize("field,value", [
    ("ollama_tag", "orca-core"), ("ollama_digest", OTHER_DIGEST), ("tier", "ultra"), ("model_family", "orneur-aeternum"),
    ("expires_at", "2030-01-01T00:00:00Z"), ("label", LABEL + " (edited)"), ("eligibility", {"user_ids": ["u-stranger"], "signup_seq_max": None}),
    ("grant_id", "g-other"),
])
def test_any_edit_after_signing_breaks_the_signature(world, field, value):
    g = world.grant()
    g[field] = value
    assert not decide(world, g, viewer=sa.Viewer("u-stranger", 1), tier=g["tier"], family=g["model_family"], tag=g["ollama_tag"],
                      digest=g["ollama_digest"]).allowed


def test_a_signature_for_another_purpose_domain_is_rejected(world):
    g = {k: v for k, v in world.grant().items() if k != "signature"}
    g["signature"] = world.priv.sign(b"orneur-training-authorization/1\n" + sa._canonical(g)).hex()
    assert not decide(world, g).allowed


def test_validity_window(world):
    assert not decide(world, world.grant(not_before=_ts(NOW + timedelta(minutes=1)), expires_at=_ts(NOW + timedelta(days=2)))).allowed
    assert not decide(world, world.grant(not_before=_ts(NOW - timedelta(days=2)), expires_at=_ts(NOW))).allowed          # expires_at is exclusive
    assert not decide(world, world.grant(not_before=_ts(NOW - timedelta(hours=1)), expires_at=_ts(NOW + timedelta(days=31)))).allowed


def test_revocation_of_the_grant_and_of_the_authority(world):
    assert not decide(world, world.grant(), revoked=["g-1"]).allowed
    registry = json.loads(json.dumps(world.registry))
    registry["records"][0]["revoked"] = True
    assert not sa.decide_self_hosted(model_family="orneur-novus", tier="core", ollama_tag="orca-core-combined-v2", public_edge=True,
                                     viewer=sa.Viewer("u-invited", 7), installed_digest=DIGEST, now=NOW,
                                     trust_files=(registry, {"grants": [world.grant()]}, {"revoked_ids": []})).allowed


def test_a_forged_registry_does_not_match_the_source_pin(world, keys):
    attacker, pub = keys()
    registry = {"schema_version": sa.REGISTRY_SCHEMA, "records": [{
        "id": "synthetic-founder", "public_key_hex": pub, "activation_timestamp": _ts(NOW - timedelta(days=30)), "expiry": None, "revoked": False}]}
    g = {k: v for k, v in world.grant().items() if k != "signature"}
    g["signature"] = attacker.sign(sa.signing_bytes(g)).hex()
    d = sa.decide_self_hosted(model_family="orneur-novus", tier="core", ollama_tag="orca-core-combined-v2", public_edge=True,
                              viewer=sa.Viewer("u-invited", 7), installed_digest=DIGEST, now=NOW,
                              trust_files=(registry, {"grants": [g]}, {"revoked_ids": []}))
    assert d.allowed is False and "pin" in d.reason


def test_the_committed_registry_is_empty_and_matches_the_pin():
    registry, grants, revoked = sa.load_trust_files()
    assert registry == sa.empty_registry() and sa.registry_digest(registry) == sa.PINNED_REGISTRY_SHA256
    assert grants["grants"] == [] and revoked["revoked_ids"] == []


@pytest.mark.parametrize("trust", [(None, {"grants": []}, {"revoked_ids": []}), ("{}", {"grants": []}, {"revoked_ids": []}),
                                   (None, None, None)])
def test_unreadable_or_malformed_trust_files_deny(world, trust):
    assert not decide(world, trust=trust).allowed


@pytest.mark.parametrize("over", [
    {"label": "Experimental model."},                                                      # too short / does not disclose
    {"label": "A perfectly fine and very long description of this lovely model for you."},  # long but not truthful
    {"eligibility": {"user_ids": [], "signup_seq_max": None}},                             # open to everyone
    {"purpose": "TRAINING"}, {"schema": "other/1"}, {"ollama_digest": "abc"},
])
def test_structurally_unacceptable_grants_are_denied_even_when_signed(world, over):
    assert not decide(world, world.grant(**over)).allowed


# ── aliasing and retired identities ────────────────────────────────────────────────────────────────────────────────────────────────

def test_pointing_the_nano_tier_at_another_model_does_not_inherit_the_legacy_exemption(world):
    d = decide(world, tier="nano", family="orneur-genesis", tag="orca-core-combined-v2", viewer=sa.Viewer())
    assert d.allowed is False and d.lifecycle == "EXPERIMENTAL"


def test_only_the_pinned_legacy_artifact_is_legacy_and_it_is_labelled_not_qualified(world):
    d = decide(world, tier="nano", family="orneur-genesis", tag="orca-nano-v7", viewer=sa.Viewer(), digest=None)
    assert d.allowed and d.lifecycle == "LEGACY_PRODUCTION_SERVING" and "not the canonical" in d.label
    assert not decide(world, tier="nano", family="orneur-genesis", tag="orca-nano", viewer=sa.Viewer(), digest=None).allowed   # the bare alias is not an identity
    assert not decide(world, tier="core", family="orneur-novus", tag="orca-nano-v7", viewer=sa.Viewer(), digest=None).allowed   # right name, wrong family/tier


# ── wiring: stale registrations, config changes, missing artifacts ─────────────────────────────────────────────────────────────────

def _brain(monkeypatch, world, resolution, *, digests, viewer="u-invited", grants=(), edge=True):
    wiring.reset_for_tests()
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1" if edge else "0")
    monkeypatch.setattr(wiring, "installed_digests", lambda host: digests)
    monkeypatch.setattr(wiring, "_viewer_for", lambda uid: sa.Viewer(uid, 7) if uid else sa.Viewer())
    monkeypatch.setattr(sa, "load_trust_files", lambda: world.trust(*grants))
    return wiring.brain_for_tier_resolution(NOVUS if resolution is None else resolution, viewer_user_id=viewer)


def _routable(brain):
    try:
        brain._gateway.resolve_deployment(brain.model_id, brain.model_version, brain.allow_experimental)
        return True
    except ModelNotRoutableError:
        return False


def _live(world, **over):
    """A grant valid around the REAL clock (the wiring layer reads the system time)."""
    real = datetime.now(timezone.utc)
    return world.grant(not_before=_ts(real - timedelta(hours=1)), expires_at=_ts(real + timedelta(days=7)), **over)


def test_wiring_serves_only_an_eligible_viewer_of_the_exact_installed_artifact(monkeypatch, world):
    g = _live(world)
    tag = "orca-core-combined-v2"
    assert _routable(_brain(monkeypatch, world, None, digests={tag: DIGEST}, grants=[g]))
    assert not _routable(_brain(monkeypatch, world, None, digests={tag: DIGEST}, grants=[g], viewer="u-stranger"))
    assert not _routable(_brain(monkeypatch, world, None, digests={tag: DIGEST}, grants=[g], viewer=None))
    assert not _routable(_brain(monkeypatch, world, None, digests={tag: OTHER_DIGEST}, grants=[g]))      # stale: artifact replaced after signing
    assert not _routable(_brain(monkeypatch, world, None, digests={}, grants=[g]))                       # missing artifact
    assert not _routable(_brain(monkeypatch, world, None, digests=None, grants=[g]))                     # runtime unreachable -> fail closed
    wiring.reset_for_tests()


def test_config_change_after_signing_is_not_covered(monkeypatch, world):
    g = _live(world)
    changed = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v3", data_left_infrastructure=False)
    assert not _routable(_brain(monkeypatch, world, changed, digests={"orca-core-combined-v3": DIGEST}, grants=[g]))
    wiring.reset_for_tests()


def test_a_stale_persisted_legacy_record_is_overwritten_with_the_truthful_lifecycle(monkeypatch, world, isolated_home):
    """An earlier build labelled anything on the nano tier LEGACY and persisted it; resolving again must not keep that label."""
    from orca.gateway.deployment import ModelDeployment

    odd = TierResolution(tier="nano", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)
    brain = _brain(monkeypatch, world, odd, digests={}, viewer=None)
    from orca.gateway.wiring import stable_deployment_id

    dep_id = stable_deployment_id("ollama", "orca-core-combined-v2", "orneur-genesis")
    dep = brain._gateway._deployments[dep_id]
    assert dep.lifecycle == "EXPERIMENTAL" and not _routable(brain)
    assert ModelDeployment.load(dep_id).lifecycle == "EXPERIMENTAL"
    wiring.reset_for_tests()


# ── safe errors ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_routing_refusal_is_a_clean_model_unavailable_error_without_internals():
    err = public_error(ModelNotRoutableError("orneur-novus", "no routable deployment with lifecycle=EXPERIMENTAL; grant g-1 digest sha256:ab"),
                       route="/api/chat")
    body = json.dumps(err.as_json()) + json.dumps(err.as_sse())
    assert err.code == "model_unavailable"
    for leak in ("orneur-novus", "EXPERIMENTAL", "grant", "sha256", "lifecycle", "Traceback"):
        assert leak not in body


def test_api_models_tells_the_truth_about_each_tier(monkeypatch):
    import urllib.request

    from fastapi.testclient import TestClient

    from orca.serve import api as api_module

    class _Resp:
        def read(self):
            return json.dumps({"models": [{"name": "orca-core"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    wiring.reset_for_tests()
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=3: _Resp())
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    monkeypatch.setenv("ORNEUR_ALLOW_EXPERIMENTAL_SERVING", "1")
    monkeypatch.setattr(wiring, "installed_digests", lambda host: {"orca-core": DIGEST})
    body = TestClient(api_module.app).get("/api/models").json()
    assert body["core"]["lifecycle"] == "EXPERIMENTAL" and body["core"]["publicly_served"] is False
    assert "not qualified" in body["core"]["disclosure"].lower()
    assert body["serving_policy"]["experimental_flag_has_authorizing_effect"] is False
    wiring.reset_for_tests()
