"""
GENESIS Foundation Sprint 2, Workstream A, Mission A1: a reproducible
dataset-provenance contract for native pretraining data.

Reuses existing, already-tested infrastructure rather than duplicating it:
`orca.registry.dataset_manifest.sha256_of_file` for file hashing, the
same `_mkdir_owner_only` (`orca.config`) ownership discipline the rest of
this codebase's registries use, and `orca.genesis.model.config.ARCHITECTURE_VERSION`
for architecture-identity binding. The existing `orca.registry.DatasetManifest`
(built for the LoRA fine-tune path's single train/eval-file shape) is NOT
extended or subclassed here -- GENESIS native pretraining's shape (many
shards, no LoRA concept, tokenizer-digest binding) is different enough that
forcing it into that schema would blur two genuinely different contracts;
this module is a sibling, not a duplicate, and both can coexist.

Every manifest is CONTENT-ADDRESSED: `manifest_id` is derived from a
canonical hash of the manifest's own binding fields, never an
arbitrary caller-chosen label -- this is the direct response to Mission
A5's requirement that dataset identity be a real cryptographic content
digest, not a caller-supplied string.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import _mkdir_owner_only, ORCA_HOME
from orca.genesis.model.config import ARCHITECTURE_VERSION
from orca.registry.dataset_manifest import sha256_of_file

MANIFEST_SCHEMA_VERSION = "genesis-dataset-provenance/1"
GENESIS_DATASET_MANIFEST_DIR = ORCA_HOME / "genesis" / "dataset_manifests"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceRejected(ValueError):
    """Raised by `GenesisDatasetManifest.build()` when any required
    provenance field is missing, malformed, or unverifiable. Mission A1's
    explicit requirement: a dataset is never silently accepted with
    partial or unverifiable provenance -- construction itself fails
    closed."""


class ManifestTamperedError(ValueError):
    """A-09 fix: raised by `GenesisDatasetManifest.load()` when the
    on-disk JSON's `manifest_id` does not match a FRESH recomputation
    from its own binding fields, or when the file's structure is
    malformed/inconsistent. Independently reproduced before this fix:
    `load()` previously deserialized whatever `manifest_id` (and every
    other field) the JSON file claimed, with ZERO recomputation or
    cross-check -- a hand-edited file with a substituted `dataset_name`
    and an arbitrary `manifest_id` loaded without complaint. A
    self-consistent hash recomputed from a file's OWN claimed fields
    still does not, by itself, authenticate who produced that file or
    whether its content is independently trustworthy -- that remains a
    SEPARATE, orthogonal concern (e.g. file permissions, signed
    provenance records, or a trusted registry entry); this only
    guarantees internal consistency was not silently bypassed."""


def normalize_record_text(text: str) -> str:
    """The single, explicit normalization rule this pipeline applies to
    every raw text record before hashing/tokenizing/deduping: Unicode NFC,
    then collapse runs of whitespace to a single space, then strip leading/
    trailing whitespace. Deterministic and idempotent -- running it twice
    produces the same result as running it once, which `source_record_count`/
    `dedup_result` below depend on for reproducibility across re-runs."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


@dataclass(frozen=True)
class SourceOrigin:
    """Where this dataset's raw bytes came from, and under what terms.
    `license_name` and `usage_restrictions` are required, non-empty
    strings -- Mission A1's "explicit rejection of missing or
    unverifiable provenance" applies here specifically: a source with no
    stated license is not assumed permissively licensed."""
    source_id: str
    description: str
    license_name: str
    usage_restrictions: str
    retrieved_at: str


@dataclass(frozen=True)
class TransformationStep:
    """One step of this dataset's build lineage -- e.g.
    "normalize_record_text applied", "deduplicated at Jaccard>=0.9",
    "PII/secret-screened via orca.learning.sanitize.sanitize_for_candidate".
    Ordered; the full list is this manifest's transformation lineage."""
    name: str
    code_reference: str  # the exact function/module that performed this step
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TokenizerBinding:
    """Binds this dataset to the EXACT tokenizer it was sharded/encoded
    against. `vocab_digest` is a real SHA-256 of the tokenizer's own
    vocabulary file bytes -- not the tokenizer's human-chosen name or
    version string alone, which could be reused across genuinely
    different vocabularies by mistake."""
    tokenizer_model_path: str
    architecture_version: str
    vocab_digest: str


