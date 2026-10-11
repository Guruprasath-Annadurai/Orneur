"""Content + renderers for the foundation evidence reassessment (JSON document and Markdown report).

All narrative judgments live here so that build_evidence.py stays a plain data assembler.  Offline only.
"""
from __future__ import annotations

GB = 1e9
BASE = "repo@cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d"
T_REPO = "2026-10-11T19:15:00Z"
T_WEB = "2026-10-11T19:26:00Z"
T_FILE = "2026-10-11T19:21:00Z"
NOT_A_SELECTION = ("NOT A SELECTION. No foundation model is selected, promoted or recommended as final by this document. Selection requires the mandatory frozen "
                   "capability evaluation (GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26 section 5) and explicit founder authorization.")


def fact(statement, cls, url, rev=BASE, ts=T_REPO, **kw):
    if not url.startswith(("http://", "https://", "repo:")):
        url = "repo:" + url
    kw.pop("source_url_is_repo", None)
    d = {"statement": statement, "claim_class": cls, "source_url": url, "retrieved_at": ts, "revision": rev}
    d.update(kw)
    return d


def gb(x, n=1):
    return f"{x / GB:.{n}f}"


# ---------------------------------------------------------------------------------------------------------
def license_findings(texts, ref):
    q3 = "Qwen3-8B (Apache-2.0)"
    nemo = "Mistral-Nemo-Instruct-2407 (Apache-2.0 declared)"
    phi = "Phi-4 (MIT)"
    q25 = "Qwen2.5-3B-Instruct, unsloth mirror (qwen-research)"
    rows = []
    CID = {q3: "qwen3-8b", nemo: "mistral-nemo-instruct-2407", phi: "phi-4", q25: "unsloth-qwen2.5-3b-instruct"}
    HFQ3 = "https://huggingface.co/Qwen/Qwen3-8B/resolve/b968826d9c46dd6066d109eabc6255188de91218/LICENSE"
    HFPHI = "https://huggingface.co/microsoft/phi-4/resolve/2db69c1c3e91a05d2c64a3185acfbaf36f744e25/LICENSE"
    HFQ25 = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve/aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE"
    NEMO_README = "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/resolve/04d8a90549d23fc6bd7f642064003592df51e9b3/README.md"
    NEMO_TREE = "https://huggingface.co/api/models/mistralai/Mistral-Nemo-Instruct-2407/tree/04d8a90549d23fc6bd7f642064003592df51e9b3"

    def row(cand, topic, finding, status, url, rev, cls="DOCUMENTED_FACT", counsel=False, clause=None):
        rows.append({"candidate": cand, "candidate_id": CID[cand], "topic": topic, "finding": finding, "permission_status": status, "requires_counsel": counsel,
                     "clause": clause, "claim_class": cls, "source_url": url, "retrieved_at": T_FILE, "revision": rev})

    R3, RP, RQ = "b968826d9c46dd6066d109eabc6255188de91218", "2db69c1c3e91a05d2c64a3185acfbaf36f744e25", "aa8e72537993ba99e69dfaafa59ed015b17504d1"
    RN = "04d8a90549d23fc6bd7f642064003592df51e9b3"
    # Qwen3-8B
    row(q3, "commercial use", "Permitted: the grant covers reproduce, prepare Derivative Works, publicly display/perform, sublicense and distribute the Work and Derivative Works in Source or Object form; no field-of-use, revenue or MAU limit appears in the text.", "PERMITTED", HFQ3, R3, clause="Apache-2.0 s.2")
    row(q3, "fine-tuned / derived weights", "Permitted. Derivative Works may carry additional or different terms for ORNEUR's own modifications provided the Work's conditions are met.", "PERMITTED", HFQ3, R3, clause="s.4 final paragraph")
    row(q3, "redistribution obligations", "Must (a) give recipients a copy of the License, (b) mark modified files with prominent change notices, (c) retain copyright/patent/trademark/attribution notices in Source form, (d) carry NOTICE contents if a NOTICE file exists - the pinned repo has no NOTICE file.", "OBLIGATED", HFQ3, R3, clause="s.4(a)-(d)")
    row(q3, "attribution / naming", "No 'Built with' style obligation. s.6 grants no trademark licence: the Qwen/Alibaba names may be used only for reasonable and customary description of origin and NOTICE reproduction.", "PERMITTED_WITH_LIMIT", HFQ3, R3, clause="s.6")
    row(q3, "ORNEUR 'vendor names stripped from outputs' doctrine", "The licence text does not require model OUTPUTS to name the vendor, but s.4(c)/(d) require attribution notices to travel with redistributed Derivative Works. Whether stripping vendor identity from product surfaces is compatible with those duties for hosted-only vs redistributed weights is a legal question.", "AMBIGUOUS", HFQ3, R3, counsel=True, clause="s.4(c)-(d), s.6")
    row(q3, "patent", "Express contributor patent licence; terminates for a licensee that sues alleging the Work infringes a patent.", "OBLIGATED", HFQ3, R3, clause="s.3")
    row(q3, "acceptable-use policy", "None in the LICENSE or in the model card at the pinned commit.", "NONE_FOUND", "https://huggingface.co/Qwen/Qwen3-8B/resolve/b968826d9c46dd6066d109eabc6255188de91218/README.md", R3)
    row(q3, "using outputs to train other models", "The licence text is silent on model outputs; no output-use restriction appears in LICENSE or README. Legal effect on distillation from Qwen3 outputs is not resolved by the text.", "SILENT", HFQ3, R3, counsel=True)
    row(q3, "weights as licensed subject matter", "Apache-2.0 is a copyright/patent licence over a 'Work'; whether trained weights are copyrightable (and therefore what the grant operates on) varies by jurisdiction. Repo shortlist already asks for pro-forma counsel confirmation before public commercial release.", "AMBIGUOUS", HFQ3, R3, cls="UNTESTED_HYPOTHESIS", counsel=True)
    row(q3, "training-data provenance", "Qwen3 model card discloses no training-data sources; indemnity-relevant provenance cannot be assessed.", "NOT_DISCLOSED", "https://huggingface.co/Qwen/Qwen3-8B/resolve/b968826d9c46dd6066d109eabc6255188de91218/README.md", R3, counsel=True)
    # Phi-4
    row(phi, "commercial use", "Permitted: use, copy, modify, merge, publish, distribute, sublicense and/or sell, without restriction, subject to the notice condition.", "PERMITTED", HFPHI, RP, clause="MIT")
    row(phi, "fine-tuned / derived weights", "Permitted (modify, merge, distribute, sublicense). MIT contains no copyleft.", "PERMITTED", HFPHI, RP)
    row(phi, "redistribution obligations", "Include the copyright notice ('Copyright (c) Microsoft Corporation') and the permission notice in all copies or substantial portions.", "OBLIGATED", HFPHI, RP)
    row(phi, "attribution / naming", "No trademark clause and no 'Built with' obligation in the text; the notice condition is the only attribution duty.", "PERMITTED", HFPHI, RP)
    row(phi, "patent", "MIT is silent on patents (no express patent grant or retaliation clause, unlike Apache-2.0). Practical risk assessment belongs to counsel.", "SILENT", HFPHI, RP, counsel=True)
    row(phi, "acceptable-use policy", "None in LICENSE. Model card 'Out-of-Scope Use Cases' says nothing in the card modifies or restricts the license; it asks developers to evaluate safety/fairness and comply with law.", "NONE_FOUND", "https://huggingface.co/microsoft/phi-4/resolve/2db69c1c3e91a05d2c64a3185acfbaf36f744e25/README.md", RP)
    row(phi, "using outputs to train other models", "Licence is silent on outputs; no restriction found in LICENSE or README.", "SILENT", HFPHI, RP, counsel=True)
    row(phi, "training-data provenance", "data_summary_card.md: synthetic AI-generated data used; commercially licensed datasets used; some private third-party dataset information 'cannot be provided due to unavailability of the underlying data'. Upstream terms of the generator models used for synthetic data are not disclosed (NOT_VERIFIED).", "PARTIALLY_DISCLOSED", "https://huggingface.co/microsoft/phi-4/resolve/2db69c1c3e91a05d2c64a3185acfbaf36f744e25/data_summary_card.md", RP, counsel=True)
    # Nemo
    row(nemo, "licence text", "No LICENSE or NOTICE file exists in the repository at the pinned commit (tree listing). Apache-2.0 appears only as card metadata (license: apache-2.0) and README prose ('Released under the Apache 2 License'). No licence-text hash can be recorded from the repo, so the status is REQUIRES_COUNSEL, not GRANTED. The canonical Apache-2.0 text from apache.org is stored as a reference only.", "UNVERIFIED_TEXT", NEMO_TREE, RN, counsel=True)
    row(nemo, "commercial use / derived weights / redistribution", "If Apache-2.0 applies as declared, the same permissions and obligations as the Qwen3-8B rows apply (s.2-s.4). That conditional cannot be confirmed from a licence file in this repo.", "CONDITIONAL_ON_DECLARATION", NEMO_README, RN, cls="UNTESTED_HYPOTHESIS", counsel=True)
    row(nemo, "attribution / naming / patent", "Unknown beyond the generic Apache-2.0 terms; the model was 'trained jointly by Mistral AI and NVIDIA' (card) - whether NVIDIA contributes any separate notice is not stated.", "AMBIGUOUS", NEMO_README, RN, counsel=True)
    row(nemo, "acceptable-use policy", "None found. README Limitations: 'does not have any moderation mechanisms'; card metadata carries an extra_gated_description (privacy-policy text) although gated=false.", "NONE_FOUND", NEMO_README, RN)
    row(nemo, "using outputs to train other models", "No statement in the repo files.", "SILENT", NEMO_README, RN, counsel=True)
    row(nemo, "training-data provenance", "Not disclosed in the card ('large proportion of multilingual and code data').", "NOT_DISCLOSED", NEMO_README, RN, counsel=True)
    # Qwen2.5-3B
    row(q25, "commercial use", "NOT granted. 'Non-Commercial' means research or evaluation purposes only; 2.a limits the grant to NON-COMMERCIAL PURPOSES ONLY; 2.b: commercial use requires requesting a licence from Alibaba Cloud (no terms, price or contact path in the text).", "NOT_PERMITTED", HFQ25, RQ, clause="2.a-2.b, 1.i")
    row(q25, "fine-tuned / derived weights", "Non-commercial research/evaluation use of derivative works is permitted; commercial release of a derivative is not without a separate licence.", "RESTRICTED", HFQ25, RQ, clause="2.a")
    row(q25, "redistribution obligations", "Give recipients a copy of the Agreement; mark modified files; retain in a 'Notice' file: 'Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved.'", "OBLIGATED", HFQ25, RQ, clause="3.a-3.c")
    row(q25, "attribution / naming (training with outputs)", "If the Materials OR ANY OUTPUTS OR RESULTS THEREFROM are used to create, train, fine-tune or improve an AI model that is distributed or made available, 'Built with Qwen' or 'Improved using Qwen' must be prominently displayed in the product documentation. NOT mentioned in the repo's base qualification or shortlist summaries. Conflicts with a doctrine of stripping vendor names from product surfaces.", "OBLIGATED", HFQ25, RQ, counsel=True, clause="4.b")
    row(q25, "indemnity / governing law", "Licensee must defend, indemnify and hold harmless Alibaba Cloud against third-party claims (6.d); Agreement governed by PRC law with exclusive jurisdiction of the People's Courts in Hangzhou (8). Not summarised in the repo documents.", "OBLIGATED", HFQ25, RQ, counsel=True, clause="6.d, 8")
    row(q25, "termination / IP suits", "Licences terminate if the licensee sues Alibaba alleging the Materials or outputs infringe (5.c); Alibaba may terminate on breach and the licensee must delete and cease use (7.b).", "OBLIGATED", HFQ25, RQ, clause="5.c, 7.b")
    row(q25, "which text governs the unsloth mirror", "The unsloth repo has NO LICENSE file (tree listing); its card declares license: other / qwen-research and links to the upstream file. The upstream text is recorded here by hash; the mirror's own legal status relative to upstream is a counsel question.", "AMBIGUOUS", "https://huggingface.co/api/models/unsloth/Qwen2.5-3B-Instruct/tree/7548fff1f997f57b2e9e8ab1ec7be96949b00ed0", "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0", counsel=True)
    return rows


