"""
Phase 15.7 -- Idea -> Product Contract compilation (spec sections
10-11, 13, 16).

The DETERMINISTIC core (`compile_idea()`) never requires a live LLM:
it builds a ProductContract skeleton, records explicitly-supplied
facts, and identifies a FIXED set of commonly-material-but-often-
unaddressed product dimensions (payment provider, country, tax
system, age restriction, delivery radius, identity provider, cloud
vendor, retention policy, production traffic scale) as UNKNOWN facts
whenever the raw idea text doesn't mention them -- this is the
concrete mechanism behind spec section 11's central invariant: "Build
me a food-delivery app" must never silently produce VERIFIED facts
about payment providers, tax systems, etc.

A `ModelProvider` (spec section 10, reusing `orca.mission.providers`
from Phase 15.6) MAY optionally assist by proposing candidate
requirement text. Its output is NEVER trusted directly:
  - malformed/unparseable provider output is silently ignored (the
    contract still compiles successfully without it);
  - a provider failure (ProviderTimeout/Cancelled/Failure) is caught
    and never corrupts the contract already built;
  - anything the provider proposes is recorded with
    provenance=INFERRED_ASSUMPTION and state=UNVERIFIED -- there is
    no code path in this module that lets a provider's own output
    reach FactState.VERIFIED or RequirementStatus.VERIFIED.

Spec section 16 (platform security invariants): when compiling a
product idea that targets ORNEUR's OWN platform
(`target_is_orneur_platform=True`), an idea containing an explicit
attempt to weaken/skip ORNEUR's own authority/authorization mechanism
is REFUSED (raises IdeaCompilerError) rather than silently compiled
into a requirement that would contradict Phase 15.5's authority
invariants. For an ordinary product's OWN internal auth model (the
default, `target_is_orneur_platform=False`), the same phrases are a
legitimate product-level design decision, not a platform invariant
violation -- this module does not second-guess a product's own
authorization design.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from orca.mission.acceptance_criteria import CriterionError, VerificationMethod, register_criterion
from orca.mission.assumption_model import FactState, record_fact
from orca.mission.product_contract import (
    Actor,
    ContractError,
    ProductContract,
    TargetPlatform,
    UserJourney,
    register_contract,
)
from orca.mission.provenance import SourceProvenance
from orca.mission.providers import ModelProvider, ProviderError
from orca.mission.requirements import Requirement, RequirementError, register as register_requirement


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IdeaCompilerError(Exception):
    pass


#: Fixed, deterministic set of commonly-material product dimensions.
#: Each maps to keyword substrings (case-insensitive) whose ABSENCE
#: from the raw idea text causes an UNKNOWN Fact to be recorded --
#: never silently assumed, never silently omitted.
KNOWN_UNKNOWN_CATEGORIES: dict[str, tuple[str, ...]] = {
    "payment_provider": ("payment", "stripe", "paypal", "billing"),
    "country": ("country", "jurisdiction", "region"),
    "tax_system": ("tax", "vat", "gst"),
    "age_restriction": ("age restrict", "minimum age", "18+"),
    "delivery_radius": ("delivery radius", "service area", "coverage area"),
    "identity_provider": ("identity provider", "sso", "oauth", "login with"),
    "cloud_vendor": ("aws", "azure", "gcp", "cloud provider"),
    "retention_policy": ("retention", "how long we keep", "data retention"),
    "production_traffic_scale": ("concurrent users", "requests per second", "traffic volume", "scale to"),
}

#: Phrases that, when found in an idea targeting ORNEUR's own
#: platform, indicate an attempt to weaken a real Phase 15.5
#: authority/authorization invariant -- refused outright, not
#: silently compiled (spec section 16).
_PLATFORM_AUTHORITY_BYPASS_PHRASES: tuple[str, ...] = (
    "skip authorization", "disable auth", "bypass authority",
    "remove authorization", "no approval needed", "skip the authority check",
)


def check_platform_invariants(raw_idea: str, *, target_is_orneur_platform: bool) -> tuple[str, ...]:
    """Returns matched bypass-phrase warnings. Does not raise -- the
    caller (compile_idea) decides whether to refuse."""
    if not target_is_orneur_platform:
        return ()
    lowered = raw_idea.lower()
    return tuple(p for p in _PLATFORM_AUTHORITY_BYPASS_PHRASES if p in lowered)


def _keyword_present(keyword: str, text: str) -> bool:
    """Word-boundary substring match -- a plain `in` check would let
    "vat" false-match inside "deactivate", silently marking
    tax_system as 'mentioned' when it wasn't (a real bug found via
    this module's own test suite, see PHASE15_EVIDENCE.md's Phase
    15.7 section). Uses lookaround rather than `\\b` so it still
    works correctly for keywords ending in a non-word character
    (e.g. "18+")."""
    pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
    return re.search(pattern, text) is not None


def compute_requirement_id(area: str, statement: str) -> str:
    """Stable under irrelevant reordering/formatting: derived purely
    from (area, normalized statement content), never from list
    position. The NAME segment is a content hash rendered as
    uppercase hex prefixed with a fixed letter (REQ-<AREA>-<NAME>-<NNN>
    requires NAME to start with a letter, per
    orca.mission.requirements' own ID pattern)."""
    normalized = " ".join(statement.strip().lower().split())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:6].upper()
    return f"REQ-{area.upper()}-H{digest}-001"


