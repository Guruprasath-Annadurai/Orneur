"""Model + system configuration locking.

A canonical per-arm configuration manifest (model id+revision, tokenizer, chat-template hash, decoding parameters, system-prompt hash, tool/RAG/kernel
configuration hash, code SHA) is hashed and LOCKED before any result. Every recorded result carries the config hash; the recorder refuses a result
whose hash differs from the lock for that arm (a changed prompt, decoding parameter, adapter revision or code SHA is a different configuration and
needs a new arm/lock, never a silent overwrite).

Mutable references ("main", "latest", "HEAD", branch-like names) are refused as revisions: a revision must be an immutable 40-hex commit or 64-hex digest.
This module computes and compares hashes only; it loads no model and contacts nothing.
"""
from __future__ import annotations

import re

from orca.evalinfra.canon import HEX40, HEX64, is_hex64, is_int, is_num, obj_hash
from orca.evalinfra.errors import ConfigMismatch, SchemaViolation
from orca.evalinfra.stats_paired import ARMS

SCHEMA_VERSION = "orneur-evalinfra-config/1"
CONFIG_KEYS = frozenset({"schema_version", "arm", "synthetic", "model", "tokenizer", "chat_template_sha256", "decoding", "system_prompt_sha256",
                         "tool_rag_kernel_config_sha256", "code_sha"})
REF_KEYS = frozenset({"id", "revision"})
DECODING_KEYS = frozenset({"do_sample", "temperature", "top_p", "top_k", "max_new_tokens"})
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+ -]{0,127}$")
_MUTABLE = {"main", "master", "latest", "head", "dev", "develop", "stable"}


def _rev(v, where):
    if not (isinstance(v, str) and (HEX40.match(v) or HEX64.match(v))):
        raise SchemaViolation("MUTABLE_OR_BAD_REVISION", f"{where}: a revision must be an immutable 40-hex commit or 64-hex digest (got a mutable/unknown ref)")


def validate_config(c) -> dict:
    if not isinstance(c, dict) or set(c) != CONFIG_KEYS:
        raise SchemaViolation("CONFIG_SCHEMA", "exact keys " + str(sorted(CONFIG_KEYS)))
    if c["schema_version"] != SCHEMA_VERSION or c["arm"] not in ARMS or not isinstance(c["synthetic"], bool):
        raise SchemaViolation("CONFIG_HEADER")
    for part in ("model", "tokenizer"):
        r = c[part]
        if not isinstance(r, dict) or set(r) != REF_KEYS or not (isinstance(r["id"], str) and _NAME.match(r["id"])) or r["id"].lower() in _MUTABLE:
            raise SchemaViolation("CONFIG_REF", part)
        _rev(r["revision"], part)
    for k in ("chat_template_sha256", "system_prompt_sha256", "tool_rag_kernel_config_sha256"):
        if not is_hex64(c[k]):
            raise SchemaViolation("CONFIG_HASH", k)
    if not (isinstance(c["code_sha"], str) and HEX40.match(c["code_sha"])):
        raise SchemaViolation("CONFIG_CODE_SHA", "code_sha must be a 40-hex git commit")
    d = c["decoding"]
    if not isinstance(d, dict) or set(d) != DECODING_KEYS:
        raise SchemaViolation("CONFIG_DECODING", "exact keys " + str(sorted(DECODING_KEYS)))
    if not isinstance(d["do_sample"], bool) or not is_num(d["temperature"]) or d["temperature"] < 0 or not is_num(d["top_p"]) or not (0 < d["top_p"] <= 1):
        raise SchemaViolation("CONFIG_DECODING", "types/ranges")
    if not is_int(d["top_k"]) or d["top_k"] < 0 or not is_int(d["max_new_tokens"]) or d["max_new_tokens"] < 1:
        raise SchemaViolation("CONFIG_DECODING", "types/ranges")
    if not d["do_sample"] and d["temperature"] not in (0, 0.0):
        raise SchemaViolation("CONFIG_DECODING", "greedy decoding (do_sample=false) must declare temperature 0")
    return c


def config_hash(c: dict) -> str:
    return obj_hash(validate_config(c))


def assert_config_matches(locked_hash: str, result_config_hash: str, *, arm: str) -> None:
    if not (is_hex64(locked_hash) and is_hex64(result_config_hash)) or locked_hash != result_config_hash:
        raise ConfigMismatch("CONFIG_HASH_MISMATCH", f"arm {arm}: the result was produced under a configuration that differs from the locked one")
