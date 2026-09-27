# Genesis Capability Eval V2 — hermetic coding-sandbox qualification-candidate image.
# Pinned by content digest, not a mutable tag: the tag below is documentation only, the digest is the actual trust root.
# Base: python:3.11-slim @ sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e (resolved 2026-09-27)
FROM python@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

# No packages are added: coding items are scored with the Python 3 standard library only (see SandboxPolicy.allow_dependencies == ()).
# Non-root execution, network disabled, and every other hardening control are applied at `docker run` time by
# orca/eval/genesis_v2/sandbox.py (build_docker_args), not baked into this image, so the same image cannot be run unsafely by omission.
LABEL orneur.genesis.v2.sandbox.qualification_candidate="1"