# ---------------------------------------------------------------------------------------------------------
def harness_errors():
    LP = "orca/eval/locked_smoke_protocol.py"
    CR = "scripts/phase21b_4_20_control_runtime_qualification.py"
    M = "docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md"
    ev = "docs/orneur/phase-21/evidence/"
    H = []

    def h(id_, title, observed, diagnosis, fix, offline, cls, src, needs_auth):
        H.append({"id": id_, "title": title, "observed": observed, "diagnosis": diagnosis, "proposed_fix_not_applied": fix,
                  "reproducible_without_provider_run": offline, "requires_owner_authorization_or_repin": needs_auth,
                  "claim_class": cls, "source_url": "repo:" + src, "retrieved_at": T_REPO, "revision": BASE})
    h("HE-1", "Smoke prompts B and C do not instruct the output format that the acceptance expects",
      "B sends the bare user message '2 + 3' and requires content to equal exactly '5'; C sends 'Return valid JSON:\\n{\"status\":\"ready\"}' and requires the whole content to parse as that object. Qwen3-8B answered '2 + 3 = 5' (correct); Phi-4 answered '2 + 3 equals 5.' and, for C, 'The JSON you provided is already valid. Here it is again for clarity: ...'; Nemo answered with a worked calculation and fenced JSON.",
      "Contract/prompt mismatch: the prompt never says 'reply with only the number' (B) and C is ambiguous between 'validate this JSON' and 'emit this JSON'. Phi-4's reply to C is a reasonable reading of the prompt. The failures are measured against an acceptance the prompt does not request. The package already says these are response-format, not capability, failures.",
      "Author a v2 locked protocol with explicit output-format instructions ('Reply with only the digit', 'Output only a JSON object') and re-pin; replay the persisted raw outputs through a semantic acceptance function (reevaluate-smokes mode exists) to report what each model would score under a tolerant policy, as a separate non-qualifying column.",
      True, "INDEPENDENTLY_REPRODUCED", LP + " ; " + ev + "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json", True)
    h("HE-2", "Output-token budget differs per control and is outside the locked-protocol fingerprint",
      "smoke_max_tokens is 1024 for Qwen3-8B but 64 for Mistral-Nemo and Phi-4 (scripts/phase21b_4_20_control_runtime_qualification.py lines 79/87/94). Phi-4 smoke C ended with finish_reason='length' after exactly 64 completion tokens while Nemo's C (51 tokens) and Qwen's finished with 'stop'.",
      "The locked protocol sha256 (d462103b...) covers prompts and acceptance only; max_tokens is a per-control config value. Phi-4's smoke C could not complete its reply, so the 'content is not valid JSON' verdict conflates a truncated answer with a wrong one; budgets are not equal across candidates.",
      "Pin one max_tokens in the protocol; classify finish_reason='length' as INCONCLUSIVE_TRUNCATED (not MODEL_RUNTIME failure); add an offline unit test over the persisted raw responses.",
      True, "INDEPENDENTLY_REPRODUCED", CR + " ; " + ev + "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json", True)
    h("HE-3", "Runtime qualification and behavioural contract are conflated in one acceptance gate",
      "RUNTIME_QUALIFIED requires every smoke to be exactly satisfied (compute_smoke_acceptance), so a server that loaded the pinned identity, answered HTTP 200 x3 with finish_reason=stop and clean cleanup is recorded runtime FAILED.",
      "Verbosity of an instruct model is a behaviour property, not a serving defect (the package says so). Splitting the verdicts would let runtime compatibility (criterion E) be read from evidence without being contaminated by format behaviour (criteria F/G).",
      "Report two independent columns - SERVING_OK (identity, BF16, HTTP 200, non-empty, finish_reason=stop, cleanup) and CONTRACT_COMPLIANCE (exact/semantic) - without changing the existing frozen records; derive them offline from persisted raw outputs.",
      True, "INDEPENDENTLY_REPRODUCED", "orca/eval/control_runtime_qualification.py ; " + M, True)
    h("HE-4", "Smoke A is streamed, B and C are not",
      "Locked protocol sets stream=true only for A. A passed for Qwen3 and Phi-4 and failed for Nemo with different transports than B/C.",
      "Different request path (SSE assembly vs JSON body) between smokes confounds 'ready' vs 'instruction' behaviour; no evidence it changed an outcome, but it is an uncontrolled variable.",
      "Add a CPU test that feeds the recorded raw A response through the SSE assembler and compares with a non-streaming replay in a mock; or run all smokes in both modes under a future authorization.",
      True, "INDEPENDENTLY_REPRODUCED", LP, True)
    h("HE-5", "Mistral-Nemo: HF chat-template resolution fails because tekken.json flips AutoTokenizer to MistralCommonBackend",
      "Attempts 1-2: HTTP 400 'default chat template is no longer allowed ... provide a chat template'. Repo CPU analysis shows the pinned tokenizer_config.json does contain a 3,945-byte chat_template (sha256 e4676cb5...), but with tekken.json present transformers 5.16.1 returns MistralCommonBackend (no chat_template, get_chat_template raises); without tekken.json the template resolves and renders '<s>[INST]...[/INST]'.",
      "Tooling interaction, established CPU-only by GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2; the vLLM log line 'Detected the chat template content format to be string' is emitted even when no template resolved and is misleading.",
      "Already addressed by candidate `mistral_nemo_native_v1` (--tokenizer-mode mistral, executed once as attempt 3). Offline alternatives for future work: stage a snapshot variant without tekken.json (changes the pinned file set and its hash manifest) or add a CPU preflight asserting 'tokenizer.chat_template is not None' before any GPU launch.",
      True, "INDEPENDENTLY_REPRODUCED", ev + "GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json", False)
    h("HE-6", "HTTP error bodies were not captured in Nemo attempt 1",
      "urllib raised HTTPError before status/body were recorded; attempt 1 was first classified MODEL_RUNTIME then re-classified UNATTRIBUTED_REQUEST_REJECTION after audit.",
      "Harness defect (already fixed in the shared runner per the matrix); historical records are immutable.", "None needed beyond keeping the regression test for error-body capture.",
      True, "INDEPENDENTLY_REPRODUCED", M, False)
    h("HE-7", "Qwen3-8B attempt 1 died on an uncaught builtin TimeoutError",
      "Modal 1.5.5 FunctionCall.get(timeout=) raises the builtin TimeoutError; the harness did not catch it; attempt 1 was cancelled after 34.6 s without serving the model.",
      "Harness defect, not a model result; the matrix records it as HARNESS_FAILURE and states a CI stand-in for modal cannot exercise the real exception type.",
      "Add a stand-in test that raises builtin TimeoutError and asserts the poll loop handles it (CI cannot import the real Modal SDK).",
      True, "INDEPENDENTLY_REPRODUCED", M, False)
    h("HE-8", "Greedy decoding is implicit: vLLM applies the model's generation_config.json defaults for fields the request omits",
      "Repo raw log (Qwen3 attempt 5, line 78): 'Default vLLM sampling parameters have been overridden by the model's generation_config.json: {temperature: 0.6, top_k: 20, top_p: 0.95}'. The locked request sends temperature, top_p, seed and max_tokens only.",
      "For Qwen3 the leftover top_k=20 is harmless under temperature 0. For Qwen2.5-3B (repetition_penalty 1.05 in generation_config) and any model with penalties, a temperature-0 request is not guaranteed to be plain argmax unless the server is started with --generation-config vllm or the request sets every sampling field (UNTESTED_HYPOTHESIS for Qwen2.5-3B; the vLLM behaviour itself is shown in the repo log).",
      "Record the effective sampling parameters in every evidence record (parse the vLLM startup warning) and add --generation-config vllm (or explicit top_k=-1, repetition_penalty=1.0) to a future protocol revision.",
      True, "INDEPENDENTLY_REPRODUCED", ev + "GENESIS_CONTROL_QWEN3_8B_MODAL_H100_ATTEMPT5_RAW_LOG_2026-09-24.txt", True)
    h("HE-9", "Qwen3 attempt 4 judged TECHNICAL_SUCCESS then reclassified; attempt-5 record carried a stale reasoning_mode",
      "Attempt 4 used the default thinking-on template and earlier prompt wording, was first judged success, and was reclassified TECHNICAL_FAILURE by the audit; the attempt-5 record initially said reasoning_mode ENABLED while 0 reasoning tokens were produced (metadata_correction added).",
      "Acceptance and metadata were derived from capability defaults rather than the effective request; fixed by deriving from the approved configuration.", "Keep the validator rule that metadata must be derived from the effective configuration; add a test asserting reasoning_tokens==0 whenever enable_thinking=false is recorded.",
      True, "INDEPENDENTLY_REPRODUCED", M, False)
    h("HE-10", "Settlement attribution: shared app description matching, aged-out apps and a false volume-metering block",
      "In-run settlement matched itemized rows by shared app description (included another attempt's app); an aged-out stopped app made reconciliation fail; a 0.196 USD 'volumes' meter caused a false financial block that the later gate correction cleared.",
      "Billing-logic defects (not model issues), fixed by object-id attribution, the aged-out-app rule and adjustment reconciliation. Zero owner cash was billed in the control program after the GLM incident (3.52 USD owner-billed in the earlier 21B.4.13 GLM run).",
      "None; keep the CPU tests. Note the decision package's 'owner billing stayed zero' is scoped to the 21B.4.20 control program, not the earlier GLM-5.3-Flash run.",
      True, "INDEPENDENTLY_REPRODUCED", M + " ; docs/orneur/phase-21/GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md", False)
    h("HE-11", "Criteria list is inconsistent across documents (A-Q in the blueprint vs A-R in the decision package)",
      "PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT D1 says 'A-Q (gates A,B,K; weighted F-Q)'; the decision package defines A-R, and its weights sum to 100 only if R (8 points) is included.",
      "Documentation drift, not harness code; any freeze must reference the package definition.", "Correct the blueprint reference in a future (non-frozen) edit; this reassessment follows the package (A-R).",
      True, "DOCUMENTED_FACT", "docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md ; docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md", False)
    return H


