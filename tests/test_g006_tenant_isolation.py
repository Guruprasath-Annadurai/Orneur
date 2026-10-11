"""G-006 -- adversarial multi-user / multi-tenant isolation tests.

Every test drives the REAL FastAPI app through ``TestClient`` with synthetic
users in an isolated ORNEUR home (the ``isolated_home`` fixture); nothing
touches a real account, model, key or network. Each test is named for the
sprint-order category it covers and asserts the *secure* behaviour, so a
failure on an unfixed tree is genuine exploit evidence
(``scripts/security/g006_repro.py`` prints the before/after table).

Categories with no subsystem to attack are recorded in
``docs/orneur/status/G006_TENANT_ISOLATION_REPORT.md`` as NOT_IMPLEMENTED,
never as secure.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correcthorsebatterystaple"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _signup(client: TestClient, **extra) -> tuple[str, str]:
    """Create a synthetic user with the product's own store + token issuer.

    Account creation through ``/api/auth/signup`` is rate limited to 5 per
    hour per IP (a good control), so only the escalation test below uses the
    real route; every other identity goes through the same ``create_user``
    and ``_make_response`` the route itself calls.
    """
    from orca.auth.routes import _make_response
    from orca.auth.store import create_user

    email = f"g006-{uuid.uuid4().hex[:12]}@example.com"
    user = create_user(email, PASSWORD, "Synthetic")
    return _make_response(user)["token"], user.id


def _signup_via_route(client: TestClient, **extra) -> tuple[str, str]:
    email = f"g006-{uuid.uuid4().hex[:12]}@example.com"
    resp = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "name": "Synthetic", **extra})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["token"], data["user"]["id"]


@pytest.fixture
def client(isolated_home, tmp_path, monkeypatch):
    """The real app, with the auth DB from ``isolated_home`` and every
    path-by-value constant the session flows touch redirected to this test's
    own directory (modules that did ``from orca.config import X`` keep the
    first test's now-deleted path otherwise)."""
    import orca.brain.knowledge_graph as kg
    import orca.brain.memory as mem
    import orca.docs.store as docs
    from orca.serve import api

    root = tmp_path / "orneur"
    for sub in ("memory", "cache", "docs", "knowledge"):
        (root / sub).mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(mem, "MEMORY_DIR", root / "memory")
    monkeypatch.setattr(mem, "CACHE_DIR", root / "cache")
    monkeypatch.setattr(docs, "DOCS_DIR", root / "docs")
    monkeypatch.setattr(docs, "_REGISTRY_FILE", root / "docs" / "registry.json")
    monkeypatch.setattr(kg, "KNOWLEDGE_DIR", root / "knowledge")
    monkeypatch.setattr(api, "_TITLES_PATH", root / "session_titles.json")
    monkeypatch.setattr(api, "_session_titles", {})
    monkeypatch.setattr(api, "_sessions", {})

    c = TestClient(api.app)
    c.storage = root  # type: ignore[attr-defined]
    # The first account on a fresh install is bootstrapped as owner by design
    # (orca/auth/store.py::create_user); burn it so every test identity is a
    # normal 'member' and any elevated access seen below is a real escalation.
    _signup(c)
    from orca.auth import apikeys

    apikeys._ensure_table()  # normally created at import; isolated_home swaps the DB under it
    return c


def _own_session(client: TestClient, token: str, fact: str = "private-fact", sid: str | None = None) -> str:
    """Create a session the way the product does: an authenticated request
    naming a fresh session id records the caller as its owner."""
    sid = sid or str(uuid.uuid4())
    r = client.post("/api/remember", json={"session_id": sid, "fact": fact}, headers=_hdr(token))
    assert r.status_code == 200, r.text
    return sid


# --------------------------------------------------------------------------
# 1. Cross-user conversation listing / titles
# --------------------------------------------------------------------------

def test_01_session_listing_never_discloses_other_users_sessions(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid_a = _own_session(client, ta)
    assert client.post("/api/session/save", json={"message": "x", "session_id": sid_a}, headers=_hdr(ta)).status_code == 200
    assert client.patch(f"/api/session/{sid_a}/title", json={"title": "A-CONFIDENTIAL-TITLE"}, headers=_hdr(ta)).status_code == 200

    for who, headers in (("user B", _hdr(tb)), ("anonymous", {})):
        body = client.get("/api/sessions", headers=headers).text
        assert sid_a not in body, f"{who} can enumerate user A's session id"
        assert "A-CONFIDENTIAL-TITLE" not in body, f"{who} can read user A's conversation title"

    own = client.get("/api/sessions", headers=_hdr(ta)).json()["sessions"]
    assert [s["id"] for s in own] == [sid_a]
    assert own[0]["title"] == "A-CONFIDENTIAL-TITLE"


# --------------------------------------------------------------------------
# 2. Cross-user modification / deletion
# --------------------------------------------------------------------------

def test_02_user_b_cannot_retitle_or_save_user_a_session(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid_a = _own_session(client, ta)
    client.patch(f"/api/session/{sid_a}/title", json={"title": "original"}, headers=_hdr(ta))

    for headers in (_hdr(tb), {}):
        r = client.patch(f"/api/session/{sid_a}/title", json={"title": "<img src=x onerror=alert(1)>"}, headers=headers)
        assert r.status_code in (401, 404), f"stranger rewrote A's title: {r.status_code} {r.text}"
        r = client.post("/api/session/save", json={"message": "x", "session_id": sid_a}, headers=headers)
        assert r.status_code in (401, 404), f"stranger forced a save of A's session: {r.status_code} {r.text}"

    titles = {s["id"]: s["title"] for s in client.get("/api/sessions", headers=_hdr(ta)).json()["sessions"]}
    assert titles.get(sid_a, "original") == "original"


def test_02b_title_route_does_not_create_titles_for_unknown_sessions(client):
    """An unknown id must not become a new key in the shared titles file
    (unbounded write amplification / defacement of future sessions)."""
    tb, _ = _signup(client)
    ghost = str(uuid.uuid4())
    r = client.patch(f"/api/session/{ghost}/title", json={"title": "squat"}, headers=_hdr(tb))
    assert r.status_code in (404, 422), r.text


# --------------------------------------------------------------------------
# 3. Cross-user file / attachment access (document store)
# --------------------------------------------------------------------------

class _Chunk:
    def __init__(self, text: str, idx: int):
        self.text, self.chunk_idx = text, idx

    def to_metadata(self) -> dict:
        return {"chunk_idx": self.chunk_idx, "filename": "secret.txt", "doc_id": "d1"}


def test_03_document_store_is_not_shared_through_a_colliding_session_prefix(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid_a = str(uuid.uuid4())
    from orca.docs.store import DocStore

    r = client.get("/api/docs/list", params={"session_id": sid_a}, headers=_hdr(ta))
    assert r.status_code == 200
    DocStore(sid_a).add_chunks([_Chunk("PAYROLL-SECRET-4711 quarterly figures", 0)], "d1", "secret.txt")

    attacker_sid = sid_a[:8] + "-evil-" + uuid.uuid4().hex[:6]  # same 8-char storage prefix
    r = client.get("/api/docs/list", params={"session_id": attacker_sid}, headers=_hdr(tb))
    leaked = r.status_code == 200 and r.json().get("total_chunks", 0) > 0
    assert not leaked, f"B's session shares A's document store: {r.text}"
    if r.status_code == 200:
        assert DocStore(attacker_sid).retrieve("PAYROLL-SECRET-4711") == []


def test_03b_doc_delete_cannot_cross_sessions(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid_a = str(uuid.uuid4())
    client.get("/api/docs/list", params={"session_id": sid_a}, headers=_hdr(ta))
    r = client.delete("/api/docs/d1", params={"session_id": sid_a}, headers=_hdr(tb))
    assert r.status_code == 404, r.text
    r = client.delete("/api/docs/d1", params={"session_id": sid_a})
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------
# 4. Cross-user memory and search leakage
# --------------------------------------------------------------------------

def test_04_long_term_memory_not_readable_through_a_colliding_session_prefix(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid_a = _own_session(client, ta, fact="TOP-SECRET-A merger plans")
    from orca.brain.memory import MemoryEngine

    MemoryEngine(sid_a).semantic.store_fact(f"session_{sid_a[:8]}", "A-PRIVATE-SUMMARY")

    attacker_sid = sid_a[:8] + "-" + uuid.uuid4().hex[:12]
    r = client.post("/api/memory/recall", json={"session_id": attacker_sid, "query": "TOP-SECRET-A"}, headers=_hdr(tb))
    assert "TOP-SECRET-A" not in r.text and "A-PRIVATE-SUMMARY" not in r.text, f"memory leaked via prefix collision: {r.text}"
    assert r.status_code in (404, 422)


def test_04b_remember_does_not_write_into_a_global_shared_note_blob(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    _own_session(client, ta, fact="NOTE-FROM-A")
    _own_session(client, tb, fact="NOTE-FROM-B")
    from orca.brain.memory import SemanticMemory

    blob = SemanticMemory().recall_fact("all_sessions_summary") or ""
    assert not ("NOTE-FROM-A" in blob and "NOTE-FROM-B" in blob), (
        "two users' private notes were merged into one global, unscoped blob "
        "(also survives account deletion, which only strips '[Session x]' blocks)"
    )


# --------------------------------------------------------------------------
# 5. Guessed / attacker-chosen identifiers
# --------------------------------------------------------------------------

HOSTILE_IDS = [
    "../../../escape",
    "..%2f..%2fescape",
    "a/b",
    "a\\b",
    "x" * 4096,
    "nul\x00byte",
    "",  # empty is treated as "new session" by design; must still be safe
    "ab cd ef",
]


@pytest.mark.parametrize("hostile", [h for h in HOSTILE_IDS if h], ids=lambda h: f"hostile{abs(hash(h)) % 1000}")
def test_05_hostile_session_ids_are_rejected_before_touching_storage(client, hostile):
    ta, _ = _signup(client)
    r = client.post("/api/remember", json={"session_id": hostile, "fact": "x"}, headers=_hdr(ta))
    assert r.status_code in (404, 422), f"hostile id accepted: {hostile!r} -> {r.status_code}"


def test_05b_session_id_cannot_write_json_outside_the_episode_directory(client):
    ta, _ = _signup(client)
    home = client.storage
    sid = "../../../g006_escape"
    client.post("/api/remember", json={"session_id": sid, "fact": "x"}, headers=_hdr(ta))
    client.post("/api/session/save", json={"message": "x", "session_id": sid}, headers=_hdr(ta))
    stray = [p for p in home.parent.rglob("g006_escape*")] + [p for p in home.rglob("g006_escape*")]
    assert stray == [], f"path traversal wrote outside storage: {stray}"


# --------------------------------------------------------------------------
# 6. Tenant switching and role escalation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/admin/stats", "/api/admin/audit", "/api/admin/metrics", "/api/admin/audit/verify",
])
def test_06_non_admin_roles_cannot_reach_admin_routes(client, path):
    t, _ = _signup(client)
    assert client.get(path).status_code == 401
    assert client.get(path, headers=_hdr(t)).status_code == 403  # default role is 'member'


def test_06b_signup_ignores_client_supplied_role_tier_and_ids(client):
    t, uid = _signup_via_route(client, role="owner", tier="enterprise", id="00000000-attacker", verified=True)
    me = client.get("/api/auth/me", headers=_hdr(t)).json()
    user = me.get("user", me)
    assert user["role"] != "owner" and user["id"] == uid
    assert user.get("tier", "free") != "enterprise"
    assert client.get("/api/admin/stats", headers=_hdr(t)).status_code == 403


def test_06c_admin_cannot_escalate_to_owner_or_demote_the_owner(client):
    from orca.auth.store import set_user_role

    t_admin, admin_id = _signup(client)
    t_owner, owner_id = _signup(client)
    t_member, member_id = _signup(client)
    set_user_role(admin_id, "admin")
    set_user_role(owner_id, "owner")

    def role_of(token):
        me = client.get("/api/auth/me", headers=_hdr(token)).json()
        return me["user"]["role"]

    r = client.patch(f"/api/auth/admin/users/{admin_id}/role", json={"role": "owner"}, headers=_hdr(t_admin))
    assert r.status_code == 403 and role_of(t_admin) == "admin", "admin promoted themselves to owner"
    r = client.patch(f"/api/auth/admin/users/{owner_id}/role", json={"role": "viewer"}, headers=_hdr(t_admin))
    assert r.status_code == 403 and role_of(t_owner) == "owner", "admin demoted the owner"
    r = client.patch(f"/api/auth/admin/users/{member_id}/role", json={"role": "admin"}, headers=_hdr(t_admin))
    assert r.status_code == 403 and role_of(t_member) == "member", "admin minted a peer admin"
    # legitimate delegation still works: admin may manage ranks below their own
    r = client.patch(f"/api/auth/admin/users/{member_id}/role", json={"role": "viewer"}, headers=_hdr(t_admin))
    assert r.status_code == 200 and role_of(t_member) == "viewer"
    # the owner can still do everything
    r = client.patch(f"/api/auth/admin/users/{member_id}/role", json={"role": "admin"}, headers=_hdr(t_owner))
    assert r.status_code == 200


# --------------------------------------------------------------------------
# 7. Session invalidation and replay
# --------------------------------------------------------------------------

def test_07_password_change_invalidates_previously_issued_tokens(client):
    t, _ = _signup(client)
    email = client.get("/api/auth/me", headers=_hdr(t)).json()
    email = (email.get("user") or email)["email"]
    r = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "anotherlongpassword"}, headers=_hdr(t))
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=_hdr(t)).status_code == 401, "stolen token still valid after password change"
    fresh = client.post("/api/auth/login", json={"email": email, "password": "anotherlongpassword"})
    assert fresh.status_code == 200, fresh.text
    assert client.get("/api/auth/me", headers=_hdr(fresh.json()["token"])).status_code == 200


def test_07b_password_reset_token_is_single_use(client):
    t, uid = _signup(client)
    email = client.get("/api/auth/me", headers=_hdr(t)).json()
    email = (email.get("user") or email)["email"]
    from orca.auth.tokens import make_reset_token

    reset = make_reset_token(uid, email)
    assert client.post("/api/auth/reset-password", json={"token": reset, "password": "firstnewpassword"}).status_code == 200
    replay = client.post("/api/auth/reset-password", json={"token": reset, "password": "attackerchosenpw"})
    assert replay.status_code == 400, "reset link replayed to take the account over again"
    assert client.get("/api/auth/me", headers=_hdr(t)).status_code == 401


def test_07c_tampered_and_foreign_tokens_are_rejected(client):
    ta, _ = _signup(client)
    head, body, sig = ta.rsplit(".", 2) if ta.count(".") == 2 else (ta, "", "")
    for bad in (ta[:-2] + ("AA" if not ta.endswith("AA") else "BB"), "", "athr_nonsense", "Bearer x"):
        assert client.get("/api/auth/me", headers=_hdr(bad) if bad else {}).status_code == 401


@pytest.mark.parametrize("kind", ["2fa_pending", "reset", "verify"])
def test_07e_non_session_tokens_are_not_accepted_as_a_session(client, monkeypatch, kind):
    """With AUTH_SECRET configured (every real deployment) the 2FA-pending,
    reset and email-verification tokens are signed with the same key as a
    session and carry the same ``sub``. Accepting one as a bearer token would
    let a password-only attacker skip the TOTP step."""
    import orca.auth.tokens as tokens

    secret = "production-like-secret-0123456789"
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", secret)          # the secret now follows the environment (orca/auth/secret.py), no module-level freeze
    from orca.auth import secret as _secret_mod
    _secret_mod._reset_cache_for_tests()
    ta, uid = _signup(client)
    email = client.get("/api/auth/me", headers=_hdr(ta)).json()["user"]["email"]
    maker = {"2fa_pending": tokens.make_2fa_pending_token, "reset": tokens.make_reset_token, "verify": tokens.make_verification_token}[kind]
    assert client.get("/api/auth/me", headers=_hdr(maker(uid, email))).status_code == 401
    assert client.get("/api/auth/me", headers=_hdr(ta)).status_code == 200  # real session still fine


def test_07f_default_signing_secret_is_refused_on_a_public_edge(monkeypatch):
    """The default AUTH_SECRET is a public constant in the source; on a public
    edge it must not be usable to sign or to verify (forged owner tokens)."""
    import base64
    import hashlib
    import hmac
    import json

    from orca.auth import crypto

    monkeypatch.delenv("ORNEUR_AUTH_SECRET", raising=False)
    monkeypatch.delenv("ORCA_AUTH_SECRET", raising=False)
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    body = base64.urlsafe_b64encode(json.dumps({"sub": "victim", "exp": 4102444800}, separators=(",", ":")).encode()).rstrip(b"=").decode()
    forged = body + "." + hmac.new(b"orneur-auth-dev-secret-CHANGE-THIS-IN-PRODUCTION", body.encode(), hashlib.sha256).hexdigest()
    assert crypto.verify_token(forged) is None, "token forged with the public default secret was accepted"
    with pytest.raises(RuntimeError):
        crypto.create_token({"sub": "x"})
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "0")  # private/dev keeps working
    assert crypto.verify_token(crypto.create_token({"sub": "x"})) is not None


def test_07d_revoked_api_key_stops_working_and_keys_are_user_scoped(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    made = client.post("/api/auth/apikeys", json={"name": "k"}, headers=_hdr(ta))
    if made.status_code != 200:
        pytest.skip(f"api-key creation not available for default tier: {made.status_code}")
    body = made.json()
    key, key_id = body["key"], body["key_id"]
    sid_a = _own_session(client, ta)
    assert client.get(f"/api/session/{sid_a}/export", headers=_hdr(key)).status_code == 200
    assert client.get(f"/api/session/{sid_a}/export", headers=_hdr(tb)).status_code == 404
    assert client.delete(f"/api/auth/apikeys/{key_id}", headers=_hdr(tb)).status_code in (403, 404), "B revoked A's key"
    assert client.delete(f"/api/auth/apikeys/{key_id}", headers=_hdr(ta)).status_code == 200
    assert client.get(f"/api/session/{sid_a}/export", headers=_hdr(key)).status_code == 404


# --------------------------------------------------------------------------
# 8. Streaming / chat reaching the wrong user's session
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route,payload", [
    ("/api/stream", {"message": "hi"}),
    ("/api/chat", {"message": "hi"}),
    ("/api/ultra", {"task": "hi"}),
    ("/api/memory/recall", {"query": "private-fact"}),
])
def test_08_streaming_and_chat_never_serve_or_touch_another_users_session(client, route, payload):
    """No model is available in this harness, so a bare "got an error" proves
    nothing. What must hold: the stranger's response carries none of A's data
    and A's live session object is neither touched nor re-bound."""
    from orca.serve import api

    ta, _ = _signup(client)
    tb, uid_b = _signup(client)
    sid_a = _own_session(client, ta, fact="private-fact-A")
    sess_a = api._sessions[sid_a]
    stamp = sess_a.last_active
    for headers in (_hdr(tb), {}):
        r = client.post(route, json={**payload, "session_id": sid_a}, headers=headers)
        assert "private-fact-A" not in r.text, f"{route} leaked A's data: {r.text[:200]}"
        assert sid_a not in r.text or r.status_code == 404
        assert sess_a.last_active == stamp, f"{route} touched A's session on behalf of a stranger"
    from orca.auth.store import get_session_owner

    assert get_session_owner(sid_a) != uid_b