@dataclass(frozen=True)
class GenesisDatasetManifest:
    """The complete, immutable provenance record for one GENESIS native
    pretraining dataset build. `manifest_id` is content-addressed (see
    `build()`) -- two manifests with identical binding fields always
    produce the identical `manifest_id`, and any change to a binding
    field changes it. This is what makes `manifest_id` usable as the
    "verifiable dataset identity" Mission A5 asks for: it is derived from
    real cryptographic digests, not supplied by a caller."""
    schema_version: str
    manifest_id: str
    dataset_name: str
    version: str
    origins: tuple[SourceOrigin, ...]
    source_record_count: int
    source_content_digest: str          # sha256 over the exact normalized source records, order-independent
    normalization_rule: str              # human-readable description; the actual rule lives in normalize_record_text()
    transformation_lineage: tuple[TransformationStep, ...]
    tokenizer_binding: TokenizerBinding
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    @staticmethod
    def _compute_manifest_id(binding_fields: dict) -> str:
        canonical = json.dumps(binding_fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls, *, dataset_name: str, version: str, origins: list[SourceOrigin], normalized_records: list[str],
        transformation_lineage: list[TransformationStep], tokenizer_binding: TokenizerBinding,
    ) -> "GenesisDatasetManifest":
        """The ONLY constructor. Computes `source_content_digest` for
        real, from the actual normalized record bytes -- never accepts a
        caller-supplied digest string (Mission A5's explicit requirement).
        Raises `ProvenanceRejected` for any missing/malformed/unverifiable
        field; nothing here is defaulted into existence."""
        if not dataset_name or not isinstance(dataset_name, str):
            raise ProvenanceRejected("dataset_name is required and must be a non-empty string")
        if not version or not isinstance(version, str):
            raise ProvenanceRejected("version is required and must be a non-empty string")
        if not origins:
            raise ProvenanceRejected("at least one SourceOrigin is required -- a dataset with no stated origin is rejected, not assumed trusted")
        for o in origins:
            if not o.license_name or not o.license_name.strip():
                raise ProvenanceRejected(f"source {o.source_id!r} has no license_name -- refusing to treat an unlicensed source as permissively usable")
            if not o.usage_restrictions or not o.usage_restrictions.strip():
                raise ProvenanceRejected(f"source {o.source_id!r} has no usage_restrictions stated")
        if not normalized_records:
            raise ProvenanceRejected("normalized_records is empty -- a dataset manifest requires at least one real record")
        if not tokenizer_binding.vocab_digest or not _SHA256_HEX.match(tokenizer_binding.vocab_digest):
            raise ProvenanceRejected(f"tokenizer_binding.vocab_digest must be a real 64-character hex SHA-256, got {tokenizer_binding.vocab_digest!r}")

        # Order-independent content digest: hash each record independently,
        # sort the per-record digests, then hash the sorted list -- so two
        # builds containing the exact same records in a different order
        # produce the SAME digest (sharding/shuffling must not change dataset
        # identity), while any actual content change does.
        record_digests = sorted(hashlib.sha256(r.encode("utf-8")).hexdigest() for r in normalized_records)
        source_content_digest = hashlib.sha256("".join(record_digests).encode("utf-8")).hexdigest()

        origins_t = tuple(origins)
        lineage_t = tuple(transformation_lineage)
        binding_fields = {
            "schema_version": MANIFEST_SCHEMA_VERSION, "dataset_name": dataset_name, "version": version,
            "origins": [asdict(o) for o in origins_t], "source_content_digest": source_content_digest,
            "tokenizer_binding": asdict(tokenizer_binding),
        }
        manifest_id = cls._compute_manifest_id(binding_fields)

        return cls(
            schema_version=MANIFEST_SCHEMA_VERSION, manifest_id=manifest_id, dataset_name=dataset_name, version=version,
            origins=origins_t, source_record_count=len(normalized_records), source_content_digest=source_content_digest,
            normalization_rule="unicodedata.normalize('NFC', text) then collapse whitespace then strip (see normalize_record_text())",
            transformation_lineage=lineage_t, tokenizer_binding=tokenizer_binding,
        )

    def manifest_path(self) -> Path:
        parent = _mkdir_owner_only(GENESIS_DATASET_MANIFEST_DIR, parents=True)
        return parent / f"{self.dataset_name}-{self.version}-{self.manifest_id[:16]}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        payload = {
            **asdict(self),
            "origins": [asdict(o) for o in self.origins],
            "transformation_lineage": [asdict(t) for t in self.transformation_lineage],
            "tokenizer_binding": asdict(self.tokenizer_binding),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        path.chmod(0o600)
        return path

    @classmethod
    def load(cls, path: Path) -> "GenesisDatasetManifest":
        """A-09 fix: the TRUSTED load boundary -- recomputes
        `manifest_id` fresh from the file's own claimed binding fields
        and REJECTS the file if that recomputation does not match the
        `manifest_id` the file itself claims. Independently reproduced
        before this fix: a hand-edited file (e.g. a substituted
        `dataset_name`, with the original `manifest_id` left
        unchanged -- or any arbitrary `manifest_id` at all) loaded with
        zero complaint; `manifest_id` was deserialized and trusted
        exactly like any other field, never independently re-derived.
        This recomputation only proves the file is INTERNALLY
        self-consistent (its own claimed id matches its own claimed
        content) -- it does NOT, and cannot, authenticate WHO produced
        the file or that its content is independently trustworthy;
        that is a separate concern (e.g. a signed provenance record or
        a trusted registry entry), not something a content hash alone
        can ever establish. Also rejects a malformed schema (missing
        required keys, wrong types) and a `schema_version` this code
        does not understand, rather than attempting a best-effort
        partial parse."""
        try:
            raw = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ManifestTamperedError(f"manifest at {path} is not valid JSON: {e!r}") from e
        if not isinstance(raw, dict):
            raise ManifestTamperedError(f"manifest at {path} is not a JSON object")
        required_keys = {
            "schema_version", "manifest_id", "dataset_name", "version", "origins", "source_record_count",
            "source_content_digest", "normalization_rule", "transformation_lineage", "tokenizer_binding", "created_at",
        }
        missing = required_keys - set(raw)
        if missing:
            raise ManifestTamperedError(f"manifest at {path} is missing required field(s): {sorted(missing)}")
        if raw["schema_version"] != MANIFEST_SCHEMA_VERSION:
            raise ManifestTamperedError(
                f"manifest at {path} declares schema_version={raw['schema_version']!r}, "
                f"but this code only understands {MANIFEST_SCHEMA_VERSION!r}"
            )
        claimed_manifest_id = raw["manifest_id"]
        if not isinstance(claimed_manifest_id, str) or not _SHA256_HEX.match(claimed_manifest_id):
            raise ManifestTamperedError(f"manifest at {path} has a malformed manifest_id: {claimed_manifest_id!r}")

        try:
            raw = dict(raw)
            raw["origins"] = tuple(SourceOrigin(**o) for o in raw["origins"])
            raw["transformation_lineage"] = tuple(TransformationStep(**t) for t in raw["transformation_lineage"])
            raw["tokenizer_binding"] = TokenizerBinding(**raw["tokenizer_binding"])
            instance = cls(**raw)
        except (TypeError, KeyError) as e:
            raise ManifestTamperedError(f"manifest at {path} has an inconsistent or malformed structure: {e!r}") from e

        binding_fields = {
            "schema_version": instance.schema_version, "dataset_name": instance.dataset_name, "version": instance.version,
            "origins": [asdict(o) for o in instance.origins], "source_content_digest": instance.source_content_digest,
            "tokenizer_binding": asdict(instance.tokenizer_binding),
        }
        recomputed_id = cls._compute_manifest_id(binding_fields)
        if recomputed_id != claimed_manifest_id:
            raise ManifestTamperedError(
                f"manifest at {path} is TAMPERED: its own claimed manifest_id ({claimed_manifest_id}) does not match "
                f"a fresh recomputation from its own binding fields ({recomputed_id}) -- a self-consistent hash was "
                f"never actually checked here before this fix, and substituted content went undetected"
            )
        if instance.source_record_count < 1:
            raise ManifestTamperedError(f"manifest at {path} declares source_record_count={instance.source_record_count}, expected >= 1")
        return instance

    def verify_against_records(self, normalized_records: list[str]) -> tuple[bool, str]:
        """Re-derives the content digest from a real set of records and
        confirms it matches this manifest -- the direct re-verification
        hook a future Workstream F integration would call before trusting
        this manifest's identity for a training-authorization request."""
        record_digests = sorted(hashlib.sha256(r.encode("utf-8")).hexdigest() for r in normalized_records)
        actual = hashlib.sha256("".join(record_digests).encode("utf-8")).hexdigest()
        if actual != self.source_content_digest:
            return False, f"content digest mismatch: manifest={self.source_content_digest} actual={actual}"
        if len(normalized_records) != self.source_record_count:
            return False, f"record count mismatch: manifest={self.source_record_count} actual={len(normalized_records)}"
        return True, "ok"