# ---------------------------------------------------------------------------------------------------------
def render_report(built, D, CLAIM_CLASSES):
    est, cands, light = built["est"], built["out_cands"], built["light"]
    by = {c["id"]: c for c in cands}
    order3 = ["qwen3-8b", "mistral-nemo-instruct-2407", "phi-4"]
    nm = {"qwen3-8b": "Qwen3-8B", "mistral-nemo-instruct-2407": "Mistral-Nemo-Instruct-2407", "phi-4": "Phi-4", "unsloth-qwen2.5-3b-instruct": "Qwen2.5-3B-Instruct (unsloth)"}
    e = est
    texts = built["texts"]
    lic_rows = license_findings(texts, built["ref_texts"])
    herr = harness_errors()

    # ---- package delta -------------------------------------------------------------------------------
    delta = []
    for s in order3:
        p = D.PACKAGE_NUMBERS[s]
        x = e[s]
        delta.append({"candidate": s,
                      "qlora_static_GB": {"package": p["static"], "this_pass": round(x["nf4_static_bytes"] / GB, 1)},
                      "qlora_peak_2048_GB": {"package": p["peak2k"], "this_pass": round(x["peak_s2048_ckpt_bytes"] / GB, 1)},
                      "qlora_peak_4096_GB": {"package": p["peak4k"], "this_pass": round(x["peak_s4096_ckpt_bytes"] / GB, 1)},
                      "bf16_weights_GB": {"package": p["bf16"], "this_pass": round(x["bf16_weights_bytes"] / GB, 1)},
                      "kv_8k_GB": {"package": p["kv8k"], "this_pass": round(x["kv_bytes_8k_seq"] / GB, 2)},
                      "lora_r16_trainable_M": {"package": p["lora16_m"], "this_pass": round(x["lora_r16_params"] / 1e6, 1)},
                      "claim_class": "UNTESTED_HYPOTHESIS", "source_url": "repo:scripts/foundation/build_evidence.py", "retrieved_at": T_REPO, "revision": BASE})

    # ---- ranking -------------------------------------------------------------------------------------
    min_bf16 = min(e[s]["bf16_weights_bytes"] for s in order3)
    min_par = min(by[s]["params"] for s in order3)
    DEC = "repo:docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md"
    scores = {
        "qwen3-8b": {"D": 3, "E": 4, "L": 3}, "mistral-nemo-instruct-2407": {"D": 1, "E": 2, "L": 2}, "phi-4": {"D": 4, "E": 4, "L": 3}}
    ranking_candidates = []
    for s in order3:
        o = round(6 * min_bf16 / e[s]["bf16_weights_bytes"], 2)
        p = round(6 * min_par / by[s]["params"], 2)
        sc = dict(scores[s], O=o, P=p)
        sub = round(sum(sc.values()), 2)
        ranking_candidates.append({"candidate": s, "scores": sc, "documented_subset_points": sub, "documented_subset_max": 24, "unevaluated_points": 76})
    gates = {
        "qwen3-8b": {"A": ("PASS", "dense Qwen3ForCausalLM, GQA 32/8, loads with transformers>=4.51 (no custom code); served under pinned vLLM in repo evidence"),
                     "B": ("PASS_ON_PAPER", "ESTIMATE only: QLoRA peak ~{:.0f}-{:.0f} GB (r=16, ckpt, s=2048/4096) - never trained; 16.4 GB BF16 serving".format(e["qwen3-8b"]["peak_s2048_ckpt_bytes"] / GB, e["qwen3-8b"]["peak_s4096_ckpt_bytes"] / GB)),
                     "K": ("PASS", "Apache-2.0 text retrieved and hashed (GRANTED); advisory counsel items remain (see license findings)")},
        "mistral-nemo-instruct-2407": {"A": ("PASS", "dense MistralForCausalLM, GQA 32/8; chat needs native Mistral tokenizer mode under the pinned stack"),
                                       "B": ("PASS_ON_PAPER", "ESTIMATE only: QLoRA peak ~{:.0f}-{:.0f} GB; 24.5 GB BF16 serving".format(e["mistral-nemo-instruct-2407"]["peak_s2048_ckpt_bytes"] / GB, e["mistral-nemo-instruct-2407"]["peak_s4096_ckpt_bytes"] / GB)),
                                       "K": ("CONDITIONAL_REQUIRES_COUNSEL", "Apache-2.0 declared but no license file in the repo at the pinned commit; no text hash")},
        "phi-4": {"A": ("PASS", "dense Phi3ForCausalLM, GQA 40/10; served on the canonical HF path in repo evidence"),
                  "B": ("PASS_ON_PAPER", "ESTIMATE only: QLoRA peak ~{:.0f}-{:.0f} GB; 29.3 GB BF16 serving".format(e["phi-4"]["peak_s2048_ckpt_bytes"] / GB, e["phi-4"]["peak_s4096_ckpt_bytes"] / GB)),
                  "K": ("PASS", "MIT text retrieved and hashed (GRANTED); no express patent grant (counsel advisory)")},
        "unsloth-qwen2.5-3b-instruct": {"A": ("PASS", "dense Qwen2ForCausalLM, GQA 16/2, tied embeddings"),
                                        "B": ("PASS_ON_PAPER", "ESTIMATE only: smallest of the four"),
                                        "K": ("FAIL", "qwen-research: commercial use not granted (RESTRICTED_NONCOMMERCIAL)")},
    }
    rubric = {
        "D": "4 = template resolves on the canonical HF path in repo evidence with no mode switch or injected defaults; 3 = resolves but contains a mode switch/state needing a deliberate SFT-template decision; 2 = resolves only with a documented workaround; 1 = canonical-path resolution FAILED on the pinned stack (native mode needed); 0 = unresolvable. Candidates without repo runtime evidence are NOT_EVALUATED.",
        "E": "4 = loaded and served on the canonical configuration under the pinned vLLM in repo evidence; 2 = served only after a non-canonical candidate configuration; 0 = did not serve. Exact-output smoke results are deliberately ignored (they are criteria F/G material).",
        "L": "4 = vLLM docs list the architecture with a LoRA mark and no pitfall is documented; 3 = listed with LoRA and one documented fine-tuning/export pitfall; 2 = listed but non-default modes needed in repo evidence plus public tracker history; NOT_EVALUATED without evidence.",
        "O": "6 x (smallest BF16 weight footprint among gate-eligible candidates) / (candidate BF16 weight footprint). ESTIMATE-derived: the criterion's 'at the frozen quality bar' clause cannot be applied.",
        "P": "6 x (smallest parameter count among gate-eligible candidates) / (candidate parameter count), because QLoRA FLOPs per token scale with 6 x params. ESTIMATE-derived.",
    }
    just = {
        ("qwen3-8b", "D"): "Hybrid thinking template: enable_thinking switch, empty <think> block injected when false (claim qwen3-8b chat_template); resolved on the canonical HF path in attempts 4-5 (repo).",
        ("qwen3-8b", "E"): "Served under vLLM 0.29.0 on the canonical configuration; attempt 5 HTTP 200 x3 (repo runtime record).",
        ("qwen3-8b", "L"): "vLLM Qwen3ForCausalLM LoRA mark; documented Unsloth completion-masking pitfall #2771 and think-tag handling.",
        ("mistral-nemo-instruct-2407", "D"): "Attempts 1-2 failed template resolution on the HF path (HTTP 400); native Mistral tokenizer mode needed (repo RCA V2).",
        ("mistral-nemo-instruct-2407", "E"): "Served only after non-canonical candidate configuration mistral_nemo_native_v1 (attempt 3).",
        ("mistral-nemo-instruct-2407", "L"): "Non-default tokenizer mode required; public vLLM PR #7739 and HF template discussions #14/#61; LoRA mark for MistralForCausalLM not captured this pass (NOT_VERIFIED).",
        ("phi-4", "D"): "Plain ChatML-like template, 462 bytes, no switches; resolved on the canonical path (attempt 1).",
        ("phi-4", "E"): "Served on the canonical configuration with no extra flags (attempt 1).",
        ("phi-4", "L"): "vLLM Phi3ForCausalLM LoRA mark; fused qkv_proj/gate_up_proj adapters need framework splitting support (tracker evidence), Unsloth pad-token history on other revisions.",
    }
    ranking_scores_detail = []
    for rc in ranking_candidates:
        for crit, val in rc["scores"].items():
            is_est = crit in ("O", "P")
            basis = just.get((rc["candidate"], crit)) or ("ESTIMATE-derived: " + rubric[crit])
            ranking_scores_detail.append({"candidate": rc["candidate"], "criterion": crit, "score": val, "max": {"D": 4, "E": 4, "L": 4, "O": 6, "P": 6}[crit], "basis": basis,
                                          "claim_class": "UNTESTED_HYPOTHESIS" if is_est else "INDEPENDENTLY_REPRODUCED" if crit in ("D", "E") else "DOCUMENTED_FACT",
                                          "source_url": "repo:scripts/foundation/build_evidence.py" if is_est else "repo:docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md",
                                          "retrieved_at": T_REPO, "revision": BASE})
    criteria = [
        ("A", "gate", None, "Architecture suitability"), ("B", "gate", None, "Parameter count / memory"), ("K", "gate", None, "Licensing / redistribution"),
        ("F", "weighted", 12, "Instruction-following"), ("G", "weighted", 12, "Structured output"), ("H", "weighted", 12, "Reasoning potential"), ("I", "weighted", 12, "Coding potential"),
        ("J", "weighted", 4, "Context-window characteristics"), ("D", "weighted", 4, "Tokenizer/chat-template stability"), ("E", "weighted", 4, "Runtime compatibility"),
        ("L", "weighted", 4, "Ecosystem/tooling maturity"), ("M", "weighted", 4, "Training-stability evidence"), ("N", "weighted", 4, "Quantization compatibility"),
        ("O", "weighted", 6, "Inference cost"), ("P", "weighted", 6, "Expected training cost"), ("Q", "weighted", 8, "Differentiated ORNEUR behaviour"), ("R", "weighted", 8, "Migration path to ORNEUR-owned families")]
    why_not = {"F": "needs frozen strict-format eval", "G": "needs frozen JSON/schema eval", "H": "needs frozen reasoning eval + pilot SFT gain", "I": "needs frozen coding eval", "J": "criterion is measured usable context at 8k/16k; only vendor-stated context is documented",
               "M": "no primary-source stability report located; pilot loss curves do not exist", "N": "needs NF4/4-bit quality retained on the frozen eval", "Q": "needs pilot behaviour shift", "R": "needs counsel + data-flow review (license inputs recorded)"}
    ranking = {
        "status": "PROVISIONAL_NON_BINDING", "is_selection": False, "binding": False, "selected_foundation": None,
        "statement": NOT_A_SELECTION + " The ordering below covers at most 24 of 100 weighted points, none of them capability points; the pre-registered selection rule (lead >= 5 weighted points AND a paired-bootstrap 95% interval excluding 0 on the eval axes) cannot be applied and is NOT applied.",
        "criteria": [{"id": i, "kind": k, "weight": w, "name": n, "evaluation_state": ("GATE" if k == "gate" else "SCORED_FROM_DOCUMENTED_EVIDENCE" if i in ("D", "E", "L", "O", "P") else "NOT_EVALUATED"),
                      "reason_not_evaluated": why_not.get(i)} for i, k, w, n in criteria],
        "weights_sum_weighted": sum(w for _, k, w, _ in criteria if k == "weighted"),
        "scoring_rubric": rubric,
        "gates": {s: {g: {"result": r, "basis": b, "claim_class": "UNTESTED_HYPOTHESIS" if g == "B" else "DOCUMENTED_FACT", "source_url": "repo:docs/orneur/status/foundation/foundation_evidence.json", "retrieved_at": T_REPO, "revision": BASE}
                      for g, (r, b) in gv.items()} for s, gv in gates.items()},
        "candidate_scores": ranking_candidates, "score_details": ranking_scores_detail,
        "excluded_from_weighted_scoring": [{"candidate": "unsloth-qwen2.5-3b-instruct", "reason": "gate K FAIL (non-commercial licence); not scored", "claim_class": "DOCUMENTED_FACT", "source_url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve/aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE", "retrieved_at": T_FILE, "revision": "aa8e72537993ba99e69dfaafa59ed015b17504d1"}],
        "identity_only_candidates_not_scored": [c["id"] for c in light],
        "documented_subset_order_non_binding": [r["candidate"] for r in sorted(ranking_candidates, key=lambda r: -r["documented_subset_points"])],
        "interpretation_limits": ["Scores D/E/L are rubric judgments over repo and tracker evidence, not measurements; O/P are arithmetic on estimates.",
                                  "Smoke pass counts are NOT a criterion (package section 2) and are not used.",
                                  "A higher subtotal here is not a lead under the pre-registered rule and must not be read as a recommendation."],
    }

    # ---- repo claim checks ---------------------------------------------------------------------------
    PKG = D.REPO_EVIDENCE["decision_package"]
    rc = [
        fact("Package s.3 gives Qwen3-8B context '32,768 native; 131,072 with YaRN' and the landscape marks config 40,960 vs vendor 32,768 as DIFFERS. Primary sources confirm BOTH numbers and the model card explains the gap (40,960 = 32,768 output + 8,192 prompt reservation). Not a contradiction; SFT sequence-length design should use 32,768 as the native figure.", "DOCUMENTED_FACT", "https://huggingface.co/Qwen/Qwen3-8B/resolve/b968826d9c46dd6066d109eabc6255188de91218/README.md", "b968826d9c46dd6066d109eabc6255188de91218", T_FILE, id="RC-1", verdict="CONFIRMED"),
        fact("Package s.3 and the Stage-0 matrix treat Mistral-Nemo's Apache-2.0 as established ('K: PASS', 'commercially clean') on the metadata tag. At the pinned commit the repository contains no LICENSE or NOTICE file (tree listing, 18 files); only the tag and README prose declare the licence. The package's K=PASS is therefore evidence-grade 'declared', not 'text verified'.", "DOCUMENTED_FACT", "https://huggingface.co/api/models/mistralai/Mistral-Nemo-Instruct-2407/tree/04d8a90549d23fc6bd7f642064003592df51e9b3", "04d8a90549d23fc6bd7f642064003592df51e9b3", T_API_(), id="RC-2", verdict="WEAKER_THAN_STATED"),
        fact("GENESIS_BASE_MODEL_QUALIFICATION and the shortlist summarise the qwen-research licence as non-commercial with attribution duties (a)-(c). The licence text also contains 4.b (display 'Built with Qwen'/'Improved using Qwen' when the Materials OR THEIR OUTPUTS are used to train/improve a distributed AI model), 6.d (indemnify Alibaba Cloud), 7.b (delete on termination) and 8 (PRC law, Hangzhou courts). These obligations are not in the repo summaries.", "DOCUMENTED_FACT", "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve/aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE", "aa8e72537993ba99e69dfaafa59ed015b17504d1", T_FILE, id="RC-3", verdict="INCOMPLETE_SUMMARY"),
        fact("The Stage-0 license matrix says the controls (Qwen3-8B, Mistral-Nemo, Phi-4) are 'control use only, never a candidate finalist' and the 2026-09-26 landscape marks them BASELINE_ONLY_CONTROL with admitted_to_capability_eval=false, while the same day's decision package calls them the 'admitted options' for Genesis Capability Eval v0 and this task's brief calls them finalists. The repo's own documents disagree on whether the three controls are in the candidate pool.", "DOCUMENTED_FACT", D.REPO_EVIDENCE["stage0_matrix"] + " ; docs/orneur/phase-21/GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md ; " + D.REPO_EVIDENCE["decision_package"], BASE, T_REPO, id="RC-4", verdict="INTERNAL_INCONSISTENCY"),
        fact("Blueprint WS-D D1 refers to pre-registered criteria 'A-Q (gates A,B,K; weighted F-Q)'; the decision package defines A-R and its 14 weighted weights sum to 100 only with R (8). This reassessment follows the package.", "DOCUMENTED_FACT", "repo:docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md", BASE, T_REPO, id="RC-5", verdict="DOCUMENT_DRIFT"),
        fact("Package KV-cache per 8k sequence (1.21/1.34/1.68 GB) and bf16 weights (16.4/24.5/29.3 GB) are reproduced exactly by the formulas applied to primary-source config values; parameter counts (8.19/12.25/14.66 B) equal the safetensors totals.", "DOCUMENTED_FACT", "repo:scripts/foundation/build_evidence.py", BASE, T_REPO, id="RC-6", verdict="CONFIRMED"),
        fact("Package QLoRA static/peak estimates are within the package's own +/-40% band of this pass's independently derived figures but not identical (formulas differ in activation accounting); see the delta table. Both are ESTIMATES; neither is a measurement.", "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", BASE, T_REPO, id="RC-7", verdict="CONSISTENT_WITHIN_ESTIMATE_BAND"),
        fact("Package s.3 says Phi-4 uses 'fused qkv / gate_up projections'. The weight index (model.safetensors.index.json) was not read in this pass; vLLM/Automodel tracker evidence mentions fused QKV for Phi-4, but the gate_up fusion claim is NOT_VERIFIED here.", "NOT_VERIFIED", "https://huggingface.co/microsoft/phi-4/resolve/2db69c1c3e91a05d2c64a3185acfbaf36f744e25/model.safetensors.index.json", "2db69c1c3e91a05d2c64a3185acfbaf36f744e25", T_FILE, id="RC-8", verdict="NOT_VERIFIED"),
        fact("Package s.1 'owner billing remained zero across the controlled program' is correct for the 21B.4.20 control program, but the earlier 21B.4.13 GLM-5.3-Flash run did bill the owner USD 3.52; the sentence should not be read as program-wide.", "DOCUMENTED_FACT", D.REPO_EVIDENCE["glm_incident"], BASE, T_REPO, id="RC-9", verdict="SCOPE_CAVEAT", source_url_is_repo=True),
        fact("Shortlist: 'Phi-4 model card last modified 2026-07-14' is confirmed (API lastModified 2026-07-14T14:22:25Z at head sha == pinned sha). The pinned commit therefore post-dates the Dec-2024 release and includes data_summary_card.md (updated 24-Nov-2025); weights are the LFS objects the repo hashed on 2026-09-24 (identical sha256).", "DOCUMENTED_FACT", "https://huggingface.co/api/models/microsoft/phi-4", "2db69c1c3e91a05d2c64a3185acfbaf36f744e25", T_API_(), id="RC-10", verdict="CONFIRMED"),
        fact("All 15 revision SHAs checked (3 controls, unsloth+upstream Qwen2.5-3B, 10 landscape-admitted dense models) still equal the repo's recorded SHAs; the three out-of-scope names that sounded unusual (Qwen3.8-27B, Mistral-Small-4-119B-2603, GLM-5.3-Flash) exist at the recorded revisions. No repo candidate is NOT_FOUND_AT_PRIMARY_SOURCE.", "DOCUMENTED_FACT", "https://huggingface.co/api/models/Qwen/Qwen3.8-27B", "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0", T_API_(), id="RC-11", verdict="CONFIRMED"),
        fact("Mistral-Nemo chat template sha256 e4676cb5... recorded by the repo (from the cached snapshot) equals the sha256 of the template read from the Hugging Face model API at HEAD (== pinned sha) today, and tokenizer_config.json is 181,297 bytes in both. The repo's recorded template sizes for Qwen3-8B (4,168 chars) and Phi-4 (462 chars) also equal the byte lengths of the byte-verified templates stored here.", "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["nemo_template_rca"], BASE, T_REPO, id="RC-12", verdict="CONFIRMED"),
        fact("Weights integrity: every LFS sha256 and size of the three controls at the pinned commits equals the hf_lfs_sha256 values in the repo's pre-cache manifests (18 weight/tokenizer objects, 0 mismatches).", "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["qwen3_precache"], BASE, T_REPO, id="RC-13", verdict="CONFIRMED"),
    ]
    changes = [
        fact("No drift: every pinned revision is still the repository HEAD on 2026-10-11 (15 days after the package); weights and tokenizer objects are unchanged (LFS sha256 identical to the repo manifests).", "DOCUMENTED_FACT", "https://huggingface.co/api/models/Qwen/Qwen3-8B/tree/b968826d9c46dd6066d109eabc6255188de91218", "b968826d9c46dd6066d109eabc6255188de91218", T_API_(), id="CH-1"),
        fact("Licence evidence upgraded from metadata tags to byte-verified texts: Qwen3-8B Apache-2.0 (git blob 6634c8cc..., identical to canonical Apache-2.0 with 'Copyright 2024 Alibaba Cloud'), Phi-4 MIT (git blob 700edcc5..., CRLF), Qwen research licence (git blob ed317377...). Nemo has no licence text to hash.", "DOCUMENTED_FACT", "docs/orneur/status/foundation/foundation_evidence.json", BASE, T_REPO, id="CH-2", source_url_is_repo=True),
        fact("NEW finding: Mistral-Nemo-Instruct-2407 ships no LICENSE file at the pinned commit; its gate K moves from 'PASS' to 'CONDITIONAL / REQUIRES_COUNSEL' in this document.", "DOCUMENTED_FACT", "https://huggingface.co/api/models/mistralai/Mistral-Nemo-Instruct-2407/tree/04d8a90549d23fc6bd7f642064003592df51e9b3", "04d8a90549d23fc6bd7f642064003592df51e9b3", T_API_(), id="CH-3"),
        fact("NEW finding: the Qwen research licence contains output-use and indemnity clauses (4.b, 6.d) absent from the repo summaries; relevant to the current canonical base and to any plan that distills from Qwen outputs.", "DOCUMENTED_FACT", "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve/aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE", "aa8e72537993ba99e69dfaafa59ed015b17504d1", T_FILE, id="CH-4"),
        fact("Chat-template identity is now hashed (Qwen3-8B 4,168 B, Phi-4 462 B, Qwen2.5-3B 2,507 B, Nemo 3,945 B) and the Nemo hash independently matches the repo's recorded hash. The package recorded template behaviour but no template hashes for the candidates.", "DOCUMENTED_FACT", "docs/orneur/status/foundation/foundation_evidence.json", BASE, T_REPO, id="CH-5", source_url_is_repo=True),
        fact("Added (the package deliberately omitted them): vendor benchmark tables with explicit limitations, multilingual and safety statements, serving/quantization availability, public tracker issues, and serving-cost hypotheses.", "DOCUMENTED_FACT", "docs/orneur/status/foundation/FOUNDATION_EVIDENCE_REASSESSMENT.md", BASE, T_REPO, id="CH-6", source_url_is_repo=True),
        fact("Estimates re-derived with explicit formulas (package static/peak figures agree within its +/-40% band; KV, BF16 and LoRA parameter counts reproduce exactly). Package range-based conclusion 'any of the three fits QLoRA' unchanged but still unproven.", "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", BASE, T_REPO, id="CH-7", source_url_is_repo=True),
        fact("Landscape-admitted dense models of 3-14B (10) were re-checked for identity only: SHAs, parameter counts and licence tags unchanged since 2026-09-26. Gemma 4 licence_link resolves to a hosted Apache-2.0 page (not a repo file); Phi-4-mini carries the custom_code tag.", "DOCUMENTED_FACT", "https://huggingface.co/api/models/google/gemma-4-12B-it", "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7", T_API_(), id="CH-8"),
        fact("New reproducible harness diagnoses from persisted evidence: unequal max_tokens (1024 vs 64) with a truncated Phi-4 smoke, prompts that do not request the accepted format, implicit generation_config sampling defaults (HE-1, HE-2, HE-8).", "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["phi4_runtime"], BASE, T_REPO, id="CH-9", source_url_is_repo=True),
        fact("Decision unchanged: FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL. Nothing here selects, promotes or authorizes anything.", "DOCUMENTED_FACT", PKG, BASE, T_REPO, id="CH-10", source_url_is_repo=True),
    ]
    not_verified = [fact(s, "NOT_VERIFIED", u, rev, ts, id=f"NV-{i + 1}") for i, (s, u, rev, ts) in enumerate([
        ("llama.cpp support for Mistral-Nemo, Phi-4 and Qwen2.5-3B: the README query returned nothing; only the Qwen3 model card's statement that llama.cpp supports Qwen3 is recorded.", "https://github.com/ggml-org/llama.cpp", "UNVERSIONED_WEB_PAGE@" + T_WEB, T_WEB),
        ("Availability and quality of third-party quantised artifacts (GGUF/AWQ/GPTQ) beyond Ollama Q4_K_M listings was not enumerated.", "https://huggingface.co/models", "UNVERSIONED_WEB_PAGE@" + T_WEB, T_WEB),
        ("vLLM docs LoRA mark for MistralForCausalLM in the current docs: the tool's table extraction omitted the row (the repo's 2026-09-26 collection lists the architecture).", "https://docs.vllm.ai/en/latest/models/supported_models/", "UNVERSIONED_WEB_PAGE@" + T_WEB, T_WEB),
        ("Mistral-Nemo tokenizer_config bos/eos/unk string values: the tool strips angle-bracket tokens; only ids (config.json) and the repo's rendering '<s>[INST]...[/INST]' are recorded.", "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/resolve/04d8a90549d23fc6bd7f642064003592df51e9b3/tokenizer_config.json", "04d8a90549d23fc6bd7f642064003592df51e9b3", T_FILE),
        ("Phi-4 technical report (arXiv:2412.08905) safety numbers and contamination/decontamination methodology were not re-read; only the model card is recorded.", "https://arxiv.org/abs/2412.08905", "UNVERSIONED_WEB_PAGE@" + T_WEB, T_WEB),
        ("Qwen3 pretraining-token count and language count: the extraction did not return them; only the model card's '100+ languages and dialects' is recorded.", "https://arxiv.org/pdf/2505.09388", "arXiv:2505.09388", "2026-10-11T19:23:30Z"),
        ("Mistral-Nemo benchmark harness, prompts and base-vs-instruct status are not stated by the vendor.", "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/resolve/04d8a90549d23fc6bd7f642064003592df51e9b3/README.md", "04d8a90549d23fc6bd7f642064003592df51e9b3", T_FILE),
        ("FP16 numerical behaviour of Qwen3-8B / Nemo / Phi-4 on T4-class (compute capability 7.5) GPUs - never run.", "repo:scripts/foundation/build_evidence.py", BASE, T_REPO),
        ("GPU rental prices other than the repo's persisted H100 list rate (USD 3.95/h), and the H100 memory bandwidth figure (3.35 TB/s assumed), are inputs that were not re-fetched.", "repo:docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md", BASE, T_REPO),
        ("Full licence texts of the ten IDENTITY_ONLY landscape candidates (Qwen3.5, Gemma 4, Granite 4.2, Olmo 3, SmolLM3, Phi-4-mini, Ministral 3) were not retrieved or hashed; their licence status is TAG_ONLY_UNVERIFIED or REQUIRES_COUNSEL.", "docs/orneur/status/foundation/foundation_evidence.json", BASE, T_REPO),
        ("Content of the cited HF discussion pages and GitHub issues was read from search excerpts only.", "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/discussions/61", "UNVERSIONED_WEB_PAGE@" + T_WEB, T_WEB),
        ("Whether trained weights are copyrightable / what an Apache-2.0 or MIT grant operates on: a legal question not answered here.", "repo:docs/orneur/phase-21/GENESIS_STAGE0_LICENSE_MATRIX.md", BASE, T_REPO),
    ])]

    doc_json = {
        "schema_version": "orneur.foundation_evidence/1",
        "document": {"title": "ORNEUR foundation-model evidence reassessment (Workstream D)", "date": "2026-10-11", "status": "PROVISIONAL_NON_BINDING_NOT_A_SELECTION",
                     "banner": NOT_A_SELECTION, "branch": "claude/ws-d-foundation-evidence", "base_branch": D.BASE_BRANCH, "base_sha": D.BASE_SHA,
                     "supersedes": None, "does_not_modify": ["docs/orneur/phase-21/** (existing evidence)", "docs/orneur/acceptance/**", "docs/orneur/authorization/**", "orca/rse/**"]},
        "constraints_observed": {"training": False, "gpu": False, "model_downloads": False, "model_inference": False, "provider_inference_calls": False, "spending": False, "api_keys_used": False,
                                 "control_retry": False, "web_access": "public documentation only, read-only HTTP GET"},
        "claim_classes": CLAIM_CLASSES,
        "claim_class_definitions": {
            "DOCUMENTED_FACT": "Stated by a cited primary source (publisher repo at an exact commit, publisher licence text, technical report) or by a cited third-party page where labelled; includes values derived by trivial arithmetic only where marked.",
            "INDEPENDENTLY_REPRODUCED": "Reproduced by this repository's own persisted evidence (file cited) or re-derived offline from such evidence.",
            "UNTESTED_HYPOTHESIS": "Estimate, inference or judgment; never measured. Includes every memory/cost figure and rubric score.",
            "NOT_VERIFIED": "Could not be verified in this pass (tool limitation, HTTP/empty result, source not read)."},
        "license_statuses": ["GRANTED", "RESTRICTED_NONCOMMERCIAL", "REQUIRES_COUNSEL", "TAG_ONLY_UNVERIFIED"],
        "license_status_rules": "GRANTED requires a retrieved licence text whose sha256 and git blob sha1 are stored and re-verifiable offline; ambiguity is never converted to GRANTED. GRANTED is a statement about the licence text only, not a selection.",
        "retrieval_session": D.RETRIEVAL_SESSION,
        "candidates": [{k: v for k, v in c.items() if k != "estimates"} | {"estimates": {k: (v if not isinstance(v, float) else round(v, 6)) for k, v in c["estimates"].items()}} for c in cands],
        "identity_only_candidates": light,
        "outside_repo_shortlist_hypotheses": [],
        "outside_repo_shortlist_note": "No candidate outside the repo's own landscape/shortlist documents was added. Qwen3-14B and Qwen2.5-7B/14B appear only in the 2026-09-17 shortlist (not in the 2026-09-26 landscape's investigated set) and were not re-verified.",
        "existence_spotcheck": [dict(s, claim_class="DOCUMENTED_FACT", source_url=f"{D.HF}/api/models/{s['repo']}", retrieved_at="2026-10-11T19:27:00Z", revision=s["sha"]) for s in D.SPOTCHECK_EXISTENCE],
        "texts": [dict(v, key=f"{k[0]}/{k[1]}") for k, v in texts.items()],
        "reference_texts": built["ref_texts"],
        "weights_integrity_cross_check": {"description": "LFS sha256 + sizes in retrieved/<slug>/tree.json equal hf_lfs_sha256/bytes in the repo pre-cache manifests (checked by verify_evidence.py).",
                                          "manifests": {"qwen3-8b": D.REPO_EVIDENCE["qwen3_precache"], "mistral-nemo-instruct-2407": D.REPO_EVIDENCE["nemo_precache"], "phi-4": D.REPO_EVIDENCE["phi4_precache"]},
                                          "claim_class": "INDEPENDENTLY_REPRODUCED", "source_url": "repo:" + D.REPO_EVIDENCE["qwen3_precache"], "retrieved_at": T_REPO, "revision": BASE},
        "estimate_formulas": {
            "label": "ALL ESTIMATES - UNTESTED_HYPOTHESIS",
            "bf16_weights": "2 x P bytes (P = safetensors total)",
            "nf4_effective_bytes_per_param": "0.5 + 1/64 + 4/(64*256) = 0.5159 (4-bit code + 8-bit absmax per 64 values + fp32 constant per 256 blocks, i.e. double quantization)",
            "qlora_static": "(P - E) x 0.5159 + E x 2, E = vocab x hidden x (1 if tied else 2) (embeddings/lm_head kept BF16)",
            "lora_trainable": "per layer r x [(h+q) + 2(h+kv) + (q+h) + 3(h+I)], q=heads x head_dim, kv=kv_heads x head_dim, h=hidden, I=intermediate; times layers (all linear layers)",
            "lora_state": "trainable x 16 B (fp32 weight 4 + grad 4 + AdamW m,v 8); paged 8-bit AdamW would be ~10 B",
            "activations_ckpt": "L x 2 x s x h (checkpointed layer inputs, BF16) + 34 x s x h (one recomputed layer, flash attention) + s x V x 6 (BF16 logits + FP32 upcast)",
            "activations_no_ckpt": "L x 34 x s x h + s x V x 6",
            "peak": "static + lora_state(r=16) + activations + 1.5 GB allocator/context overhead; band 0.8x-1.4x (the package's own band)",
            "kv_cache_per_token": "2 x layers x kv_heads x head_dim x 2 B (BF16)",
            "serving_memory": "(2P + 8 sequences x 8192 x kv/token + 1.5 GB) / 0.9",
            "training_throughput": "tokens/s = u x 989e12 / (6 P), u in [0.15, 0.25]; USD/1M tokens = 3.95/3600/tokens_per_s x 1e6",
            "serving_throughput": "step = (2P + B x ctx x kv/token) / (3.35e12 x 0.5); tokens/s = B/step; B=16, ctx=2048; USD/1M = 3.95/3600/tokens_per_s x 1e6 / utilisation",
            "unit": "GB = 1e9 bytes",
            "sources_of_formulas": "Package s.4 (repo) for rates/throughput; activation accounting follows Korthikanti et al. 2022 (not re-fetched; assumption)",
        },
        "package_delta": delta,
        "license_findings": lic_rows,
        "provisional_ranking": ranking,
        "repo_claim_checks": rc,
        "changes_vs_package_2026_09_26": changes,
        "harness_errors": herr,
        "not_verified": not_verified,
    }
    md = render_md(doc_json, built, D, nm, order3, e, delta)
    return {"json": doc_json, "markdown": md}


def T_API_():
    return "2026-10-11T19:19:00Z"


# ---------------------------------------------------------------------------------------------------------
def render_md(J, built, D, nm, order3, e, delta):
    C = {c["id"]: c for c in J["candidates"]}
    cfg = {c["id"]: c["config"] for c in J["candidates"]}
    ids4 = order3 + ["unsloth-qwen2.5-3b-instruct"]
    L = []
    w = L.append
    w("# Foundation-Model Evidence Reassessment (Workstream D)")
    w("")
    w("Date: 2026-10-11 | Branch: `claude/ws-d-foundation-evidence` | Base: `claude/integration-candidate-1` @ `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d` | Machine-readable twin: `foundation_evidence.json` | Verifier: `scripts/foundation/verify_evidence.py`")
    w("")
    w("> **" + NOT_A_SELECTION + "**")
    w("> This is a PROVISIONAL, NON-BINDING evidence reassessment. The verdict of `GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26` (`FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL`) stands. No training, GPU, model download, inference or provider call occurred; sources were public documentation read through HTTP GET only.")
    w("")
    w("## 0. Evidence classes and how to read this file")
    w("")
    w("Every statement carries one class (full definitions in the JSON):")
    w("")
    w("- **DOCUMENTED_FACT** - cited primary source (publisher repo at exact commit SHA, licence text, technical report) or a labelled third-party page; each has `source_url`, `retrieved_at`, `revision`.")
    w("- **INDEPENDENTLY_REPRODUCED** - reproduced by this repository's own persisted evidence (file cited).")
    w("- **UNTESTED_HYPOTHESIS** - every estimate, cost figure and rubric judgment. Nothing here was measured.")
    w("- **NOT_VERIFIED** - could not be checked in this pass (section 14).")
    w("")
    w("Integrity method: Hugging Face exposes the git blob id of every file (tree API / ETag). Each recorded text (licence, `config.json`, `generation_config.json`, `tokenizer_config.json`) was reconstructed from the tool output and **stored only if its git blob sha1 equals the primary source's oid** (byte-exact proof). Weight-shard LFS sha256 values were cross-checked against the repo's own 2026-09-24 pre-cache manifests (0 mismatches). Details and tool limitations: JSON `retrieval_session`.")
    w("")
    w("## 1. Executive summary and surprises")
    w("")
    w("1. **No drift.** All 15 SHAs re-checked (3 controls, Qwen2.5-3B unsloth + upstream, 10 landscape-admitted dense models) equal the repo's recorded revisions; control weight hashes are identical to the repo manifests.")
    w("2. **Mistral-Nemo-Instruct-2407 has no LICENSE file** at the pinned commit (18-file tree). Apache-2.0 rests on the metadata tag and README prose. The package's `K: PASS` is therefore weaker than stated; this document records `REQUIRES_COUNSEL` and refuses `GRANTED`.")
    w("3. **The qwen-research licence is stricter than the repo summaries**: clause 4.b requires 'Built with Qwen' / 'Improved using Qwen' when the Materials *or their outputs* are used to train or improve a distributed AI model; 6.d is an indemnity; 8 is PRC law with Hangzhou courts. The current canonical base (unsloth mirror) also ships no LICENSE file of its own.")
    w("4. **Qwen3-8B and Phi-4 licence texts are byte-verified** (Apache-2.0 identical to the canonical text with `Copyright 2024 Alibaba Cloud`; MIT with CRLF, 1,105 bytes) - the first time the repo has hashed them.")
    w("5. **The three 'finalists' are `BASELINE_ONLY_CONTROL` in the repo's own landscape** (not admitted to the capability eval) and 'never a candidate finalist' in the Stage-0 matrix, yet the decision package uses them as the options. The documents disagree (RC-4).")
    w("6. **The control-program 'failures' are largely harness design**, reproducible offline: prompts do not request the format the acceptance demands, `max_tokens` is 1024 for Qwen3 but 64 for Nemo/Phi-4 (Phi-4's JSON smoke was cut off with `finish_reason=length`), and vLLM silently applies each model's `generation_config.json` defaults (section 12).")
    w("7. Nemo's template hash independently matches the repo's recorded hash; Qwen3's default template injects `<think>` handling; Qwen2.5's template injects a vendor identity system prompt ('You are Qwen, created by Alibaba Cloud').")
    w("")
    w("## 2. Candidates and depth of verification")
    w("")
    w("| Candidate | Role in repo | Repo @ exact revision (== HEAD on 2026-10-11) | Depth |")
    w("|---|---|---|---|")
    for i in ids4:
        c = C[i]
        w(f"| {nm[i]} | {c['role']} | `{c['repo']}` @ `{c['revision']}` | DEEP (primary files re-read, hashed) |")
    for c in J["identity_only_candidates"]:
        w(f"| {c['repo'].split('/')[1]} | landscape `GENESIS_EVAL_ADMITTED` | `{c['repo']}` @ `{c['revision']}` | IDENTITY_ONLY (sha, params, licence tag) |")
    w("")
    w("Upstream of the canonical base: `Qwen/Qwen2.5-3B-Instruct` @ `aa8e72537993ba99e69dfaafa59ed015b17504d1` (weights byte-identical to the unsloth repack). No candidate was `NOT_FOUND_AT_PRIMARY_SOURCE`; the odd-sounding out-of-scope names (Qwen3.8-27B, Mistral-Small-4-119B-2603, GLM-5.3-Flash) exist at the repo's recorded SHAs. **No candidate outside the repo's own documents was added** (Qwen3-14B and Qwen2.5-7B/14B appear only in the 2026-09-17 shortlist and were not re-verified).")
    w("")
    w("## 3. Architecture, parameters, context (DOCUMENTED_FACT from byte-verified `config.json`)")
    w("")
    w("| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B (unsloth) |")
    w("|---|---|---|---|---|")
    def rowf(label, f):
        w("| " + label + " | " + " | ".join(f(i) for i in ids4) + " |")
    rowf("Architecture class", lambda i: C[i]["claims"][3]["value"]["architectures"][0])
    rowf("Parameters (safetensors, BF16)", lambda i: f"{C[i]['params']:,}")
    rowf("Layers / hidden", lambda i: f"{cfg[i]['layers']} / {cfg[i]['hidden']}")
    rowf("Heads / KV heads (GQA)", lambda i: f"{cfg[i]['heads']} / {cfg[i]['kv_heads']} ({cfg[i]['heads'] // cfg[i]['kv_heads']}:1)")
    rowf("Head dim", lambda i: f"{cfg[i]['head_dim']}" + (" (derived)" if cfg[i]["head_dim_source"].startswith("DERIVED") else ""))
    rowf("MLP intermediate", lambda i: f"{cfg[i]['intermediate']:,}")
    rowf("Vocabulary", lambda i: f"{cfg[i]['vocab']:,}")
    rowf("Tied embeddings", lambda i: str(cfg[i]['tied']))
    rowf("rope_theta", lambda i: f"{cfg[i]['rope_theta']:,}")
    rowf("config max_position_embeddings", lambda i: f"{cfg[i]['max_pos']:,}")
    w("| Vendor-stated native context | 32,768 (131,072 with YaRN; card explains 40,960 reservation) | 128k trained (card) | 16K (card), no extension | 32,768 full / 8,192 generation (card intro also says '128K', unsupported by config) |")
    w("")
    w("## 4. Tokenizer and chat template (hashes of the exact template text)")
    w("")
    w("| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B (unsloth) |")
    w("|---|---|---|---|---|")
    tt = {k[0]: v for k, v in built["texts"].items() if k[1] == "chat_template.jinja.txt"}
    w("| Template sha256 | `{}` | `{}` | `{}` | `{}` |".format(*[tt[i]["sha256"] for i in ids4]))
    w("| Template bytes | {} | {} | {} | {} |".format(*[tt[i]["bytes"] for i in ids4]))
    w("| Format | ChatML `<\\|im_start\\|>`/`<\\|im_end\\|>` | `[INST]...[/INST]`, system prepended to last user turn, strict alternation | `<\\|im_start\\|>role<\\|im_sep\\|>...<\\|im_end\\|>` | ChatML + **default system prompt injected** |")
    w("| Thinking / mode switch | `enable_thinking` (default on), `/think` `/no_think`; empty `<think>` block when off | none | none | none |")
    w("| Tool-call format | `<tool_call>` JSON | `[AVAILABLE_TOOLS]`/`[TOOL_CALLS]`, 9-char ids | none | `<tool_call>` JSON |")
    w("| EOS / pad / BOS | `<\\|im_end\\|>` / `<\\|endoftext\\|>` / none | ids eos=2, bos=1; **no pad token defined** | `<\\|im_end\\|>` / `<\\|dummy_85\\|>` / `<\\|endoftext\\|>` | `<\\|im_end\\|>` / `<\\|vision_pad\\|>` / none |")
    w("| Tokenizer files | tokenizer.json (BPE, 151,936) | tokenizer.json **and** tekken.json | tokenizer.json (GPT2Tokenizer) | tokenizer.json |")
    w("| Vendor sampling guidance | thinking 0.6/0.95/20 (no greedy); non-thinking 0.7/0.8/20 | temperature 0.3 | none (widget temp 0) | gen. config 0.7/0.8/20, rep. penalty 1.05 |")
    w("")
    w("Nemo's template text was read from the Hugging Face model API at HEAD (== pinned SHA); its sha256 equals the hash the repo recorded from its cached snapshot (RC-12). The repo's root-cause work shows that on transformers 5.16.1 the presence of `tekken.json` makes `AutoTokenizer` return a backend without a chat template (HE-5).")
    w("")
    w("## 5. Licence text identity and commercial findings")
    w("")
    w("| Candidate | Status | Licence text in repo? | sha256 of retrieved text | Git blob sha1 (== HF oid) |")
    w("|---|---|---|---|---|")
    for i in ids4:
        l = C[i]["license"]
        if l["text"]:
            w(f"| {nm[i]} | **{l['license_status']}** ({l['license_id']}) | {'yes (upstream repo; the unsloth mirror has none)' if i.startswith('unsloth') else 'yes'} | `{l['text']['sha256']}` | `{l['text']['git_blob_sha1']}` |")
        else:
            w(f"| {nm[i]} | **{l['license_status']}** ({l['license_id']}) | **no LICENSE file** | none (reference Apache text hash `{l['reference_text_not_a_repo_file']['sha256'][:16]}...` is not a repo file) | n/a |")
    w("")
    w("`GRANTED` means only that the licence text was retrieved, byte-verified and hashed. It is not a selection and not legal advice.")
    w("")
    w("### Commercial-licence findings table")
    w("")
    w("`REQUIRES_COUNSEL` = ambiguous or unresolved by the text.")
    w("")
    w("| Candidate | Topic | Finding | Status | Counsel | Clause |")
    w("|---|---|---|---|---|---|")
    for r in J["license_findings"]:
        w("| {} | {} | {} | {} | {} | {} |".format(r["candidate"], r["topic"], r["finding"].replace("|", "/"), r["permission_status"], "**REQUIRES_COUNSEL**" if r["requires_counsel"] else "", r["clause"] or ""))
    w("")
    w("## 6. Memory estimates (ALL UNTESTED_HYPOTHESIS)")
    w("")
    w("Formulas (JSON `estimate_formulas`): BF16 weights `2P`; QLoRA static `(P-E)*0.5159 + 2E` (E = embeddings incl. untied lm_head); LoRA trainable `r*[(h+q)+2(h+kv)+(q+h)+3(h+I)]*layers`; optimizer state 16 B per trainable parameter (fp32 weight+grad+AdamW m,v); activations with gradient checkpointing `L*2*s*h + 34*s*h + s*V*6` bytes (batch 1, flash-attention), without `L*34*s*h + s*V*6`; peak = static + optimizer + activations + 1.5 GB, band 0.8x-1.4x (the package's band). GB = 1e9 bytes.")
    w("")
    w("| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B |")
    w("|---|---|---|---|---|")
    def rowe(label, f):
        w("| " + label + " | " + " | ".join(f(e[i]) for i in ids4) + " |")
    rowe("BF16 weights (GB)", lambda x: gb(x["bf16_weights_bytes"]))
    rowe("QLoRA static, NF4 + BF16 embeddings (GB)", lambda x: gb(x["nf4_static_bytes"]))
    rowe("LoRA r=16 trainable params (M) / optimizer state (GB)", lambda x: f"{x['lora_r16_params'] / 1e6:.1f} / {x['lora_r16_state_bytes_adamw_fp32'] / GB:.2f}")
    rowe("LoRA r=64 trainable params (M) / optimizer state (GB)", lambda x: f"{x['lora_r64_params'] / 1e6:.1f} / {x['lora_r64_state_bytes_adamw_fp32'] / GB:.2f}")
    rowe("Activations s=2048, ckpt / no ckpt (GB)", lambda x: f"{x['act_s2048_ckpt_bytes'] / GB:.1f} / {x['act_s2048_noshckpt_bytes'] / GB:.1f}")
    rowe("Activations s=4096, ckpt / no ckpt (GB)", lambda x: f"{x['act_s4096_ckpt_bytes'] / GB:.1f} / {x['act_s4096_noshckpt_bytes'] / GB:.1f}")
    rowe("QLoRA peak s=2048, ckpt (GB, band)", lambda x: f"{x['peak_s2048_ckpt_bytes'] / GB:.1f} ({x['peak_s2048_ckpt_range_bytes'][0] / GB:.1f}-{x['peak_s2048_ckpt_range_bytes'][1] / GB:.1f})")
    rowe("QLoRA peak s=4096, ckpt (GB, band)", lambda x: f"{x['peak_s4096_ckpt_bytes'] / GB:.1f} ({x['peak_s4096_ckpt_range_bytes'][0] / GB:.1f}-{x['peak_s4096_ckpt_range_bytes'][1] / GB:.1f})")
    rowe("QLoRA peak s=2048, NO ckpt (GB)", lambda x: f"{x['peak_s2048_noshckpt_bytes'] / GB:.1f}")
    rowe("QLoRA peak s=4096, NO ckpt (GB)", lambda x: f"{x['peak_s4096_noshckpt_bytes'] / GB:.1f}")
    rowe("KV cache per token (KiB, BF16)", lambda x: f"{x['kv_bytes_per_token_bf16'] / 1024:.0f}")
    rowe("KV cache per 8k sequence (GB)", lambda x: f"{x['kv_bytes_8k_seq'] / GB:.2f}")
    rowe("Serving GPU memory, batch 8 x 8k ctx (GB) / class", lambda x: f"{x['serve_bf16_gpu_memory_needed_bytes_batch8_ctx8k'] / GB:.1f} / {gpu_class_(x['serve_bf16_gpu_memory_needed_bytes_batch8_ctx8k'])}")
    rowe("4-bit serving weights, 4.5 bit/param (GB, hypothesis)", lambda x: gb(x["serve_4bit_weights_bytes_hypothesis"]))
    w("")
    w("**Delta to the 2026-09-26 package** (both estimates; this pass derives activations explicitly):")
    w("")
    w("| Candidate | QLoRA static pkg -> now | Peak 2k pkg -> now | Peak 4k pkg -> now | BF16 pkg -> now | KV 8k pkg -> now | LoRA r16 (M) pkg -> now |")
    w("|---|---|---|---|---|---|---|")
    for d_ in delta:
        f = lambda k: f"{d_[k]['package']} -> {d_[k]['this_pass']}"
        w(f"| {nm[d_['candidate']]} | {f('qlora_static_GB')} | {f('qlora_peak_2048_GB')} | {f('qlora_peak_4096_GB')} | {f('bf16_weights_GB')} | {f('kv_8k_GB')} | {f('lora_r16_trainable_M')} |")
    w("")
    w("Reading: KV, BF16 and LoRA parameter counts reproduce the package exactly; static and peak differ by a few percent to ~20% (activation accounting) and stay inside the package's +/-40% band. Without gradient checkpointing the Nemo and Phi-4 peaks already exceed a 24 GB card at s=2048 (26.6 / 27.1 GB) and Qwen3-8B grows from 20.4 GB (s=2048) to 32.5 GB (s=4096); every figure remains an estimate and no run has validated any of them.")
    w("")
    w("## 7. Hardware compatibility, serving engines, quantisation")
    w("")
    w("- **BF16 / Ampere+ (DOCUMENTED_FACT):** BF16 needs compute capability >= 8.0; vLLM rejects BF16 on a Tesla T4 (cc 7.5) - [vllm#1157](https://github.com/vllm-project/vllm/issues/1157). On a T4 the model would run FP16 (numerics NOT tested here) or 4-bit. BF16 weights vs a 16 GB T4: Qwen3-8B 16.4 GB, Nemo 24.5 GB, Phi-4 29.3 GB do not fit; Qwen2.5-3B 6.2 GB fits (ESTIMATE).")
    w("- **vLLM (DOCUMENTED_FACT, docs tool-extracted):** `Qwen3ForCausalLM`, `Phi3ForCausalLM`, `Qwen2ForCausalLM` listed with LoRA and PP marks. `MistralForCausalLM`: listed in the repo's 2026-09-26 collection; the LoRA mark was not captured today (NOT_VERIFIED). Repo-observed under vLLM 0.29.0 / transformers 5.16.1: Qwen3 and Phi-4 served on the canonical configuration; Nemo only with `--tokenizer-mode mistral`.")
    w("- **Ollama (third-party registry):** `qwen3:8b` Q4_K_M; `mistral-nemo` default tag 7.1 GB (its page claims a '1000K' context, contradicting the vendor's 128k - not adopted); `phi4` 14B 16k. Qwen3's card states Ollama, LM Studio, MLX-LM, llama.cpp and KTransformers support Qwen3.")
    w("- **llama.cpp:** only the Qwen3 card statement; Nemo/Phi-4/Qwen2.5-3B NOT_VERIFIED. **Other quantised artifacts:** NOT_VERIFIED.")
    w("")
    w("## 8. Serving-cost hypotheses (UNTESTED_HYPOTHESIS)")
    w("")
    w("Assumptions (stated, not measured): H100 80 GB at the repo's persisted list rate USD 3.95/h (2,844 USD/month always-on, reproducing the package), decode memory-bandwidth-bound at an assumed 3.35 TB/s and 50% efficiency, 16 concurrent sequences, average context 2,048, no prefill or scheduling overhead. Cost per 1M output tokens = rate / (tokens/s x 3600) x 1e6, divided by the fraction of paid hours actually serving.")
    w("")
    w("| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B |")
    w("|---|---|---|---|---|")
    w("| Tokens/s (aggregate) | " + " | ".join(f"{e[i]['serve_model']['tokens_per_s']:.0f}" for i in ids4) + " |")
    for u in (1.0, 0.3, 0.1):
        w(f"| USD / 1M output tokens at {int(u * 100)}% utilisation | " + " | ".join(f"{e[i]['serve_model']['usd_per_1M_output_tokens_at_full_utilisation'] / u:.2f}" for i in ids4) + " |")
    w("| QLoRA tokens/s on 1 H100 (15-25% of 989 TFLOP/s) | " + " | ".join(f"{e[i]['qlora_tokens_per_s_range'][0]:.0f}-{e[i]['qlora_tokens_per_s_range'][1]:.0f}" for i in ids4) + " |")
    w("| USD / 1M training tokens | " + " | ".join(f"{e[i]['usd_per_1M_train_tokens_range'][0]:.2f}-{e[i]['usd_per_1M_train_tokens_range'][1]:.2f}" for i in ids4) + " |")
    w("")
    w("The dominant uncertainty is utilisation: at low utilisation an always-on GPU costs an order of magnitude more per token than the full-utilisation figure; the package's conclusion (scale-to-zero or 4-bit small-GPU serving regardless of base) is unchanged.")
    w("")
    w("## 9. Published benchmarks and their limitations (vendor-reported; none reproduced)")
    w("")
    w("| Benchmark | Qwen3-8B thinking | Qwen3-8B non-thinking | Qwen2.5-3B-Instruct (Qwen3 report baseline) |")
    w("|---|---|---|---|")
    for k in D.QWEN3_8B_THINKING:
        w(f"| {k} | {D.QWEN3_8B_THINKING[k]} | {D.QWEN3_8B_NONTHINKING[k]} | {D.QWEN25_3B_NONTHINKING_IN_QWEN3_REPORT[k]} |")
    w("")
    w("Phi-4 (model card, OpenAI simple-evals): " + ", ".join(f"{k} {v}" for k, v in D.PHI4_README_SIMPLE_EVALS.items()) + ". Mistral-Nemo (model card): " + ", ".join(f"{k} {v}%" for k, v in D.NEMO_README_BENCH.items()) + ".")
    w("")
    w("Limitations that apply to every number above: (1) VENDOR_REPORTED - the publisher chose benchmarks, prompts, harness and decoding (Qwen3: thinking up to 32,768 output tokens, temp 0.6; non-thinking temp 0.7 with presence penalty 1.5); (2) public benchmarks may be contaminated and the corpora are not inspectable from outside (Phi-4 trains on synthetic 'textbook-like' data and states a June-2024 cutoff; Qwen3 and Nemo disclose no data sources); (3) harness differences make cross-vendor comparison unsound - Phi-4's own card notes simple-evals' strict formatting penalises Llama; Nemo's card gives no harness and does not say whether the numbers are base or instruct; (4) Qwen3 and Qwen2.5 rows were taken through the tool's PDF query extraction; (5) none measures ORNEUR's contract-style exact-output, JSON-schema or refusal/evidence behaviour, which is what the frozen eval must test; (6) the Qwen2.5-3B column is a baseline inside a competing model's report, not a Qwen2.5 card result.")
    w("")
    w("Multilingual: Qwen3 '100+ languages and dialects' (MMMLU-14 74.4/66.9); Nemo en/fr/de/es/it/pt/ru/zh/ja with per-language MMLU 59.0-64.6; Phi-4 'primarily English', multilingual ~8% and 'not intended to support multilingual use'; Qwen2.5-3B '29+ languages'. Safety: Qwen3 and Qwen2.5-3B cards publish no safety evaluation; Nemo states 'no moderation mechanisms'; Phi-4 describes SFT + iterative DPO safety post-training and Microsoft AIRT red-teaming but its card contains no numbers (they are in the technical report, not re-read).")
    w("")
    w("## 10. Known fine-tuning / deployment issues")
    w("")
    w("Repo control program (INDEPENDENTLY_REPRODUCED): Qwen3-8B attempt 5 PASS/FAIL/PASS (served; `2 + 3 = 5`); Nemo attempts 1-2 HTTP 400 template resolution, attempt 3 (native tokenizer mode) FAIL x3 (verbose prose); Phi-4 attempt 1 PASS/FAIL/FAIL (C truncated at 64 tokens). No control is RUNTIME_QUALIFIED; capability is UNPROVEN. These are response-format results, not capability evidence (package s.1).")
    w("")
    w("Public trackers (DOCUMENTED_FACT, excerpts only): [vllm#7739](https://github.com/vllm-project/vllm/issues/7739) Nemo + `--tokenizer-mode mistral` HTTP 400 (fixed in 2024 vLLM); HF [Nemo discussion 14](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/discussions/14) (system role in template) and [61](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/discussions/61) (alternation error after tool use); [unsloth#2771](https://github.com/unslothai/unsloth/issues/2771) completion-only training with Qwen3; [Unsloth Phi-4 write-up](https://unsloth.ai/blog/phi4) pad/eos bug history; NVIDIA Automodel tracker lists Phi-4 PEFT fused-QKV splitting.")
    w("")
    w("## 11. Provisional ranking (NON-BINDING, NOT A SELECTION)")
    w("")
    w("> " + J["provisional_ranking"]["statement"])
    w("")
    w("Gates (pre-registered A, B, K):")
    w("")
    w("| Candidate | A architecture | B memory | K licence |")
    w("|---|---|---|---|")
    for i in ids4:
        g = J["provisional_ranking"]["gates"][i]
        w(f"| {nm[i]} | {g['A']['result']} | {g['B']['result']} | **{g['K']['result']}** - {g['K']['basis']} |")
    w("")
    w("Criteria (weights from the package; 100 total over F-R):")
    w("")
    w("| ID | Criterion | Weight | State | Qwen3-8B | Nemo | Phi-4 |")
    w("|---|---|---|---|---|---|---|")
    sc = {r["candidate"]: r["scores"] for r in J["provisional_ranking"]["candidate_scores"]}
    for c in J["provisional_ranking"]["criteria"]:
        if c["kind"] == "gate":
            continue
        cells = [str(sc[i][c["id"]]) if c["id"] in sc[i] else "NOT_EVALUATED" for i in order3]
        w(f"| {c['id']} | {c['name']} | {c['weight']} | {c['evaluation_state']} | " + " | ".join(cells) + " |")
    w("")
    w("| Documented-subset total (max 24 of 100) | " + " | ".join(f"{nm[r['candidate']]} {r['documented_subset_points']}" for r in J["provisional_ranking"]["candidate_scores"]) + " |")
    w("|---|---|")
    w("")
    w("Rubrics: " + " ".join(f"**{k}** - {v}" for k, v in J["provisional_ranking"]["scoring_rubric"].items()))
    w("")
    w("Qwen2.5-3B-Instruct is **excluded from weighted scoring** (gate K FAIL: non-commercial licence). The ten IDENTITY_ONLY landscape models are not scored. Capability criteria F, G, H, I and also J, M, N, Q, R are **NOT_EVALUATED**: they need the frozen evaluation and pilot (package s.5). The subset totals are not a lead under the pre-registered rule (>= 5 weighted points AND a paired-bootstrap CI excluding 0) and must not be read as a recommendation.")
    w("")
    w("## 12. Reproducible harness errors in the control program (diagnose / propose only; nothing re-run)")
    w("")
    w("| ID | Finding | Evidence | Proposed fix (NOT applied) | Offline? | Needs owner authorization / re-pin |")
    w("|---|---|---|---|---|---|")
    for h in J["harness_errors"]:
        w("| {} | **{}** - {} | {} | {} | {} | {} |".format(h["id"], h["title"], h["observed"].replace("|", "/"), h["claim_class"] + ": " + h["source_url"], h["proposed_fix_not_applied"].replace("|", "/"), "yes" if h["reproducible_without_provider_run"] else "no", "yes" if h["requires_owner_authorization_or_repin"] else "no"))
    w("")
    w("These proposals respect the frozen prohibition on further control retries: they concern offline replay, protocol re-authoring and evidence-schema changes; none triggers a provider run.")
    w("")
    w("## 13. What changed vs the 2026-09-26 package")
    w("")
    for c in J["changes_vs_package_2026_09_26"]:
        w(f"- **{c['id']}** ({c['claim_class']}): {c['statement']}")
    w("")
    w("### Repo claims checked against primary sources")
    w("")
    w("| ID | Verdict | Statement |")
    w("|---|---|---|")
    for c in J["repo_claim_checks"]:
        w(f"| {c['id']} | **{c['verdict']}** | {c['statement'].replace('|', '/')} ({c['claim_class']}) |")
    w("")
    w("## 14. NOT_VERIFIED")
    w("")
    for c in J["not_verified"]:
        w(f"- {c['id']}: {c['statement']}")
    w("")
    w("## 15. Landscape-admitted dense models (identity only, not scored)")
    w("")
    w("| Model | Revision | Params | Licence tag | Licence status here | Note |")
    w("|---|---|---|---|---|---|")
    for c in J["identity_only_candidates"]:
        l = c["license"]
        note = [x for x in c["claims"] if x["topic"] == "notes"][0]["statement"]
        w(f"| `{c['repo']}` | `{c['revision'][:12]}` | {c['params']:,} | {l['license_id']} | {l['license_status']} | {note} |")
    w("")
    w("These were re-checked for SHA/parameter/licence-tag drift only; architecture rows reuse the repo's 2026-09-26 collection of the same revision. Hybrid-attention and multimodal checkpoints (Qwen3.5, Gemma 4) carry the runtime caveats the repo landscape already records.")
    w("")
    w("## 16. How to verify (offline)")
    w("")
    w("```")
    w("python3 scripts/foundation/verify_evidence.py          # schema, hashes, licence rules, ranking guards; no network")
    w("python3 scripts/foundation/build_evidence.py           # regenerate JSON + this report from evidence_data.py")
    w("pytest tests/test_foundation_evidence_schema.py")
    w("```")
    w("")
    return "\n".join(L) + "\n"


def gpu_class_(b):
    g = b / GB
    for c in (16, 24, 40, 48, 80):
        if g <= c:
            return f"{c}GB-class"
    return ">80GB"
