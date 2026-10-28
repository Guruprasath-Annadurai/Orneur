# ORNEUR — QUALIFICATION LANDMARK-01
## WAVE K: Qualification Machine-Readable Evidence Schema Specification

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** FINAL SCHEMA SPECIFICATION  

---

### 1. JSON Schema for Qualification Manifests

All automated test runs executed by the ORNEUR Independent Qualification Laboratory emit structured JSON receipts adhering to the schema below:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OrneurQualificationEvidenceManifest",
  "type": "object",
  "required": [
    "manifest_version",
    "timestamp",
    "worktree",
    "target_sha",
    "target_branch",
    "environment",
    "results",
    "summary"
  ],
  "properties": {
    "manifest_version": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "worktree": { "type": "string" },
    "target_sha": { "type": "string", "pattern": "^[0-9a-f]{40}$" },
    "target_branch": { "type": "string" },
    "is_clean_worktree": { "type": "boolean" },
    "environment": {
      "type": "object",
      "required": ["os", "python", "redis", "model"],
      "properties": {
        "os": { "type": "string" },
        "python": { "type": "string" },
        "redis": { "type": "string" },
        "model": { "type": "string" }
      }
    },
    "results": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["command", "exit_code", "passed", "duration_seconds", "stdout", "stderr"],
        "properties": {
          "command": { "type": "string" },
          "exit_code": { "type": "integer" },
          "passed": { "type": "boolean" },
          "duration_seconds": { "type": "number" },
          "stdout": { "type": "string" },
          "stderr": { "type": "string" }
        }
      }
    },
    "summary": {
      "type": "object",
      "required": ["total_suites", "passed_suites", "failed_suites", "total_duration_seconds"],
      "properties": {
        "total_suites": { "type": "integer" },
        "passed_suites": { "type": "integer" },
        "failed_suites": { "type": "integer" },
        "total_duration_seconds": { "type": "number" }
      }
    }
  }
}
```

### 2. Evidence Integrity & Immutability Rules

1. Manifests are generated programmatically by `scripts/qualification/run_qualification_suite.py`. Hand-editing results is strictly forbidden.
2. Every test result records exact exit codes, raw stdout/stderr captures, and test duration.
3. The manifest is committed directly alongside qualification documentation to provide an immutable audit trail.
