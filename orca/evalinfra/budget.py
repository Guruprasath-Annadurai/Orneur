"""Cost accounting + quota refusal: a hash-chained budget ledger with a HARD cap that refuses (raises BudgetExceeded) BEFORE an operation that would exceed it.

  * Default cap is 0: with nothing configured every operation -- even a zero-cost one -- is refused.
  * A contingency fraction of the cap is held back: ordinary operations may use cap*(1-contingency); the remainder is only reachable with an explicit
    `use_contingency=True` plus a written reason, and the HARD cap is never exceedable by any path.
  * Money is exact: integer micro-dollars (Decimal rounding UP), NaN/inf/negative/bool refused.
  * State is derived by replaying the chain (tamper-evident, persistent). An actual cost above its reservation (an overrun that already happened)
    LOCKS the ledger: no further reservation until a human resets via a new, authorization-referenced configuration entry.

This module does not spend, authorize or measure anything; it only refuses. Raising the cap is a founder act (register row AUTH-1 / FINAL-2): `configure`
therefore requires an `authorization_ref` string for any non-zero cap and records it.
"""
from __future__ import annotations

from decimal import ROUND_UP, Decimal, InvalidOperation

from orca.evalinfra.chain import ChainLog
from orca.evalinfra.errors import BudgetExceeded, SchemaViolation

KINDS = ("BUDGET_CONFIG", "BUDGET_RESERVE", "BUDGET_COMMIT", "BUDGET_RELEASE")
MICRO = Decimal("0.000001")


def to_micro(x) -> int:
    if isinstance(x, bool) or x is None:
        raise SchemaViolation("BAD_AMOUNT", "amount must be a number")
    try:
        d = Decimal(str(x))
    except InvalidOperation:
        raise SchemaViolation("BAD_AMOUNT", "not a number") from None
    if not d.is_finite() or d < 0:
        raise SchemaViolation("BAD_AMOUNT", "amount must be finite and non-negative")
    return int((d.quantize(MICRO, rounding=ROUND_UP) / MICRO).to_integral_value())


class BudgetLedger:
    def __init__(self, path):
        self._log = ChainLog(path, allowed_kinds=KINDS)

    # -- state ---------------------------------------------------------------------------------------------------------------------
    def _replay(self) -> dict:
        st = {"cap": 0, "contingency_ppm": 0, "committed": 0, "open": {}, "ops": set(), "locked": False, "configured": False, "refs": []}
        for e in self._log.entries():
            p, k = e["payload"], e["kind"]
            if k == "BUDGET_CONFIG":
                st.update(cap=p["cap_micro"], contingency_ppm=p["contingency_ppm"], configured=True, locked=False)
                st["refs"].append(p["authorization_ref"])
            elif k == "BUDGET_RESERVE":
                st["open"][p["op_id"]] = p["micro"]
                st["ops"].add(p["op_id"])
            elif k == "BUDGET_COMMIT":
                st["open"].pop(p["op_id"], None)
                st["committed"] += p["actual_micro"]
                if p["actual_micro"] > p["reserved_micro"]:
                    st["locked"] = True
            elif k == "BUDGET_RELEASE":
                st["open"].pop(p["op_id"], None)
        return st

    def state(self) -> dict:
        s = self._replay()
        reserved = sum(s["open"].values())
        normal_cap = s["cap"] - s["cap"] * s["contingency_ppm"] // 1_000_000
        return {"hard_cap_micro": s["cap"], "ordinary_cap_micro": normal_cap, "contingency_micro": s["cap"] - normal_cap, "committed_micro": s["committed"],
                "reserved_open_micro": reserved, "remaining_micro": s["cap"] - s["committed"] - reserved, "locked": s["locked"], "configured": s["configured"]}

    # -- configuration -------------------------------------------------------------------------------------------------------------
    def configure(self, cap_usd, contingency_fraction: float = 0.10, *, authorization_ref: str = "") -> None:
        cap = to_micro(cap_usd)
        if not (isinstance(contingency_fraction, (int, float)) and not isinstance(contingency_fraction, bool) and 0.0 <= contingency_fraction < 1.0):
            raise SchemaViolation("BAD_CONTINGENCY", "contingency fraction must be in [0, 1)")
        if cap > 0 and not (isinstance(authorization_ref, str) and len(authorization_ref) >= 8):
            raise SchemaViolation("AUTHORIZATION_REF_REQUIRED", "a non-zero cap needs the identifier/hash of the founder budget record that authorizes it")
        s = self._replay()
        if cap > 0 and authorization_ref in s["refs"]:
            raise SchemaViolation("AUTHORIZATION_REF_REUSED", "each cap change must cite a different authorization record")
        self._log.append("BUDGET_CONFIG", {"cap_micro": cap, "contingency_ppm": int(round(contingency_fraction * 1_000_000)), "authorization_ref": authorization_ref})

    # -- operations ----------------------------------------------------------------------------------------------------------------
    def reserve(self, op_id: str, estimated_cost_usd, *, use_contingency: bool = False, reason: str = "") -> dict:
        """Refuses (raises) BEFORE the operation if it could exceed the cap. Returns the reservation record on success."""
        if not (isinstance(op_id, str) and op_id):
            raise SchemaViolation("BAD_OP_ID")
        micro = to_micro(estimated_cost_usd)
        s = self._replay()
        if s["cap"] == 0:
            raise BudgetExceeded("CAP_ZERO", "no budget is configured (default cap 0): every operation is refused")
        if s["locked"]:
            raise BudgetExceeded("LEDGER_LOCKED", "a previous overrun locked the ledger; a new authorized configuration is required")
        if op_id in s["ops"]:
            raise BudgetExceeded("DUPLICATE_OPERATION", op_id)
        if use_contingency and len((reason or "").strip()) < 10:
            raise BudgetExceeded("CONTINGENCY_REASON_REQUIRED", "contingency draws need a written reason (>= 10 characters)")
        spent = s["committed"] + sum(s["open"].values())
        normal_cap = s["cap"] - s["cap"] * s["contingency_ppm"] // 1_000_000
        limit = s["cap"] if use_contingency else normal_cap
        if spent + micro > limit:
            raise BudgetExceeded("WOULD_EXCEED_CAP" if use_contingency else "WOULD_EXCEED_ORDINARY_CAP",
                                 f"spent+reserved {spent} + request {micro} micro-USD > limit {limit}")
        e = self._log.append("BUDGET_RESERVE", {"op_id": op_id, "micro": micro, "contingency": bool(use_contingency), "reason": reason})
        return e["payload"]

    def commit(self, op_id: str, actual_cost_usd) -> dict:
        actual = to_micro(actual_cost_usd)
        s = self._replay()
        if op_id not in s["open"]:
            raise BudgetExceeded("NO_OPEN_RESERVATION", op_id)
        reserved = s["open"][op_id]
        e = self._log.append("BUDGET_COMMIT", {"op_id": op_id, "reserved_micro": reserved, "actual_micro": actual, "overrun": actual > reserved})
        return e["payload"]

    def release(self, op_id: str) -> None:
        if op_id not in self._replay()["open"]:
            raise BudgetExceeded("NO_OPEN_RESERVATION", op_id)
        self._log.append("BUDGET_RELEASE", {"op_id": op_id})