def test_08b_two_users_streams_use_their_own_sessions(client):
    ta, uid_a = _signup(client)
    tb, uid_b = _signup(client)
    r1 = client.post("/api/memory/recall", json={"query": "x"}, headers=_hdr(ta))
    r2 = client.post("/api/memory/recall", json={"query": "x"}, headers=_hdr(tb))
    sa, sb = r1.json()["session_id"], r2.json()["session_id"]
    assert sa != sb
    from orca.auth.store import get_session_owner

    assert get_session_owner(sa) == uid_a and get_session_owner(sb) == uid_b


# --------------------------------------------------------------------------
# 12. Check/use race on session ownership
# --------------------------------------------------------------------------

def test_12_concurrent_first_claims_yield_exactly_one_owner(isolated_home):
    """Two workers both pass the read-only ownership check for an unowned
    session, then both record it (multi-process deployments interleave this
    way). Exactly one user may end up owning it and the loser must be denied."""
    from orca.auth import store
    from orca.serve import api

    sid = str(uuid.uuid4())
    api._check_session_ownership(sid, "user-a")
    api._check_session_ownership(sid, "user-b")  # both pass: nobody owns it yet
    store.record_user_session("user-a", sid)
    store.record_user_session("user-b", sid)
    with store.get_conn() as conn:
        owners = [r["user_id"] for r in conn.execute("SELECT user_id FROM user_sessions WHERE session_id=?", (sid,)).fetchall()]
    assert len(owners) == 1, f"session has multiple owners: {owners}"


