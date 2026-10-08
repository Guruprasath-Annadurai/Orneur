#!/usr/bin/env bash
# REVIEW_TOOL (read-only). Mechanical exact-SHA gate checks for an eventual IMP-2/3/4 candidate.
# Usage: audit_gate_checks.sh <BASE_SHA> <CANDIDATE_SHA> [repo_dir]
# It never writes to the repository and never checks out or modifies any branch. It prints PASS/FAIL lines and a summary.
# A PASS here is NECESSARY, never SUFFICIENT: the hostile review, vectors and adversarial tests are separate gates.
set -u
BASE="${1:?base sha}"; CAND="${2:?candidate sha}"; REPO="${3:-.}"
cd "$REPO" || exit 2
fail=0
say() { printf '%s\n' "$*"; }
ok()  { say "PASS  $*"; }
bad() { say "FAIL  $*"; fail=$((fail+1)); }
R=docs/orneur/phase-21/rse
M3=$R/v1.2/RSE_ARCH_1_2_FREEZE_MANIFEST_V3.txt
git cat-file -e "$CAND^{commit}" 2>/dev/null && ok "candidate object exists ($CAND)" || { bad "candidate object missing"; exit 1; }
git merge-base --is-ancestor "$BASE" "$CAND" && ok "candidate descends from base" || bad "candidate does NOT descend from base"
say "INFO  commits ahead of base: $(git rev-list --count "$BASE..$CAND")"
say "INFO  authors: $(git log --format='%an' "$BASE..$CAND" | sort -u | tr '\n' ';')"
# 1 frozen / governance / authorization / workflow paths
touched=$(git diff --name-only "$BASE" "$CAND" | grep -E "^($R/(RSE_|v1\.1/|v1\.2/(RSE_ARCH|RSE12_0|clarification-1))|docs/orneur/authorization/|\.github/)" || true)
[ -z "$touched" ] && ok "no frozen architecture / authorization / workflow file modified" || { bad "protected paths modified:"; printf '   %s\n' $touched; }
prot=$(git diff --name-only "$BASE" "$CAND" | grep -i -E "benchmark|holdout|protected|known_leakage" || true)
[ -z "$prot" ] && ok "no protected-benchmark path touched" || { bad "benchmark-like paths touched:"; printf '   %s\n' $prot; }
# 2 Manifest V3 identity (candidate tree)
want=7b19e6ca6b60f6209a35036690c9d05dc5352dfb6219ed17887b63343e72e703
got=$(git show "$CAND:$M3" 2>/dev/null | sha256sum | cut -c1-64)
[ "$got" = "$want" ] && ok "Manifest V3 digest unchanged" || bad "Manifest V3 digest differs ($got)"
n=0; mism=0
while IFS= read -r line; do
  h=${line%%  *}; p=$(printf '%s' "$line" | awk -F'  ' '{print $6}')
  a=$(git show "$CAND:$R/$p" 2>/dev/null | sha256sum | cut -c1-64); n=$((n+1)); [ "$a" = "$h" ] || { mism=$((mism+1)); say "   MISMATCH $p"; }
done < <(git show "$CAND:$M3" | awk 'NR>4')
[ "$mism" -eq 0 ] && ok "Manifest V3: $n entries verify" || bad "Manifest V3: $mism of $n entries mismatch"
# 3 authorization lock files
for f in CORPUS_GENERATION_AUTHORIZATION MODEL_EVAL_AUTHORIZATION QUALIFICATION_RUNNER_REGISTRY; do
  if [ -n "$(git diff --name-only "$BASE" "$CAND" -- docs/orneur/authorization/$f.json)" ]; then bad "$f.json changed"; else ok "$f.json unchanged"; fi
done
# 4 privacy / secret patterns in added lines only
leaks=$(git diff "$BASE" "$CAND" | grep -E '^\+' | grep -v '^+++' | grep -n -i -E "/Users/[a-z]|/home/[a-z]|BEGIN (RSA|EC|OPENSSH|PRIVATE)|ghp_[A-Za-z0-9]|AKIA[A-Z0-9]{8}|sk-[A-Za-z0-9]{16}|xox[bp]-|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}" | head -5 || true)
[ -z "$leaks" ] && ok "no secret/private-path/IP patterns in added lines" || { bad "possible leak patterns:"; printf '   %s\n' "$leaks"; }
# 5 CI/test requirement drift
wf=$(git diff --name-only "$BASE" "$CAND" -- .github pyproject.toml tests/conftest.py pytest.ini setup.cfg 2>/dev/null || true)
[ -z "$wf" ] && ok "no workflow / test-config change" || say "REVIEW  config files changed (inspect by hand): $wf"
removed_tests=$(git diff "$BASE" "$CAND" -- tests | grep -E '^-\s*def test_' | wc -l | tr -d ' ')
[ "$removed_tests" = "0" ] && ok "no test function removed" || bad "$removed_tests test function(s) removed or renamed"
skips=$(git diff "$BASE" "$CAND" -- tests | grep -E '^\+.*(pytest\.mark\.skip|pytest\.skip|xfail|importorskip)' | wc -l | tr -d ' ')
[ "$skips" = "0" ] && ok "no skip/xfail added in tests" || say "REVIEW  $skips added skip/xfail/importorskip lines"
# 6 exceptions swallowing in new security code
swallow=$(git diff "$BASE" "$CAND" -- orca | grep -E '^\+' | grep -n -E "except( Exception| BaseException)?:\s*(pass|return None|continue)" | head -5 || true)
[ -z "$swallow" ] && ok "no except-pass/return-None in added production code" || { say "REVIEW  swallow-style handlers:"; printf '   %s\n' "$swallow"; }
say "INFO  changed files:"; git diff --name-status "$BASE" "$CAND" | sed 's/^/   /'
say "SUMMARY  failures=$fail (mechanical gate only; NOT an acceptance verdict)"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