@dataclass(frozen=True)
class CompiledRequirement:
    area: str
    statement: str
    acceptance_criteria: tuple[str, ...]
    verification_method: VerificationMethod = VerificationMethod.MANUAL_REVIEW


@dataclass
class CompilationResult:
    contract: ProductContract
    fact_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    provider_warnings: tuple[str, ...] = field(default_factory=tuple)


def compile_idea(
    *,
    contract_id: str,
    product_name: str,
    raw_idea: str,
    explicit_facts: dict[str, str] | None = None,
    explicit_requirements: tuple[CompiledRequirement, ...] = (),
    actors: tuple[Actor, ...] = (),
    user_journeys: tuple[UserJourney, ...] = (),
    target_platforms: tuple[TargetPlatform, ...] = (),
    out_of_scope: tuple[str, ...] = (),
    mission_id: str | None = None,
    target_is_orneur_platform: bool = False,
    provider: ModelProvider | None = None,
) -> CompilationResult:
    """The deterministic idea -> ProductContract compiler. Works
    without `provider` entirely (spec section 10: "This phase must
    work WITHOUT requiring a live LLM")."""
    if not raw_idea.strip():
        raise IdeaCompilerError("raw_idea must not be empty.")

    bypass_hits = check_platform_invariants(raw_idea, target_is_orneur_platform=target_is_orneur_platform)
    if bypass_hits:
        raise IdeaCompilerError(
            f"Refusing to compile: idea targets ORNEUR's own platform and contains an attempt to "
            f"weaken a real authority invariant ({bypass_hits!r}). Product-level requirements cannot "
            f"override ORNEUR's own Phase 15.5 authority/authorization system."
        )

    fact_ids: list[str] = []
    explicit_facts = explicit_facts or {}
    for i, (key, value) in enumerate(sorted(explicit_facts.items())):
        fact_id = f"{contract_id}-fact-explicit-{i:03d}"
        record_fact(
            id=fact_id, contract_id=contract_id, mission_id=mission_id,
            statement=f"{key}: {value}", state=FactState.UNVERIFIED,
            provenance=SourceProvenance.OWNER_EXPLICIT,
        )
        fact_ids.append(fact_id)

    unknown_ids: list[str] = []
    lowered_idea = raw_idea.lower()
    for category, keywords in sorted(KNOWN_UNKNOWN_CATEGORIES.items()):
        if category in explicit_facts:
            continue  # explicitly addressed by the owner -- not unknown
        if any(_keyword_present(kw, lowered_idea) for kw in keywords):
            continue  # mentioned in the raw idea text -- not silently unknown
        fact_id = f"{contract_id}-unknown-{category}"
        record_fact(
            id=fact_id, contract_id=contract_id, mission_id=mission_id,
            statement=f"{category} is not specified by the product idea or owner-supplied facts.",
            state=FactState.UNKNOWN,
            provenance=SourceProvenance.INFERRED_ASSUMPTION,
        )
        unknown_ids.append(fact_id)
        fact_ids.append(fact_id)

    provider_warnings: list[str] = []
    if provider is not None:
        provider_warnings.extend(_assist_with_provider(
            provider=provider, raw_idea=raw_idea, contract_id=contract_id, mission_id=mission_id, fact_ids=fact_ids,
        ))

    requirement_ids: list[str] = []
    criterion_ids: list[str] = []
    for compiled_req in explicit_requirements:
        req_id = compute_requirement_id(compiled_req.area, compiled_req.statement)
        try:
            register_requirement(Requirement(
                id=req_id,
                source_section="Phase 15.7 idea compiler",
                statement=compiled_req.statement,
                acceptance_criteria=compiled_req.acceptance_criteria,
            ))
        except RequirementError:
            pass  # already registered -- stable ID means a repeat compile is idempotent, not an error
        requirement_ids.append(req_id)
        for j, criterion_text in enumerate(compiled_req.acceptance_criteria):
            criterion_id = f"{req_id}-ac-{j:03d}"
            try:
                register_criterion(
                    criterion_id=criterion_id, requirement_id=req_id,
                    description=criterion_text, verification_method=compiled_req.verification_method,
                )
                criterion_ids.append(criterion_id)
            except CriterionError:
                pass  # already registered -- idempotent re-compile

    contract = ProductContract(
        contract_id=contract_id,
        version=1,
        product_name=product_name,
        product_purpose=raw_idea,
        source_input=raw_idea,
        created_at=_now_iso(),
        mission_id=mission_id,
        actors=actors,
        user_journeys=user_journeys,
        target_platforms=target_platforms,
        out_of_scope=out_of_scope,
        assumption_ids=tuple(fid for fid in fact_ids if fid not in unknown_ids),
        unknown_ids=tuple(unknown_ids),
    )
    try:
        register_contract(contract)
    except ContractError:
        raise

    return CompilationResult(
        contract=contract, fact_ids=tuple(fact_ids), requirement_ids=tuple(requirement_ids),
        criterion_ids=tuple(criterion_ids), provider_warnings=tuple(provider_warnings),
    )


