"""
EvidenceCompiler -- turns retrieved documents/search results into typed
Evidence/EvidenceSource objects with real provenance (Phase 4 spec §16-17).
Never lets a search provider's own HTML parsing become the Evidence model
directly (spec §14) -- this is the one place raw retrieval output gets
normalized into the stable contract the rest of Truth Fabric consumes.
"""
from __future__ import annotations

import hashlib

from orca.cognitive.contracts import FreshnessLevel
from orca.truth.contracts import Evidence, EvidencePassage, EvidenceSource, SourceQuality, SourceType, _new_id, _now_iso
from orca.truth.search_provider import SearchResultMetadata

_COMMUNITY_DOMAINS = {"reddit.com", "stackoverflow.com", "stackexchange.com", "quora.com", "news.ycombinator.com"}
_OFFICIAL_DOMAIN_HINTS = ("docs.", "developer.", "api.", ".gov", "github.com")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def classify_source_quality(domain: str) -> SourceQuality:
    """
    Structured, contextual factors -- never a single global score (spec
    §32). `is_official`/`is_community` are hints a later stage (state.py,
    verification.py) weighs differently depending on WHAT is being asked,
    not a verdict on the source in isolation.
    """
    domain = domain.lower()
    is_community = any(domain.endswith(d) or domain == d for d in _COMMUNITY_DOMAINS)
    is_official = any(hint in domain for hint in _OFFICIAL_DOMAIN_HINTS)
    factors = []
    if is_official:
        factors.append("domain matches official/primary-source hints")
    if is_community:
        factors.append("domain is a community/forum platform")
    return SourceQuality(is_primary=is_official, is_official=is_official, is_community=is_community, domain=domain, factors=factors)


def evidence_from_document_chunk(chunk: dict, session_id: str) -> tuple[Evidence, EvidenceSource]:
    """Normalizes an existing DocStore chunk (dict shape from
    orca/docs/store.py) into typed Evidence/EvidenceSource -- the
    UPLOADED_DOCUMENT path. Reuses the existing chunk shape rather than
    requiring DocStore to change."""
    text = chunk.get("text", "")
    filename = chunk.get("filename", "?")
    source_id = _new_id("src")
    source = EvidenceSource(
        source_id=source_id,
        identity=f"session:{session_id}/{filename}",
        source_type=SourceType.UPLOADED_DOCUMENT,
        domain="",
        # A document the user directly uploaded to this session is a
        # first-party source for claims about its own content -- distinct
        # from secondhand web reporting -- so it counts as primary
        # (never "official", which is reserved for institutional/regulator
        # sources per classify_source_quality). Without this, authority
        # checks for STRICT/AUDIT_GRADE evidence (see orca/truth/state.py)
        # would always fail against the user's own uploaded documents.
        quality=SourceQuality(is_primary=True, factors=["user-uploaded document"]),
        content_hash=_content_hash(text),
    )
    evidence = Evidence(
        evidence_id=_new_id("ev"),
        source_id=source_id,
        document_id=filename,
        passage=EvidencePassage(text=text, location=f"chunk#{chunk.get('chunk_idx', 0)}"),
        content_hash=_content_hash(text),
        freshness=FreshnessLevel.STATIC,
    )
    return evidence, source


def evidence_from_search_result(result: SearchResultMetadata) -> tuple[Evidence, EvidenceSource]:
    """The WEB path -- from a SearchProvider result's snippet only (no
    full-page fetch). See truth_fabric.py for the full-fetch variant that
    additionally runs fetch.py's sanitizer."""
    source_id = _new_id("src")
    quality = classify_source_quality(result.domain)
    source_type = SourceType.WEB_COMMUNITY if quality.is_community else (
        SourceType.WEB_PRIMARY if quality.is_official else SourceType.WEB_SECONDARY
    )
    source = EvidenceSource(
        source_id=source_id, identity=result.url, source_type=source_type,
        domain=result.domain, quality=quality, content_hash=_content_hash(result.snippet),
    )
    evidence = Evidence(
        evidence_id=_new_id("ev"), source_id=source_id, document_id=result.url,
        passage=EvidencePassage(text=result.snippet, location="search_snippet"),
        content_hash=_content_hash(result.snippet),
        freshness=FreshnessLevel.CURRENT,   # a live search result is, by construction, freshly retrieved
        origin_metadata={"title": result.title},
    )
    return evidence, source


def evidence_from_fetched_passage(url: str, domain: str, passage_text: str, location: str) -> tuple[Evidence, EvidenceSource]:
    """The full-page-fetch path (Deep Search, RAG_5_RESEARCH) -- distinct
    from evidence_from_search_result since it carries a real fetched
    passage, not just a search snippet."""
    source_id = _new_id("src")
    quality = classify_source_quality(domain)
    source_type = SourceType.WEB_COMMUNITY if quality.is_community else (
        SourceType.WEB_PRIMARY if quality.is_official else SourceType.WEB_SECONDARY
    )
    source = EvidenceSource(source_id=source_id, identity=url, source_type=source_type, domain=domain, quality=quality)
    evidence = Evidence(
        evidence_id=_new_id("ev"), source_id=source_id, document_id=url,
        passage=EvidencePassage(text=passage_text, location=location),
        content_hash=_content_hash(passage_text),
        freshness=FreshnessLevel.CURRENT,
    )
    return evidence, source
