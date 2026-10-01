# ORNEUR Genesis V2 — Vault (Domain 4) Terraform/OpenTofu variable skeleton.
# NOT APPLIED. No provider block exists in this directory. No resource block exists in this directory.
# This file exists only to pin down the INPUTS a real Vault module would need, for review purposes,
# before any provider is chosen (see docs/orneur/phase-21/infrastructure/GENESIS_V2_OWNER_DECISIONS_REQUIRED.md).

variable "vault_bucket_name" {
  description = "Name of the dedicated object-storage bucket/container for Genesis V2 ciphertext. Must live in an account used for nothing else."
  type        = string
}

variable "object_lock_enabled" {
  description = "Whether write-once/immutability (Object Lock or equivalent) is enabled on the vault prefix. Must be true before any real corpus write."
  type        = bool
  default     = true
}

variable "allowed_writer_principal_arns" {
  description = "Exactly the Forge (Generator) identity's principal ARN(s)/ID(s). Never a wildcard. See GENESIS_V2_IAM_MATRIX.md."
  type        = list(string)
}

variable "allowed_reader_principal_arns" {
  description = "Exactly the Witness (Verifier) identity's principal ARN(s)/ID(s). Never a wildcard, never overlapping with allowed_writer_principal_arns. See GENESIS_V2_IAM_MATRIX.md."
  type        = list(string)
}

variable "public_access_block_enabled" {
  description = "Account-level public-access block. Must be true at every tier. See GENESIS_V2_NETWORK_POLICY.md."
  type        = bool
  default     = true
}