def _assist_with_provider(
    *, provider: ModelProvider, raw_idea: str, contract_id: str, mission_id: str | None, fact_ids: list[str],
) -> list[str]:
    """Calls the provider ONCE, expects a JSON object with an
    optional "candidate_facts" list of {key, value} objects. Any
    failure (provider error, malformed JSON, wrong shape) is caught
    and reported as a warning string -- NEVER raised, NEVER corrupts
    the contract already being built. Every accepted candidate is
    recorded UNVERIFIED/INFERRED_ASSUMPTION -- there is no path here
    to VERIFIED."""
    from orca.mission.providers import ProviderRequest

    warnings: list[str] = []
    try:
        response = provider.invoke(ProviderRequest(
            provider=getattr(provider, "provider_name", "unknown"),
            model=getattr(provider, "model_name", "unknown"),
            purpose="idea_compilation_assist",
            prompt=raw_idea,
        ))
    except ProviderError as e:
        warnings.append(f"provider assist failed ({e.kind.value}): {e.message}")
        return warnings

    try:
        payload = json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        warnings.append("provider output was not valid JSON -- ignored.")
        return warnings

    if not isinstance(payload, dict):
        warnings.append("provider output was not a JSON object -- ignored.")
        return warnings

    candidates = payload.get("candidate_facts")
    if not isinstance(candidates, list):
        warnings.append("provider output had no valid 'candidate_facts' list -- ignored.")
        return warnings

    for i, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or "key" not in candidate or "value" not in candidate:
            warnings.append(f"provider candidate_facts[{i}] malformed -- skipped.")
            continue
        fact_id = f"{contract_id}-fact-provider-{i:03d}"
        try:
            record_fact(
                id=fact_id, contract_id=contract_id, mission_id=mission_id,
                statement=f"{candidate['key']}: {candidate['value']} (provider-proposed)",
                state=FactState.UNVERIFIED,
                provenance=SourceProvenance.INFERRED_ASSUMPTION,
            )
            fact_ids.append(fact_id)
        except Exception:
            warnings.append(f"provider candidate_facts[{i}] could not be recorded -- skipped.")
    return warnings