def test_12b_threaded_claims_never_both_succeed(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid = str(uuid.uuid4())
    results: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def go(name, token):
        barrier.wait()
        results[name] = client.post("/api/remember", json={"session_id": sid, "fact": name}, headers=_hdr(token)).status_code

    threads = [threading.Thread(target=go, args=("a", ta)), threading.Thread(target=go, args=("b", tb))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results.values()) == [200, 404], results


# --------------------------------------------------------------------------
# 9 / 10. Background jobs and shared caches: tripwires, not "secure" claims
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent


def test_09_no_serving_route_enqueues_user_work_in_a_background_queue():
    """NOT_IMPLEMENTED: ``LensJobQueue`` jobs carry no user identity and no
    serving code uses the queue today. If a route starts using it, this test
    fails so the per-job owner/authority design is reviewed first."""
    users = [
        p for p in (REPO / "orca").rglob("*.py")
        if "orca/lens/" not in p.as_posix() and ("lens.queue" in p.read_text() or "LensJobQueue" in p.read_text())
    ]
    assert users == [], f"background queue is now used by {users}: add per-job owner binding + tests first"


def test_10_disk_caches_are_an_audited_closed_set():
    """Every diskcache site must be reviewed for tenant-scoped keys. Known:
    lens queue (unused, see test_09) and semantic memory (keys are
    ``fact:session_<prefix>``, protected by the storage-prefix claim above)."""
    sites = sorted(
        p.relative_to(REPO).as_posix() for p in (REPO / "orca").rglob("*.py")
        if p.name != "safe_cache.py" and ("diskcache.Cache(" in p.read_text() or "open_cache(" in p.read_text())
    )
    assert sites == ["orca/brain/memory.py", "orca/lens/queue.py"], f"new shared cache site(s) need a tenant-key review: {sites}"


# --------------------------------------------------------------------------
# 11. Tool invocation authority -- KNOWN, UNFIXED (G-020, needs a product decision)
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="G-020: agent `shell` tool reads any path the server OS user can read; path confinement was explicitly left undone (orca/tools/code.py docstring)")
def test_11a_agent_shell_cannot_read_outside_the_workspace(tmp_path):
    from orca.tools.code import run_shell

    secret = tmp_path / "other_tenant_data.txt"
    secret.write_text("OTHER-TENANT-SECRET")
    out = run_shell(f"cat {secret}")
    assert "OTHER-TENANT-SECRET" not in out.stdout


@pytest.mark.xfail(strict=True, reason="G-020: agent file tools use ONE server-wide workspace; tools carry no user/session identity")
def test_11b_agent_file_tools_are_not_shared_between_users(tmp_path, monkeypatch):
    import orca.tools as tools

    monkeypatch.setattr(tools, "WORKSPACE_DIR", tmp_path)
    reg_user_a, reg_user_b = tools.build_registry(), tools.build_registry()
    reg_user_a.call("write_file", {"path": "notes.txt", "content": "USER-A-PRIVATE"})
    assert "USER-A-PRIVATE" not in reg_user_b.call("read_file", {"path": "notes.txt"})


# --------------------------------------------------------------------------
# Subsystems with nothing to attack: recorded, not asserted secure
# --------------------------------------------------------------------------

def test_not_implemented_categories_are_documented():
    report = Path(__file__).resolve().parent.parent / "docs/orneur/status/G006_TENANT_ISOLATION_REPORT.md"
    text = report.read_text()
    for category in ("background jobs", "tool invocations", "shared cache keys"):
        assert category in text.lower(), f"category not recorded in the report: {category}"
    assert "NOT_IMPLEMENTED" in text
