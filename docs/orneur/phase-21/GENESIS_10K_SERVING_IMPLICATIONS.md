# Genesis 10K Real-Time User Serving Implications

Capacity architecture planning per spec section 20. **This does not
provision anything.** Permanent requirement restated: ORNEUR's initial
production target is 10,000 real-time users with no material
compromise in Genesis intelligence quality.

## What "one GPU serves 10K users" gets wrong

No single accelerator, regardless of class, serves 10,000 concurrent
real-time users for a modern LLM. Required architecture elements,
independent of which candidate is eventually selected:

- **Continuous batching** — dynamically packing concurrent requests
  onto the same forward passes (standard in vLLM/SGLang, both
  Modal-documented) rather than one-request-per-GPU-pass
- **Multiple replicas** behind a load balancer/router, sized to the
  target concurrent-request volume and each replica's measured
  tokens/sec throughput
- **Autoscaling** tied to queue depth / concurrent-request signals,
  not a fixed replica count
- **KV-cache-aware routing** (prefix caching / sticky sessions) to
  avoid redundant prefill work across replicas
- **Streaming token delivery** for perceived latency at scale
- **Failover** across replicas (and ideally regions) so a single
  replica or host failure doesn't take down service

## Per-candidate-class implications

- **True frontier giants (100B+ total, per the Compute Matrix doc)**:
  EACH replica requires the full multi-GPU weight-storage footprint
  (e.g. 3-70× 80GB GPUs depending on candidate and precision).
  10,000-user serving therefore implies many such multi-GPU replicas
  running concurrently — a substantially larger and more expensive
  deployment than smaller candidates, scaling roughly linearly with
  target concurrency on top of the already-large per-replica GPU count.
- **Qwen3.8-27B-class dense models**: single-GPU (or small multi-GPU
  for headroom) per replica makes horizontal scaling to 10K users a
  much more tractable, standard autoscaling problem, at the cost of
  whatever capability gap exists (unverified this phase) between a 27B
  dense model and the frontier giants.
- **Mid-scale candidates (e.g. GLM-5.3-Flash, 320B total)**: an
  intermediate case — meaningfully smaller per-replica footprint than
  the largest giants, but still multi-GPU per replica.

## Quality compromises

**NONE ACCEPTED.** Per the owner's permanent requirement, serving-cost
considerations inform infrastructure planning but must never be used
to justify selecting a lower-capability Genesis foundation than the
evidence supports. If the evidence-based frontier candidate genuinely
requires a large multi-GPU-per-replica deployment to serve 10,000
users without degrading intelligence quality, that is the architecture
to plan toward — not a reason to downgrade the model choice. This
phase makes no claim about which candidate that will turn out to be.

## What this phase does NOT do

No production capacity was provisioned, sized in dollar terms, or
committed to. This document exists so that future foundation-model
selection is made with eyes open to its serving-scale implications,
not to lock in a specific serving architecture now.
