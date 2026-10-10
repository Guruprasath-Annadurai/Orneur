#!/usr/bin/env python3
"""Deterministic validator for the ORNEUR master acceptance graph.

NON_NORMATIVE. Does not authorize provisioning, purchase, secrets, corpus
generation, qualification, model selection, GPU, spend, or training.
Does not edit RSE-ARCH-1.2.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "docs" / "orneur" / "acceptance" / "register_graph.json"
MD_PATH = ROOT / "docs" / "orneur" / "ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md"
LEDGER_PATH = ROOT / "docs" / "orneur" / "acceptance" / "acceptance_ledger.json"
TRUST_PATH = ROOT / "docs" / "orneur" / "acceptance" / "reviewer_trust.json"
FOUNDER_ROOT_PATH = ROOT / "docs" / "orneur" / "acceptance" / "founder_root_keys.json"
BOOTSTRAP_PATH = ROOT / "docs" / "orneur" / "acceptance" / "BOOTSTRAP_ROOT_KEY.json"
CHECKPOINT_PATH = ROOT / "docs" / "orneur" / "acceptance" / "TRUST_CHECKPOINT.json"
CHECKPOINT_PIN_PATH = ROOT / "docs" / "orneur" / "acceptance" / "TRUST_CHECKPOINT_PIN.json"
EMPTY_LEDGER = "[]\n"
EMPTY_TRUST = '{\n  "git_sha": "",\n  "generation": 0,\n  "entries": [],\n  "signature_hex": ""\n}\n'
EMPTY_FOUNDER_ROOT = '{\n  "git_sha": "",\n  "generation": 0,\n  "roots": [],\n  "signature_hex": ""\n}\n'
EMPTY_BOOTSTRAP = '{\n  "public_key_hex": ""\n}\n'
EMPTY_CHECKPOINT = (
    '{\n  "subject_sha": "",\n  "generation": 0,\n  "trust_snapshot_hash": "",\n'
    '  "root_state_hash": "",\n  "previous_checkpoint_hash": "",\n  "signature_hex": ""\n}\n'
)
EMPTY_CHECKPOINT_PIN = '{\n  "pinned_checkpoint_hash": ""\n}\n'

BANNED = (
    "RSE_MASTER_BLOCK_1_ACCEPTED",
    "IMP_2_ACCEPTED_FOR_SOFTWARE_GATE",
    "IMP_3_ACCEPTED_FOR_SOFTWARE_GATE",
    "IMP_4_ACCEPTED_FOR_SOFTWARE_GATE",
)

ROLES = {
    "CURSOR",
    "CLAUDE",
    "ANTIGRAVITY",
    "PRODUCT_MANAGEMENT",
    "FOUNDER",
    "UNRESOLVED_EXTERNAL",
    "RECORDED_ON_MAIN",
}

STATUSES = {
    "NOT_VERIFIABLE",
    "PRESENT_ON_MAIN",
    "UNMERGED_NOT_ACCEPTED",
    "NOT_AUTHORIZED",
    "NOT_STARTED",
    "DESIGNED_ONLY",
    "OPEN_PR_UNREVIEWED",
    "NOT_ACCEPTED",
    "BLOCKED_LICENSE",
    "NOT_A_SELECTION",
    "OPEN",
    "HISTORICAL",
    "EXTERNALLY_REPORTED",
}

EVIDENCE_STATES = {
    "NONE",
    "SOURCE_VERIFIED",
    "SHA_CI_PASSED",
    "PULL_REQUEST_CI_PASSED",
    "CI_IN_PROGRESS",
    "SHA_CI_PASSED_ON_ANCESTOR",
    "EXTERNALLY_REPORTED",
}

DENOMINATORS = {
    "PRE_TRAINING",
    "APPLICATION",
    "POST_TRAINING_LAUNCH",
    "EXECUTION",
    "NONE",
}

CI_PR8 = (
    "PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run "
    "37884389862 success. GitHub reviews length 0. The run is not row acceptance."
)

# Checked live on 2026-10-09 before this remediation was published.
# Pull-request runs are recorded and are not used as exact-SHA proof.
RECONCILIATION = {
    "checked": "2026-10-09",
    "main": "464b602f3f259b56f139c3304828baa660e6b860",
    "reviewed_register_sha": "de7188d76a8db633886812277272c8e51080e11e",
    "reviewed_register_push_run": {
        "id": 37972785102,
        "event": "push",
        "conclusion": "success",
        "sha": "de7188d76a8db633886812277272c8e51080e11e",
    },
    "pulls": [
        {
            "number": 8,
            "head": "da567d927b61c41e253b42732aad249b5fdbb104",
            "base": "main",
            "reviews": 0,
            "runs": [
                {"id": 37884389862, "event": "push", "conclusion": "success"},
            ],
        },
        {
            "number": 9,
            "head": "c127780abbe6790cd0ba76beb6755615752af9b2",
            "base": "cursor/rse-master-imp2-imp4-c04e",
            "reviews": 0,
            "runs": [
                {"id": 37889422564, "event": "push", "conclusion": "success"},
            ],
        },
        {
            "number": 10,
            "head": "f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb",
            "base": "cursor/rse-block1-owner-ratification-c04e",
            "reviews": 0,
            "runs": [
                {"id": 37893124711, "event": "push", "conclusion": "success"},
                {
                    "id": 37892311517,
                    "event": "push",
                    "conclusion": "failure",
                    "sha": "518488dbd404cc4b3cac662b30237a93bedba5bf",
                    "note": "Earlier head. Not evidence for f424dbf.",
                },
            ],
        },
        {
            "number": 11,
            "head": "6e30dd9f31215f0046a2612653794291ada6688f",
            "base": "main",
            "reviews": 0,
            "runs": [
                {
                    "id": 37921622633,
                    "event": "pull_request",
                    "conclusion": "success",
                    "note": "No push run was listed for this head. Not exact-SHA proof.",
                },
            ],
        },
        {
            "number": 12,
            "head": "348fb882dce86d95b351a932a799a45d09f37940",
            "base": "claude/phase-a-assistant-baseline",
            "reviews": 0,
            "runs": [
                {
                    "id": 37973804538,
                    "event": "push",
                    "conclusion": "success",
                    "sha": "348fb882dce86d95b351a932a799a45d09f37940",
                },
                {
                    "id": 37972182734,
                    "event": "push",
                    "conclusion": "success",
                    "sha": "63ece2a5dd673d69a06effdf766d7046f1973fc8",
                    "note": "Ancestor of the live head. Not proof of 348fb882.",
                },
            ],
        },
        {
            "number": 13,
            "head": "0328123361756b9732fc57886754d6d09c4b9c46",
            "cited_ancestor": "cd95befd196c57d1885be208532a1c9a32991a39",
            "base": "main",
            "reviews": 0,
            "runs": [
                {
                    "id": 37973767347,
                    "event": "push",
                    "conclusion": "success",
                    "sha": "0328123361756b9732fc57886754d6d09c4b9c46",
                },
                {
                    "id": 37973770477,
                    "event": "pull_request",
                    "conclusion": "success",
                    "sha": "0328123361756b9732fc57886754d6d09c4b9c46",
                    "note": "Pull-request run. Not exact-SHA proof.",
                },
                {
                    "id": 37972786151,
                    "event": "push",
                    "conclusion": "success",
                    "sha": "cd95befd196c57d1885be208532a1c9a32991a39",
                    "note": "Ancestor named by the remediation request. The live head is newer.",
                },
            ],
        },
        {
            "number": 14,
            "head": "55d133c94be65b1d9b843afa3da2f9a2cc4eb701",
            "base": "cursor/rse-block1-governance-closure-c04e",
            "reviews": 0,
            "note": "Three Phase 0 notes. Preserved. This register does not replace them.",
        },
        {
            "number": 15,
            "head_before_this_remediation": "de7188d76a8db633886812277272c8e51080e11e",
            "base": "cursor/rse-phase0-register-c04e",
            "reviews": 0,
        },
    ],
}


def R(
    id,
    *,
    cls="MANDATORY",
    frozen="",
    denominator="PRE_TRAINING",
    counts=True,
    event="READINESS",
    founder_act="NONE",
    canonical="",
    covered=(),
    freeze_row=None,
    source="",
    evidence="",
    current="",
    states=(),
    status="NOT_STARTED",
    impl="CURSOR",
    reviewer="CLAUDE",
    founder="NOT_REQUIRED",
    escalation="",
    depends=(),
    exit="",
    rationale="",
    cross=(),
    artifact_class="",
):
    return {
        "id": id,
        "class": cls,
        "frozen_class": frozen,
        "denominator": denominator,
        "counts": counts,
        "event": event,
        "founder_act": founder_act,
        "canonical_id": canonical,
        "covered_by": list(covered),
        "freeze_row": freeze_row,
        "pass_rule": "OWN_EVIDENCE",
        "evidence_key": id if counts else (canonical or id),
        "source": source,
        "evidence_required": evidence,
        "current_evidence": current,
        "evidence_states": list(states),
        "status": status,
        "implementation_owner": impl,
        "independent_reviewer": reviewer,
        "founder_approval": founder,
        "escalation": escalation,
        "depends_on": list(depends),
        "exit": exit,
        "rationale": rationale,
        "cross_refs": list(cross),
        "artifact_class": artifact_class,
    }


def software(id, prop, evidence, status="UNMERGED_NOT_ACCEPTED", depends=("G3",), extra=""):
    current = CI_PR8
    if extra:
        current = extra + " " + CI_PR8
    return R(
        id,
        frozen="M",
        source="RSE12_06 §4",
        evidence=evidence,
        current=current,
        states=("SHA_CI_PASSED",),
        status=status,
        impl="CURSOR",
        reviewer="CLAUDE",
        founder="NOT_REQUIRED",
        depends=depends,
        exit="A reviewer accepts this row's own artifact on the merged SHA.",
        cross=(prop,),
    )


def hw(
    id,
    freeze_row,
    frozen,
    *,
    counts=True,
    canonical="",
    covered=(),
    cls=None,
    evidence="",
    depends=("G4",),
    status="NOT_STARTED",
    founder="NOT_REQUIRED",
    rationale="",
    cross=(),
):
    if cls is None:
        cls = "NONBLOCKING" if frozen in {"P", "O"} else "MANDATORY"
    denom = "PRE_TRAINING" if counts else "NONE"
    return R(
        id,
        cls=cls,
        frozen=frozen,
        denominator=denom,
        counts=counts,
        canonical=canonical,
        covered=covered,
        freeze_row=freeze_row,
        source="RSE12_06 §1",
        evidence=evidence,
        current="No serial, quote, photograph, purchase, or firmware record for this property is in the tree.",
        states=("NONE",),
        status=status if counts else "NOT_STARTED",
        impl="UNRESOLVED_EXTERNAL",
        reviewer="CLAUDE",
        founder=founder,
        escalation=(
            "Founder names a P1 operator who is not the reviewer. "
            "No purchase is authorized by this row."
        ),
        depends=() if not counts else depends,
        exit="The named artifact exists and a reviewer accepts that artifact.",
        rationale=rationale,
        cross=cross,
    )


def build_nodes():
    nodes = []
    nodes.append(
        R(
            "G1",
            frozen="M",
            source="RSE12_06 §7 step 1 and §8",
            evidence="An architecture review, stored where a later reader can open it, by a person who did not author RSE-ARCH-1.2.",
            current="No such review file was found in this pass.",
            states=("NONE",),
            status="NOT_VERIFIABLE",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="UNRESOLVED_EXTERNAL",
            escalation="Name a reviewer who did not author RSE-ARCH-1.2, and record where the review is stored.",
            depends=(),
            exit="The review is identifiable without a verdict slogan.",
            rationale="The audit is an input to readiness. It is not the training authorization.",
        )
    )
    nodes.append(
        R(
            "G2",
            frozen="M",
            source="RSE12_06 §7 step 2",
            evidence="Freeze commit on canonical main, re-checked against Manifest V3 at integration time.",
            current="Main is 464b602f3f259b56f139c3304828baa660e6b860. Manifest V3 was not edited.",
            states=("SOURCE_VERIFIED",),
            status="PRESENT_ON_MAIN",
            impl="RECORDED_ON_MAIN",
            reviewer="PRODUCT_MANAGEMENT",
            depends=("G1",),
            exit="The integration check still matches the manifest.",
        )
    )
    nodes.append(
        R(
            "G3",
            frozen="M",
            source="RSE12_06 §7 steps 4 and 5",
            evidence="Independent code review of the merged software SHA, plus that SHA's own main push CI.",
            current="IMP-2/3/4 code is unmerged on PR #8. " + CI_PR8 + " RSE_MASTER_BLOCK_1_EVIDENCE.md on that SHA still says independent acceptance is pending.",
            states=("SHA_CI_PASSED",),
            status="UNMERGED_NOT_ACCEPTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G2",),
            exit="The merged SHA has its own main push CI and a review that is not a copied slogan.",
        )
    )
    nodes.append(
        R(
            "G4",
            frozen="M",
            source="RSE12_06 §7 step 6",
            founder_act="INTERMEDIATE",
            evidence="A founder purchase authorization and a named hardware selection.",
            current="The freeze states nothing is bought. NO_HARDWARE_PURCHASE_AUTHORIZED stands.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("G3",),
            exit="The authorization names the machines. This register does not purchase them.",
            rationale="Intermediate founder act. Purchase is an input to hardware evidence. It is not contingent on full readiness.",
        )
    )
    nodes.append(
        R(
            "G5",
            frozen="M",
            source="RSE12_06 §7 step 7",
            founder_act="INTERMEDIATE",
            evidence="Provisioning and key-creation authorization, then a ceremony record that contains no secret.",
            current="Locks return false. No ceremony record.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("G4",),
            exit="A founder act changes the authorization. This register does not create a secret.",
            rationale="Intermediate founder act. Key creation is an input to later hardware tests. It is not the training authorization.",
        )
    )

    # Real-hardware C rows and Witness properties feed the acceptance run.
    # They do not depend on G6, or the run would cycle.
    real_hw = [
        "C08",
        "C22",
        "C23",
        "C24",
        "C25",
        "C26",
        "C27",
        "C28",
        "C29",
        "C30",
        "C31",
        "C32",
        "C33",
        "C34",
        "C35",
        "C36",
        "C37",
        "C38",
        "C44",
        "HW-01",
        "HW-02",
        "HW-03",
        "HW-06",
        "HW-08",
        "HW-11",
        "HW-16",
        "HW-18",
        "HW-19",
        "HW-20",
        "HW-21",
        "HW-24",
        "HW-FORGE",
    ]
    nodes.append(
        R(
            "G6",
            frozen="M",
            source="RSE12_06 §7 step 8",
            evidence="One acceptance-run record that cites each real-hardware artifact by its own id. The record is not a copy of those artifacts.",
            current="Synthetic tests only. No hardware log.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            founder="NOT_REQUIRED",
            escalation="Founder names the operator who runs the acceptance. The reviewer is not that operator. Purchase stays on G4.",
            depends=("G5", *real_hw),
            exit="The run record exists. Each cited row still needs its own accepted artifact.",
        )
    )
    nodes.append(
        R(
            "G7",
            frozen="M",
            source="RSE12_06 §7 step 9",
            evidence="Custody record for a Crown machine that is not the daily driver, with its own serial.",
            current="No Crown inventory.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            founder="NOT_REQUIRED",
            escalation="Founder names the Crown custodian. No purchase is authorized here. Purchase stays on G4.",
            depends=("G6",),
            exit="The Crown serial is recorded and differs from Witness and Forge.",
            cross=("HW-01", "HW-FORGE", "C38"),
        )
    )
    nodes.append(
        R(
            "G8",
            frozen="M",
            source="RSE12_06 §7 step 10; CORPUS_GENERATION_AUTHORIZATION.json",
            founder_act="INTERMEDIATE",
            evidence="A founder corpus-generation grant, and nothing else. The grant does not create a corpus and does not carry a corpus digest.",
            current="CORPUS_GENERATION_AUTHORIZATION.json status is NOT_AUTHORIZED. No protected corpus exists.",
            artifact_class="founder-corpus-grant",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("G7",),
            exit="The founder changes that file. This register does not.",
            rationale="Intermediate founder act. The corpus grant is an input to later data rows. It is not contingent on full training readiness.",
        )
    )
    nodes.append(
        R(
            "G9",
            frozen="M",
            source="RSE12_06 §7 step 11",
            evidence="A second Crown milestone: an independent dedicated Crown device, with its own serial, before qualification or training.",
            current="Not started.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            founder="NOT_REQUIRED",
            escalation="Founder names the device. This row does not purchase it. Purchase stays on G4.",
            depends=("G8",),
            exit="The second Crown serial is recorded.",
        )
    )
    nodes.append(
        R(
            "G10",
            frozen="M",
            source="RSE12_06 §7 step 12",
            evidence="A chamber-design review that names the design SHA and the tests the reviewer ran.",
            current="QUALIFICATION_RUNNER_REGISTRY.json state is REGISTERED_NOT_AUTHORIZED.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="CURSOR",
            reviewer="CLAUDE",
            founder="NOT_REQUIRED",
            depends=("G9",),
            exit="The reviewer accepts the design record. Runner authorization is QUAL-1, a separate artifact.",
        )
    )
    nodes.append(
        R(
            "G11",
            frozen="M",
            source="RSE12_06 §7 step 13",
            evidence="A P2 gate record that names the environment. Attestation, egress, and counter logs stay on their own rows.",
            current="R-EXF in RSE12_06 §5 says egress control blocks training authorization. No environment is named.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            escalation="Founder names the P2 operator. No provider is selected here.",
            depends=("G10", "P2-1", "P2-2", "C46", "C47"),
            exit="The gate record exists. P2-1, P2-2, C46, and C47 remain separately accepted.",
        )
    )
    nodes.append(
        R(
            "G12",
            frozen="M",
            source="RSE12_06 §7 step 14, infrastructure clause",
            evidence="A training-infrastructure record: pinned software identity, dry-run log pointer, and the P2 environment id.",
            current="training_authorized() returns false. No infrastructure record.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G11", "TRAIN-1", "TRAIN-2"),
            exit="The infrastructure record exists. GPU permission is FINAL-2, after readiness.",
            rationale="Technical infrastructure only. GPU and spend permission are contingent on readiness and are not inputs to this row.",
        )
    )

    sw = [
        ("C01", "Refusal log from the signed registry path showing an unregistered id refused."),
        ("C02", "Consumer refusal record for a stale or unknown registry."),
        ("C04", "Refusal record for a ceiling above the policy cap."),
        ("C05", "Validator output refusing a confusable name."),
        ("C09", "Journal record of challenge reuse refused."),
        ("C10", "Refusal record showing a set-back clock does not extend a consumed challenge."),
        ("C11", "State log showing no ACTIVE state before a witnessed checkpoint."),
        ("C12", "Verify log of a witness cosignature, including a forged ack refused."),
        ("C13", "Witness log refusing a fork or a smaller tree. A synthetic fence is not this artifact."),
        ("C14", "Refusal record for a bundle that lacks a witnessed result."),
        ("C17", "Vector test for enc validity and the zero-shared-secret abort."),
        ("C18", "Test log reproducing the RFC 9180 vectors used by this profile."),
        ("C19", "Per-case verdicts for missing, duplicate, reordered, extra, truncated, and foreign frames."),
        ("C20", "Resolver log refusing an unknown or revoked sender."),
        ("C21", "Verify log showing a bad origin signature is rejected before key use."),
        ("C45", "Transition log refusing an impossible lifecycle edge. Class K remains a separate decision."),
    ]
    for cid, evidence in sw:
        nodes.append(software(cid, cid, evidence))
    nodes.append(
        software(
            "C15",
            "C15",
            "Journal replay report for a crash at each specified step, including the C26 power-cut report.",
            depends=("G3", "C26"),
        )
    )
    nodes.append(
        R(
            "C03",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Verify log of a canonical registry update with two distinct owner tokens.",
            current="IMP-1 registry code is on main. Distinct hardware tokens are not issued. " + CI_PR8,
            states=("SOURCE_VERIFIED", "SHA_CI_PASSED"),
            status="DESIGNED_ONLY",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G3", "C08"),
            exit="The verify log shows two distinct tokens. C08 remains its own row.",
        )
    )
    nodes.append(
        software(
            "C06",
            "C06",
            "Rendered-card digest showing the consumer rendered the received signed bytes.",
            status="DESIGNED_ONLY",
        )
    )
    nodes.append(
        software(
            "C07",
            "C07",
            "Typed-entry record for the SAS and the Intent Sheet fields.",
            status="DESIGNED_ONLY",
        )
    )
    nodes.append(
        R(
            "C08",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Verify log from two distinct physical tokens. One token used twice is refused.",
            current="No tokens issued. REAL_HW cell is tokens.",
            states=("NONE",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="CLAUDE",
            founder="REQUIRED",
            depends=("G5",),
            exit="Two physical tokens produce the log. This row does not create a secret by itself.",
            rationale="Intermediate token ceremony after G5. It is not the training authorization.",
            founder_act="INTERMEDIATE",
        )
    )
    nodes.append(
        R(
            "C16",
            frozen="M",
            source="RSE12_06 §4",
            evidence="A second codec implementation, not Cursor's, agrees on the OCR1 verdict vector.",
            current="Freeze maturity is structural codec evidence only. " + CI_PR8,
            states=("SHA_CI_PASSED",),
            status="DESIGNED_ONLY",
            impl="CURSOR",
            reviewer="UNRESOLVED_EXTERNAL",
            escalation="Name a second codec implementer who is not Cursor.",
            depends=("G3",),
            exit="The second implementation's digest matches on the merged SHA.",
        )
    )
    nodes.append(
        R(
            "C44",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Verify log that one token cannot satisfy a two-token class.",
            current="No tokens issued.",
            states=("NONE",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="CLAUDE",
            founder="REQUIRED",
            depends=("C08",),
            exit="The single-token refusal is logged on hardware tokens.",
            founder_act="INTERMEDIATE",
            rationale="Intermediate token test after C08. The refusal log is its own artifact. It is not the training authorization.",
        )
    )

    hw_c = [
        ("C22", "Mount and key-state record showing the vault stayed locked through key-absent phase 1.", ("G5", "HW-02")),
        ("C23", "Sandbox policy dump from a real checker showing no key, no network, and bounded I/O.", ("G5", "HW-01")),
        ("C24", "TPM policy test: image PCR and PCR 7 named, wrong PCR denied, wrong PIN denied, altered UKI denied.", ("G4", "HW-02")),
        ("C25", "TPM NV denial record for an older image, including the counter value.", ("G4", "HW-03")),
        ("C26", "Per-step power-cut report for the NV update. A simulator report is only the partial credit the freeze allows.", ("G4", "HW-03")),
        ("C28", "Firmware key list showing only owner Secure Boot keys.", ("G4", "HW-02")),
        ("C29", "Offline quote record against the pinned attestation key, including measured PCR values.", ("G4", "HW-02")),
        ("C30", "Kernel report that IOMMU groups are enforced, or that the named DMA buses are absent.", ("G4",)),
        ("C31", "Kernel log of USB default-deny with the single allow-listed medium class.", ("G4",)),
        ("C32", "Enumeration digest showing radios absent or hardware-off.", ("G4",)),
        ("C33", "Measured netdev digest showing no usable network device per link class.", ("G4", "HW-16")),
        ("C34", "Platform report for management engine or out-of-band management. A network-capable controller that cannot be disabled disqualifies the machine.", ("G4",)),
        ("C35", "Firmware settings record: setup password, locked boot order, internal drive only, network boot disabled.", ("G4",)),
        ("C36", "LUKS2 header check.", ("G4", "HW-02")),
        ("C37", "Storage scan report, before and after, with a planted marker found by the negative test.", ("G6",)),
        ("C38", "Crown isolation inventory digest with its own serial.", ("G4",)),
    ]
    for cid, evidence, deps in hw_c:
        # C37's negative scan needs the acceptance machines, but depending on G6 would cycle
        # because G6 depends on C37. Depend on G5 instead; the scan is still its own artifact.
        if cid == "C37":
            deps = ("G5", "HW-01")
        frozen = "M"
        if cid == "C30":
            frozen = "M: IOMMU mandatory when a DMA bus exists; D if such a bus exists and no IOMMU"
        if cid == "C34":
            frozen = "M; D if present, network-capable and not disableable"
        nodes.append(
            R(
                cid,
                frozen=frozen,
                source="RSE12_06 §4",
                evidence=evidence,
                current="No hardware report for this control.",
                states=("NONE",),
                status="NOT_STARTED",
                impl="UNRESOLVED_EXTERNAL",
                reviewer="CLAUDE",
                founder="NOT_REQUIRED",
                escalation="Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4.",
                depends=deps,
                exit="The artifact named above is accepted on its own.",
            )
        )
    nodes.append(
        R(
            "DEC-K",
            frozen="M",
            source="RSE12_06 C27; ACR-B1-2 deferral on PR #10",
            founder_act="INTERMEDIATE",
            evidence="A founder decision that class K recovery stays deferred, and that C27 therefore stays unmet, until a later architecture-change authorization exists.",
            current="Approval 3 defers ACR-B1-2. Class K returns UNSUPPORTED_CURRENT_MILESTONE. No implementation is authorized by this row.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=(),
            exit="The decision is recorded. C27 is still a separate mandatory row.",
            rationale="Intermediate decision. It does not implement class K and it does not remove C27 from the denominator.",
        )
    )
    nodes.append(
        R(
            "C27",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Re-enrolment records for a TPM or board replacement that refuse a lower-generation restore, produced by an authorized class-K path.",
            current="Class K is unsupported. No re-enrolment record.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            founder="REQUIRED",
            escalation="Do not implement class K under this row. Wait for a founder architecture-change authorization that is not this register.",
            depends=("DEC-K", "G5", "HW-02"),
            exit="The re-enrolment record exists after class K is authorized elsewhere. A decision record alone does not pass C27.",
            founder_act="INTERMEDIATE",
            rationale="Intermediate recovery evidence. It waits on DEC-K and does not itself authorize class K. It is not the training authorization.",
        )
    )
    nodes.append(
        R(
            "C39",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Two independent build reports whose digests match, compared on Crown.",
            current="No pair of build reports was produced in this pass.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="CLAUDE",
            reviewer="ANTIGRAVITY",
            depends=("SUP-1",),
            exit="The comparison record is accepted. SUP-1's harness log is not this comparison.",
        )
    )
    nodes.append(
        R(
            "C40",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Floor-check log refusing a lower card and a lower sealed floor.",
            current="Software floors are not a sealed Crown card.",
            states=("NONE",),
            status="DESIGNED_ONLY",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("C41",),
            exit="The floor-check log is accepted together with a sealed floor. C41 remains separate.",
        )
    )
    nodes.append(
        R(
            "C41",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Signed comparison receipt containing both floor-card serials.",
            current="No floor card.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("G7",),
            exit="The receipt names both serials.",
            founder_act="INTERMEDIATE",
            rationale="Intermediate custody act. It is not the training authorization.",
        )
    )
    nodes.append(
        R(
            "C42",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Refusal log for a recovery kit below the effective floor.",
            current="No recovery kit.",
            states=("NONE",),
            status="DESIGNED_ONLY",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("C40",),
            exit="The below-floor kit is refused in the log.",
        )
    )
    nodes.append(
        R(
            "C43",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Epoch checkpoint and LUKS slot rotation record after recovery-media theft response.",
            current="No ceremony record.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("G5",),
            exit="The epoch record exists and contains no secret.",
            founder_act="INTERMEDIATE",
            rationale="Intermediate ceremony. It is not the training authorization.",
        )
    )
    nodes.append(
        R(
            "C46",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Qualification bit-budget counter log from the chamber.",
            current="Not implemented. Table marks P2 and future.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G10",),
            exit="The budget log is accepted. C47 is a separate monotonicity artifact.",
        )
    )
    nodes.append(
        R(
            "C47",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Evidence that restoring qualification state does not refund the budget. The freeze types this UNP.",
            current="Not implemented.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            escalation="Name the chamber operator. A synthetic counter is not this artifact.",
            depends=("G10",),
            exit="The monotonicity evidence is accepted.",
        )
    )
    nodes.append(
        software(
            "C48",
            "C48",
            "Refusal records showing a T-complete record cannot authorize W, and W-complete cannot authorize D.",
            status="DESIGNED_ONLY",
        )
    )
    nodes.append(
        R(
            "C49",
            frozen="M",
            source="RSE12_06 §4",
            evidence="Registry entry containing the foundation provenance digests before any use.",
            current="No approved foundation entry. model_selection_authorized() returns false.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            founder="REQUIRED",
            depends=("MODEL-1",),
            exit="The registry entry is accepted. The selection record remains MODEL-1.",
            founder_act="INTERMEDIATE",
            rationale="Intermediate registry entry after selection. It is not the training authorization.",
        )
    )
    nodes.append(
        R(
            "C50",
            frozen="M",
            source="RSE12_06 §3 and §4",
            evidence="A drill measurement of boots, media moves, witness trips, token touches, and typed SAS counts.",
            current="Budget numbers exist in the freeze. No drill record.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            founder="NOT_REQUIRED",
            escalation="Founder names the operator who runs the drill. Purchase stays on G4.",
            depends=("G7",),
            exit="The measurement is recorded. A sentence that a drill happened is not the measurement.",
        )
    )

    # §1 properties. Aliases share the canonical evidence key and do not count.
    nodes.append(
        hw(
            "HW-01",
            1,
            "M",
            evidence="Witness serial recorded on a machine used for nothing else, different from the Crown serial and the Forge serial.",
            cross=("G7", "HW-FORGE"),
        )
    )
    nodes.append(
        hw(
            "HW-02",
            2,
            "D",
            evidence="TPM 2.0 capability record for the Witness. Absence disqualifies the machine.",
        )
    )
    nodes.append(
        hw(
            "HW-03",
            3,
            "M",
            evidence="TPM NV capability record showing a counter index and policy comparison on NV.",
            cross=("C25", "C26"),
        )
    )
    nodes.append(
        hw(
            "HW-04",
            4,
            "M",
            counts=False,
            canonical="C28",
            evidence="Same artifact as C28.",
            rationale="Frozen §1 row 4 is the same firmware key list as C28. One achievement.",
            cross=("C28",),
        )
    )
    nodes.append(
        hw(
            "HW-05",
            5,
            "M",
            counts=False,
            canonical="C29",
            evidence="Same artifact as C29.",
            rationale="Frozen §1 row 5 is evidenced by the offline quote on C29. One achievement.",
            cross=("C29",),
        )
    )
    nodes.append(
        hw(
            "HW-06",
            6,
            "M",
            evidence="Measurement record showing the role code and its version inside the measured image.",
        )
    )
    nodes.append(
        hw(
            "HW-07",
            7,
            "M",
            counts=False,
            canonical="C24",
            evidence="Same artifact as C24.",
            rationale="Frozen §1 row 7 is the PCR policy tested on C24. One achievement.",
            cross=("C24",),
        )
    )
    nodes.append(
        hw(
            "HW-08",
            8,
            "M",
            evidence="Build record of the owner-signed unified kernel image and the boot measurement that matches it.",
        )
    )
    nodes.append(
        hw(
            "HW-09",
            9,
            "M",
            counts=False,
            canonical="C36",
            evidence="Same artifact as C36.",
            rationale="Frozen §1 row 9 is the LUKS2 header check on C36. One achievement.",
            cross=("C36",),
        )
    )
    nodes.append(
        hw(
            "HW-10",
            10,
            "M",
            counts=False,
            canonical="C24",
            evidence="Same artifact as C24.",
            rationale="Frozen §1 row 10 is the TPM-bound release plus PIN tested on C24. One achievement.",
            cross=("C24",),
        )
    )
    nodes.append(
        hw(
            "HW-11",
            11,
            "M",
            evidence="Custody record that a paper recovery passphrase exists, with no secret and no passphrase value in git.",
            depends=("G5",),
        )
    )
    nodes.append(
        hw(
            "HW-12",
            12,
            "M",
            counts=False,
            canonical="C35",
            evidence="Same artifact as C35.",
            rationale="Frozen §1 row 12 is the firmware settings record on C35, including network boot disabled. One achievement.",
            cross=("C35",),
        )
    )
    nodes.append(
        hw(
            "HW-13",
            13,
            "M; D if present, network-capable and not disableable",
            counts=False,
            canonical="C34",
            evidence="Same artifact as C34.",
            rationale="Frozen §1 row 13 is the platform report on C34. One achievement. The disqualifying clause stays on C34.",
            cross=("C34",),
        )
    )
    nodes.append(
        hw(
            "HW-14",
            14,
            "M: IOMMU mandatory when a DMA bus exists; D if such a bus exists and no IOMMU",
            counts=False,
            canonical="C30",
            evidence="Same artifact as C30.",
            rationale="Frozen §1 row 14 is the DMA report on C30. One achievement. The disqualifying clause stays on C30.",
            cross=("C30",),
        )
    )
    nodes.append(
        hw(
            "HW-15",
            15,
            "M",
            counts=False,
            canonical="C32",
            evidence="Same artifact as C32.",
            rationale="Frozen §1 row 15 is the radio enumeration on C32. One achievement.",
            cross=("C32",),
        )
    )
    nodes.append(
        hw(
            "HW-16",
            16,
            "M",
            evidence="Firmware or physical record that the wired port is unused, blocked, or firmware-disabled.",
            cross=("C33",),
        )
    )
    nodes.append(
        hw(
            "HW-17",
            17,
            "M",
            counts=False,
            canonical="C31",
            evidence="Same artifact as C31.",
            rationale="Frozen §1 row 17 is the USB policy log on C31. One achievement.",
            cross=("C31",),
        )
    )
    nodes.append(
        hw(
            "HW-18",
            18,
            "M",
            evidence="Update log showing firmware and OS updates came only from the owner-approved offline registry.",
        )
    )
    nodes.append(
        hw(
            "HW-19",
            19,
            "M",
            evidence="Registry record of the approved artifacts and the offline distribution used to install them.",
            depends=("G2",),
        )
    )
    nodes.append(
        hw(
            "HW-20",
            20,
            "M (custody)",
            evidence="Custody record for the Witness location. Seals are HW-20P and do not satisfy this row.",
        )
    )
    nodes.append(
        hw(
            "HW-20P",
            20,
            "P (seals)",
            counts=False,
            cls="NONBLOCKING",
            evidence="Photograph of tamper-evident seals. Preferred only.",
            founder="NOT_REQUIRED",
            rationale="Frozen class P. Omitted from the mandatory denominator. Custody remains HW-20.",
        )
    )
    nodes.append(
        hw(
            "HW-21",
            21,
            "M",
            evidence="Capacity record for RAM, storage, and CPU against the largest planned bundle and the sandboxed checker.",
        )
    )
    nodes.append(
        hw(
            "HW-22",
            22,
            "P",
            counts=False,
            cls="NONBLOCKING",
            evidence="TPM RNG availability note.",
            founder="NOT_REQUIRED",
            rationale="Frozen class P. Omitted from the mandatory denominator.",
        )
    )
    nodes.append(
        hw(
            "HW-23",
            23,
            "O",
            counts=False,
            cls="NONBLOCKING",
            evidence="Record of discrete TPM versus firmware TPM. Neither is claimed immune.",
            founder="NOT_REQUIRED",
            rationale="Frozen class O. Omitted from the mandatory denominator.",
        )
    )
    nodes.append(
        hw(
            "HW-24",
            24,
            "M",
            evidence="Inventory showing the Witness has no GPU.",
        )
    )
    nodes.append(
        hw(
            "HW-25",
            25,
            "O",
            counts=False,
            cls="NONBLOCKING",
            evidence="Cold spare serial, if a spare is kept.",
            founder="NOT_REQUIRED",
            rationale="Frozen class O. Omitted from the mandatory denominator.",
        )
    )
    nodes.append(
        R(
            "HW-FORGE",
            cls="MANDATORY",
            frozen="M",
            source="RSE12_06 §6 P1 definition: Crown + Forge + independent Witness",
            evidence="Forge serial different from the Witness serial and the Crown serial.",
            current="No Forge inventory.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            founder="NOT_REQUIRED",
            escalation="Founder names the Forge custodian. No purchase is authorized here. Purchase stays on G4.",
            depends=("G4",),
            exit="The Forge serial is recorded.",
            cross=("HW-01", "G7"),
        )
    )

    nodes.append(
        R(
            "SUP-1",
            frozen="M",
            source="RSE12_06 C39; docker/rse_synthetic_integration_lab and infra/tier0-local/docker",
            evidence="Two independent build digests of the training image, plus the lock used to build them.",
            current=(
                "PR #13 live head 0328123361756b9732fc57886754d6d09c4b9c46. "
                "Push run 37973767347 succeeded for that head. "
                "Pull-request run 37973770477 also succeeded and is not the exact-SHA proof. "
                "Ancestor cd95befd196c57d1885be208532a1c9a32991a39 push run 37972786151 succeeded. "
                "GitHub reviews length 0. A green harness run is not two independent training-image digests."
            ),
            states=("SHA_CI_PASSED", "SHA_CI_PASSED_ON_ANCESTOR"),
            status="NOT_STARTED",
            impl="CLAUDE",
            reviewer="ANTIGRAVITY",
            depends=("G3",),
            exit="C39's comparison exists. A harness repair log does not pass C39.",
        )
    )
    nodes.append(
        R(
            "SUP-2",
            cls="MANDATORY",
            frozen="M",
            denominator="APPLICATION",
            event="APPLICATION",
            source=".github/workflows/test.yml job container-build",
            evidence="A green exact-SHA production-container job for the application SHA under claim.",
            current="The job is in the workflow file. A green run of the register branch does not qualify the application image.",
            states=("SOURCE_VERIFIED",),
            status="NOT_ACCEPTED",
            impl="CLAUDE",
            reviewer="ANTIGRAVITY",
            depends=(),
            exit="The reviewer names the application SHA and the job log.",
            rationale=(
                "The production container serves the assistant. orca/train does not import orca.serve. "
                "The first Genesis training run is not defined to boot this image. "
                "Mandatory for the application denominator. Excluded from pre-training readiness."
            ),
        )
    )
    nodes.append(
        R(
            "SUP-3",
            frozen="M",
            source="requirements/rse.txt on PR #10",
            evidence="Hash-locked install of the RSE extra and a fail-closed audit log of that lock, on the SHA that is merged to main.",
            current=(
                "On f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb, push run 37893124711 "
                "job RSE dependency lock and vulnerability scan reported no known vulnerabilities for that lock. "
                "Not on main. The base job does not include pyhpke."
            ),
            states=("SHA_CI_PASSED",),
            status="UNMERGED_NOT_ACCEPTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G3",),
            exit="The same job is green on the merge commit on main.",
        )
    )
    nodes.append(
        R(
            "SUP-4",
            cls="NONBLOCKING",
            frozen="",
            denominator="NONE",
            counts=False,
            event="APPLICATION",
            source="Workflow comment naming chromadb PYSEC-2026-311 and diskcache PYSEC-2026-2447",
            evidence="A fresh advisory decision.",
            current="Disclosed on the base install. chromadb is not in the train extra. diskcache is a base dependency.",
            states=("SOURCE_VERIFIED",),
            status="OPEN",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=(),
            exit="A separate advisory decision.",
            rationale=(
                "Not an RSE12_06 control. chromadb is in the memory and docs extras, not the train extra. "
                "Excluded from the pre-training denominator. The advisories stay open."
            ),
        )
    )
    nodes.append(
        R(
            "P2-1",
            frozen="M",
            source="RSE12_06 §2 cloud-provider row and §7 step 13",
            evidence="Attestation evidence for a named training environment. No provider is selected by this row.",
            current="The freeze marks provider root of trust UNPROVEN.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            escalation="Founder names the environment operator. No provider contract is authorized here.",
            depends=("G10",),
            exit="The attestation package is accepted.",
        )
    )
    nodes.append(
        R(
            "P2-2",
            frozen="M",
            source="RSE12_06 §5 R-EXF",
            evidence="An egress test showing the training identity cannot open a forbidden path.",
            current="Residual text only.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G10",),
            exit="The egress test log is accepted.",
        )
    )
    nodes.append(
        R(
            "P2-3",
            cls="MANDATORY",
            frozen="M",
            denominator="NONE",
            counts=False,
            covered=("C46", "C47"),
            source="RSE12_06 C46 and C47",
            evidence="Covered by C46 and C47.",
            current="See those rows.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=(),
            exit="C46 and C47 each pass on their own artifacts.",
            rationale="Same controls as C46 and C47. Not a second achievement.",
        )
    )
    nodes.append(
        R(
            "P2-4",
            frozen="M",
            source="MODEL_EVAL_AUTHORIZATION.json",
            evidence="A training-environment test that a spend above the configured cap is refused. The cap value may remain 0.",
            current="max_spend_usd is 0. network_provider_inference_allowed is false. gpu_allowed is false.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G10",),
            exit="The refusal test is accepted. Raising the cap is FINAL-2.",
            rationale="The enforcement test is a readiness input. Permission to spend or to use a GPU is contingent on readiness.",
        )
    )

    nodes.append(
        R(
            "DATA-1",
            frozen="M",
            source="GENESIS_PRETRAINING_QUALIFICATION.md",
            evidence="A provenance manifest listing source, license, and per-record digest, bound to the creation digest from DATA-3. The founder grant is not this manifest.",
            current="The qualification note describes a small v1+v2+v3 set and a token proxy. That note is not a protected-corpus manifest and does not authorize training.",
            states=("SOURCE_VERIFIED",),
            status="NOT_ACCEPTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="PRODUCT_MANAGEMENT",
            escalation="Founder names who assembles the manifest. This row generates no corpus.",
            depends=("DATA-3",),
            exit="The manifest is accepted against the creation digest. G8 does not pass this row.",
            artifact_class="corpus-provenance-manifest",
        )
    )
    nodes.append(
        R(
            "DATA-2",
            frozen="M",
            source="RSE12_05 contamination oracle; RSE12_01 contamination_status_ref",
            evidence="A contamination and holdout-separation result bound to the creation digest and the holdout fingerprint set, with no item-level leak. The founder grant is not this result.",
            current="GENESIS_FRONTIER_HOLDOUT_SPEC.md says zero-contamination is not proven. No protected corpus exists to test.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("DATA-1", "DATA-3", "DATA-5", "QUAL-2"),
            exit="The oracle output is accepted. G8 does not pass this row.",
            artifact_class="contamination-holdout-separation",
        )
    )
    nodes.append(
        R(
            "DATA-3",
            frozen="M",
            source="RSE12_06 §6 real private corpus after P1; CORPUS_GENERATION_AUTHORIZATION.json is the grant, not the corpus",
            evidence="A protected-corpus creation record that names the corpus digest and the creating operator. The founder grant is not this record.",
            current="No creation record. CORPUS_GENERATION_AUTHORIZATION.json remains NOT_AUTHORIZED and contains no corpus.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="CLAUDE",
            escalation="Founder names the corpus operator after G8. This row does not generate a corpus and does not implement class K.",
            depends=("G8",),
            exit="The creation record exists. The grant alone leaves this row unmet.",
            artifact_class="protected-corpus-creation",
        )
    )
    nodes.append(
        R(
            "DATA-5",
            frozen="M",
            source="RSE12_06 §6 custody of the real private corpus",
            evidence="An independent custody and integrity receipt that re-hashes the protected corpus and names a custodian who is not the creator. The founder grant is not this receipt.",
            current="No protected corpus and no custody receipt.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="PRODUCT_MANAGEMENT",
            escalation="Founder names a custodian who did not create the corpus. This row does not generate a corpus.",
            depends=("DATA-3",),
            exit="The receipt matches the creation digest. Creation alone does not pass this row.",
            artifact_class="corpus-custody-integrity",
        )
    )
    nodes.append(
        R(
            "DATA-4",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            event="POST_TRAINING",
            source="Public dataset marketing claims",
            evidence="A published data card.",
            current="No trained model and no public card.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="PRODUCT_MANAGEMENT",
            reviewer="CLAUDE",
            depends=(),
            exit="The card is published after a model exists.",
            rationale="Public marketing after training. Excluded from pre-training readiness.",
        )
    )

    nodes.append(
        R(
            "MODEL-0",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            source="orca/registry/model_spec.py family genesis",
            evidence="The code pin, read from the file.",
            current=(
                "base_model unsloth/Qwen2.5-3B-Instruct, revision and tokenizer revision "
                "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0, license_name qwen-research, "
                "license_commercial_use RESTRICTED. model_selection_authorized() returns false."
            ),
            states=("SOURCE_VERIFIED",),
            status="NOT_A_SELECTION",
            impl="RECORDED_ON_MAIN",
            reviewer="PRODUCT_MANAGEMENT",
            depends=(),
            exit="A reader can open the pin. Selection is MODEL-1.",
            rationale="A source fact. Not a second selection achievement and not an authorization.",
        )
    )
    nodes.append(
        R(
            "MODEL-2R",
            frozen="M",
            source="GENESIS_BASE_MODEL_QUALIFICATION.md license section",
            founder_act="INTERMEDIATE",
            evidence="A founder scope record that the first run, when later authorized, is research or evaluation only under the qwen-research terms.",
            current=(
                "The qualification note quotes a non-commercial research license and says commercial release is blocked. "
                "It also says the term does not by itself block research or internal evaluation. "
                "No founder scope record exists. This row does not grant either scope."
            ),
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("MODEL-0",),
            exit="The research-only scope record exists. Commercial rights remain MODEL-2C.",
            rationale="Intermediate scope decision. Research-only training and commercial release are different rights. This row records only the research scope.",
        )
    )
    nodes.append(
        R(
            "MODEL-1",
            frozen="M",
            source="orca/registry/model_spec.py; model_selection_authorized()",
            founder_act="INTERMEDIATE",
            evidence="A founder selection record naming the repository and the exact revision. The code pin is not that record.",
            current="The pin in MODEL-0 is present. model_selection_authorized() returns false.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("MODEL-2R",),
            exit="The selection record exists and stays inside the research-only scope. It does not set training_authorized().",
            rationale="Intermediate selection. It is an input to readiness. It does not depend on the training lock.",
        )
    )
    nodes.append(
        R(
            "MODEL-2C",
            cls="MANDATORY",
            frozen="M",
            denominator="POST_TRAINING_LAUNCH",
            counts=True,
            event="POST_TRAINING",
            source="GENESIS_BASE_MODEL_QUALIFICATION.md commercial clause",
            evidence="A commercial grant from the rights holder, or a founder record that no commercial release will be made from this base.",
            current="The qualification note says commercial use of this base requires a license from Alibaba Cloud. No grant is in the tree.",
            states=("SOURCE_VERIFIED",),
            status="BLOCKED_LICENSE",
            impl="UNRESOLVED_EXTERNAL",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            escalation="The rights holder is outside this repository. Founder requests a commercial grant through the rights holder's own channel. This row does not send that request.",
            depends=(),
            exit="The commercial grant or the no-commercial-release record exists.",
            rationale=(
                "Commercial release rights are mandatory for a commercial launch. "
                "They are not required to compute research-training readiness. "
                "Excluded from the pre-training denominator. Not deleted."
            ),
        )
    )
    nodes.append(
        R(
            "MODEL-3",
            cls="MANDATORY",
            frozen="M",
            denominator="NONE",
            counts=False,
            canonical="C49",
            source="RSE12_06 C49",
            evidence="Same artifact as C49.",
            current="See C49.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=(),
            exit="C49 passes on its own registry entry.",
            rationale="Same control as C49. Not a second achievement.",
        )
    )
    nodes.append(
        R(
            "MODEL-4",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            source="GENESIS_STAGE0_LICENSE_MATRIX.md",
            evidence="Not a selection.",
            current="Other candidates are listed with license notes. The matrix says it is not legal advice and does not authorize a download.",
            states=("SOURCE_VERIFIED",),
            status="NOT_A_SELECTION",
            impl="RECORDED_ON_MAIN",
            reviewer="PRODUCT_MANAGEMENT",
            depends=(),
            exit="Readers use MODEL-1 for selection.",
            rationale="A survey. Not a selection and not a denominator row.",
        )
    )

    nodes.append(
        R(
            "QUAL-1",
            frozen="M",
            source="QUALIFICATION_RUNNER_REGISTRY.json",
            founder_act="INTERMEDIATE",
            evidence="Founder authorization of the qualification runner. The binding note is not that authorization.",
            current=(
                "State REGISTERED_NOT_AUTHORIZED. runner_class SELF_HOSTED_CPU. "
                "os_runtime says the local Mac is the canonical CPU runner. Network policy in the record is none."
            ),
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("G10",),
            exit="The founder changes the runner state. This register does not.",
            rationale="Intermediate runner authorization after the chamber design. It is not contingent on full training readiness.",
        )
    )
    nodes.append(
        R(
            "QUAL-2",
            frozen="M",
            source="eval_private/genesis_capability_eval_v1/holdout.jsonl and holdout_fingerprints.json",
            evidence="A failed read of the holdout by the training identity.",
            current="The paths exist. No isolation proof was run in this pass.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("QUAL-1", "P2-2"),
            exit="The failed-read log is accepted.",
        )
    )
    nodes.append(
        R(
            "QUAL-3",
            frozen="M",
            source="GENESIS_PRETRAINING_QUALIFICATION.md regression policy",
            evidence="Numeric thresholds frozen before any candidate result, for every category the policy says is critical and for the categories it leaves unset.",
            current="Critical categories are named. Numeric thresholds for the other categories are not set.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="PRODUCT_MANAGEMENT",
            reviewer="CLAUDE",
            depends=("G10",),
            exit="The threshold freeze is recorded before a candidate run.",
        )
    )
    nodes.append(
        R(
            "QUAL-4",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            event="POST_TRAINING",
            source="Public benchmark claims",
            evidence="A report that keeps the holdout out of marketing.",
            current="No finished model.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="PRODUCT_MANAGEMENT",
            reviewer="CLAUDE",
            depends=(),
            exit="The report exists after a model exists.",
            rationale="Public claims after training. Excluded from pre-training readiness.",
        )
    )

    nodes.append(
        R(
            "TRAIN-1",
            frozen="M",
            source="pyproject.toml extra train; orca/train",
            evidence="A hash lock of the train extra and one dry-run command pinned to a SHA.",
            current="The extra lists version ranges. No hash lock for the train extra was found. uv.lock is not what CI installs.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("G3",),
            exit="The lock and the command log name the same SHA.",
        )
    )
    nodes.append(
        R(
            "TRAIN-2",
            frozen="M",
            source="orca/rse/imp1/locks.py",
            evidence="A synthetic dry-run log showing corpus, qualification, model-selection, GPU, and training locks still false afterward.",
            current="No full-trainer dry-run log is in this pass.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="CLAUDE",
            depends=("TRAIN-1",),
            exit="The log shows the locks still false. The run does not flip them.",
        )
    )
    nodes.append(
        R(
            "TRAIN-3",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            source="docs/orneur/phase-0",
            evidence="Not used.",
            current="Historical notes say no training was started.",
            states=("SOURCE_VERIFIED",),
            status="HISTORICAL",
            impl="RECORDED_ON_MAIN",
            reviewer="PRODUCT_MANAGEMENT",
            depends=(),
            exit="Do not cite these notes as DATA-3.",
            rationale="Earlier product notes. Not this programme's corpus.",
        )
    )

    nodes.append(
        R(
            "AUTH-1",
            frozen="M",
            source="Founder budget approval, which is not a file yet",
            founder_act="INTERMEDIATE",
            evidence="A budget record with a number, a currency, and the founder's signature or equivalent.",
            current="No budget record found.",
            states=("NONE",),
            status="NOT_VERIFIABLE",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=(),
            exit="The record exists. Until then this row blocks a readiness percentage.",
            rationale="Intermediate budget act. It can exist before readiness is complete. It is not contingent on FINAL-1.",
        )
    )
    nodes.append(
        R(
            "APP-1",
            cls="MANDATORY",
            frozen="M",
            denominator="APPLICATION",
            event="APPLICATION",
            source="PR #11",
            evidence="Independent review of head 6e30dd9f31215f0046a2612653794291ada6688f for the streaming and error-leak fix, plus an exact-SHA push CI for that head.",
            current=(
                "Head unchanged. GitHub reviews length 0. "
                "Pull-request run 37921622633 succeeded. No push run was listed. "
                "This register did not read the diff."
            ),
            states=("PULL_REQUEST_CI_PASSED",),
            status="OPEN_PR_UNREVIEWED",
            impl="CLAUDE",
            reviewer="ANTIGRAVITY",
            depends=(),
            exit="Antigravity's report names the SHA and is stored as an artifact. A PR-body sentence is not that artifact.",
            rationale=(
                "Assistant HTTP and SSE behaviour. orca/train does not import orca.serve. "
                "Not required for the first Genesis training run. Mandatory in the application denominator."
            ),
        )
    )
    nodes.append(
        R(
            "APP-2",
            cls="MANDATORY",
            frozen="M",
            denominator="APPLICATION",
            event="APPLICATION",
            source="PR #12",
            evidence="Independent review of the live head for pool bounds, secret logging, and SSE diagnostics, plus that head's push CI.",
            current=(
                "Live head 348fb882dce86d95b351a932a799a45d09f37940. "
                "Push run 37973804538 succeeded for that head. "
                "Ancestor 63ece2a5dd673d69a06effdf766d7046f1973fc8 push run 37972182734 succeeded. "
                "GitHub reviews length 0. Diff not read."
            ),
            states=("SHA_CI_PASSED", "SHA_CI_PASSED_ON_ANCESTOR"),
            status="OPEN_PR_UNREVIEWED",
            impl="CLAUDE",
            reviewer="ANTIGRAVITY",
            depends=("APP-1",),
            exit="The retest report names 348fb882 or a later reviewed head.",
            rationale=(
                "Same public assistant path as APP-1. Not required for the first Genesis training run. "
                "Mandatory in the application denominator."
            ),
        )
    )
    nodes.append(
        R(
            "APP-3",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            event="POST_TRAINING",
            source="docs/LAUNCH_PLAN.md",
            evidence="Launch evidence for public claims.",
            current="Planning text only.",
            states=("SOURCE_VERIFIED",),
            status="NOT_STARTED",
            impl="PRODUCT_MANAGEMENT",
            reviewer="CLAUDE",
            depends=(),
            exit="After a trained model exists.",
            rationale="Public launch planning. Excluded from pre-training and from the application security denominator.",
        )
    )
    nodes.append(
        R(
            "EV-AG-APP",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            event="APPLICATION",
            source="Product Management remediation directive 2026-10-09",
            evidence="The Antigravity application retest report, including the SHA it tested and the result.",
            current=(
                "The directive states Antigravity previously retested the application. "
                "No report text, tested SHA, or result is in this repository. "
                "GitHub reviews on PR #11 and PR #12 have length 0. "
                "PR bodies are author narrative and are not this report."
            ),
            states=("EXTERNALLY_REPORTED",),
            status="EXTERNALLY_REPORTED",
            impl="ANTIGRAVITY",
            reviewer="PRODUCT_MANAGEMENT",
            escalation="Product Management places the report where a later reader can open it.",
            depends=(),
            exit="The stored report can be read. Until then APP-1 and APP-2 stay unreviewed.",
            rationale="External report locator. Not a GitHub approval, not a committed audit artifact, and not an acceptance.",
        )
    )
    nodes.append(
        R(
            "EV-AG-DOCKER",
            cls="NONBLOCKING",
            denominator="NONE",
            counts=False,
            event="APPLICATION",
            source="Product Management remediation directive 2026-10-09",
            evidence="The Antigravity Docker retest report, including the SHA it tested and the result.",
            current=(
                "The directive states Antigravity previously retested Docker. "
                "No report text, tested SHA, or result is in this repository. "
                "GitHub reviews on PR #13 have length 0. "
                "The PR body is the author's local log, not Antigravity's report."
            ),
            states=("EXTERNALLY_REPORTED",),
            status="EXTERNALLY_REPORTED",
            impl="ANTIGRAVITY",
            reviewer="PRODUCT_MANAGEMENT",
            escalation="Product Management places the report where a later reader can open it.",
            depends=(),
            exit="The stored report can be read. It does not pass SUP-1 or C39.",
            rationale="External report locator. Not a GitHub approval, not a committed audit artifact, and not an acceptance.",
        )
    )

    nodes.append(
        R(
            "R65",
            frozen="M",
            source="The founder's canonical 65 rules. No file in this tree contains that set.",
            evidence="The exact source text, founder-approved, then one child row per rule.",
            current="No source. No child rule is listed.",
            states=("NONE",),
            status="NOT_VERIFIABLE",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            escalation="Founder supplies the complete exact text. Do not paraphrase it.",
            depends=(),
            exit="Sixty-five child rows replace this placeholder after the source is approved.",
            rationale="Intermediate source requirement. The founder supplies the text before readiness can be complete. Child rules are not invented. A percentage stays unpublished while this row is NOT_VERIFIABLE. This row is not the training authorization.",
        )
    )

    # Placeholders filled after the other readiness ids are known.
    nodes.append(
        R(
            "FINAL-1",
            frozen="M",
            event="READINESS",
            founder_act="NONE",
            source="This register",
            evidence="An independent recomputation worksheet that lists every counted pre-training id and its own status.",
            current="Numerator is 0. G1, AUTH-1, and R65 are NOT_VERIFIABLE.",
            states=("NONE",),
            status="NOT_STARTED",
            impl="CURSOR",
            reviewer="PRODUCT_MANAGEMENT",
            founder="NOT_REQUIRED",
            depends=(),
            exit="The worksheet matches a fresh run of the validator. Founder authorization is still FINAL-2.",
        )
    )
    nodes.append(
        R(
            "FINAL-2",
            cls="MANDATORY",
            frozen="M",
            denominator="EXECUTION",
            counts=True,
            event="FOUNDER_AUTHORIZATION_GRANTED",
            founder_act="CONTINGENT",
            source="Founder execution authorization",
            evidence="One founder record naming the SHA, the dataset manifest, the foundation revision, the research-only scope, the spend cap, and the GPU permission.",
            current="Not present. gpu_allowed is false. max_spend_usd is 0. training_authorized() returns false.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=("FINAL-1",),
            exit="The record exists after FINAL-1. This register is not that record.",
            rationale="Contingent on readiness. Excluded from the readiness denominator so readiness can be computed before this authorization exists.",
        )
    )
    nodes.append(
        R(
            "EXEC-1",
            cls="MANDATORY",
            frozen="M",
            denominator="EXECUTION",
            counts=True,
            event="TRAINING_EXECUTION_ALLOWED",
            founder_act="CONTINGENT",
            source="orca/rse/imp1/locks.py and the authorization JSON files",
            evidence="A start record, distinct from FINAL-2, showing the locks and the authorization files agree with FINAL-2 and that a run was permitted to start.",
            current="model_selection_authorized, qualification_authorized, gpu_authorized, and training_authorized return false.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="CLAUDE",
            founder="REQUIRED",
            depends=("FINAL-2",),
            exit="The start record exists. Editing a lock to return true without FINAL-2 fails this row.",
            rationale="Contingent on founder authorization. A third event after readiness and after the grant.",
        )
    )
    nodes.append(
        R(
            "AUTH-2",
            cls="MANDATORY",
            frozen="M",
            denominator="NONE",
            counts=False,
            canonical="FINAL-2",
            event="FOUNDER_AUTHORIZATION_GRANTED",
            founder_act="CONTINGENT",
            source="MODEL_EVAL_AUTHORIZATION.json",
            evidence="Same artifact as FINAL-2.",
            current="gpu_allowed false. max_spend_usd 0. status NOT_AUTHORIZED.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="PRODUCT_MANAGEMENT",
            founder="REQUIRED",
            depends=(),
            exit="FINAL-2 carries the GPU and spend permission.",
            rationale="Contingent GPU permission. Same founder record as FINAL-2. Not a second achievement and not an input to G12.",
        )
    )
    nodes.append(
        R(
            "AUTH-3",
            cls="MANDATORY",
            frozen="M",
            denominator="NONE",
            counts=False,
            canonical="EXEC-1",
            event="TRAINING_EXECUTION_ALLOWED",
            founder_act="CONTINGENT",
            source="orca/rse/imp1/locks.py",
            evidence="Same artifact as EXEC-1.",
            current="The three authorization predicates return false.",
            states=("SOURCE_VERIFIED",),
            status="NOT_AUTHORIZED",
            impl="FOUNDER",
            reviewer="CLAUDE",
            founder="REQUIRED",
            depends=(),
            exit="EXEC-1 checks the locks.",
            rationale="Contingent execution check. Same artifact as EXEC-1. MODEL-1 does not depend on it.",
        )
    )

    by_id = {n["id"]: n for n in nodes}
    if len(by_id) != len(nodes):
        raise SystemExit("duplicate ids while building")
    readiness = sorted(
        n["id"]
        for n in nodes
        if n["denominator"] == "PRE_TRAINING" and n["counts"] and n["id"] != "FINAL-1"
    )
    by_id["FINAL-1"]["depends_on"] = readiness
    for node in nodes:
        if not node["artifact_class"]:
            node["artifact_class"] = node["evidence_key"]
    for node in nodes:
        if node["canonical_id"]:
            canonical = by_id[node["canonical_id"]]
            node["evidence_key"] = canonical["evidence_key"]
            node["artifact_class"] = canonical["artifact_class"]
    return nodes


def readiness_ids(nodes):
    return [
        n["id"]
        for n in nodes
        if n["denominator"] == "PRE_TRAINING" and n["counts"]
    ]


def validate(nodes):
    errors = []
    by_id = {}
    for node in nodes:
        if node["id"] in by_id:
            errors.append(f"duplicate id {node['id']}")
        by_id[node["id"]] = node
        if node["pass_rule"] != "OWN_EVIDENCE":
            errors.append(f"{node['id']} pass_rule")
        if node["status"] not in STATUSES:
            errors.append(f"{node['id']} status {node['status']}")
        if node["status"] == "ACCEPTED":
            errors.append(f"{node['id']} uses ACCEPTED")
        if node["implementation_owner"] not in ROLES:
            errors.append(f"{node['id']} owner")
        if node["independent_reviewer"] not in ROLES:
            errors.append(f"{node['id']} reviewer")
        if node["implementation_owner"] == node["independent_reviewer"]:
            if node["implementation_owner"] != "UNRESOLVED_EXTERNAL":
                errors.append(f"{node['id']} owner equals reviewer")
        if node["founder_approval"] not in {"REQUIRED", "NOT_REQUIRED"}:
            errors.append(f"{node['id']} founder_approval")
        if "UNRESOLVED_EXTERNAL" in {node["implementation_owner"], node["independent_reviewer"]}:
            if not node["escalation"]:
                errors.append(f"{node['id']} missing escalation")
        if node["denominator"] not in DENOMINATORS:
            errors.append(f"{node['id']} denominator")
        for state in node["evidence_states"]:
            if state not in EVIDENCE_STATES:
                errors.append(f"{node['id']} evidence state {state}")
        if node["counts"] and node["denominator"] == "NONE":
            errors.append(f"{node['id']} counts in NONE")
        if not node["counts"] and node["denominator"] not in {"NONE"}:
            errors.append(f"{node['id']} non-count has denominator")
        if node["denominator"] == "PRE_TRAINING" and node["event"] != "READINESS":
            errors.append(f"{node['id']} pretraining event")
        if node["denominator"] == "EXECUTION" and node["event"] not in {
            "FOUNDER_AUTHORIZATION_GRANTED",
            "TRAINING_EXECUTION_ALLOWED",
        }:
            errors.append(f"{node['id']} execution event")
        if node["founder_act"] == "CONTINGENT" and node["denominator"] == "PRE_TRAINING":
            errors.append(f"{node['id']} contingent act inside readiness")
        if node["founder_act"] == "INTERMEDIATE" and node["denominator"] != "PRE_TRAINING":
            errors.append(f"{node['id']} intermediate act outside readiness")
        if node["founder_approval"] == "REQUIRED" and node["denominator"] == "PRE_TRAINING":
            if "intermediate" not in node["rationale"].lower():
                errors.append(f"{node['id']} founder-required readiness row needs an intermediate rationale")
        if node["denominator"] == "EXECUTION" and "contingent" not in node["rationale"].lower():
            errors.append(f"{node['id']} execution rationale")
        if node["denominator"] in {"APPLICATION", "POST_TRAINING_LAUNCH", "NONE"} and not node["rationale"]:
            errors.append(f"{node['id']} missing exclusion rationale")
        if node["canonical_id"]:
            if node["counts"]:
                errors.append(f"{node['id']} alias counts")
            if node["canonical_id"] not in by_id and node["canonical_id"] not in {n["id"] for n in nodes}:
                errors.append(f"{node['id']} missing canonical")
        if node["covered_by"] and node["counts"]:
            errors.append(f"{node['id']} covered row counts")

    for node in nodes:
        if node["canonical_id"] and node["canonical_id"] not in by_id:
            errors.append(f"{node['id']} canonical missing")
        for dep in node["depends_on"]:
            if dep == node["id"]:
                errors.append(f"{node['id']} self-dependency")
            if dep not in by_id:
                errors.append(f"{node['id']} missing dep {dep}")
        for ref in node["cross_refs"]:
            if ref.startswith("C") or ref.startswith("HW") or ref.startswith("G"):
                if ref in by_id or ref == node["id"]:
                    continue
        for covered in node["covered_by"]:
            if covered not in by_id or not by_id[covered]["counts"]:
                errors.append(f"{node['id']} covered_by {covered}")

    contingent = {
        n["id"]
        for n in nodes
        if n["event"] in {"FOUNDER_AUTHORIZATION_GRANTED", "TRAINING_EXECUTION_ALLOWED"}
    }
    for node in nodes:
        if node["denominator"] == "PRE_TRAINING":
            hit = set(node["depends_on"]) & contingent
            if hit:
                errors.append(f"{node['id']} readiness depends on {sorted(hit)}")

    expected_final = sorted(
        n["id"]
        for n in nodes
        if n["denominator"] == "PRE_TRAINING" and n["counts"] and n["id"] != "FINAL-1"
    )
    if "FINAL-1" not in by_id:
        errors.append("missing FINAL-1")
    elif by_id["FINAL-1"]["depends_on"] != expected_final:
        errors.append("FINAL-1 dependency set is not the readiness inventory")
    if by_id.get("FINAL-2", {}).get("depends_on") != ["FINAL-1"]:
        errors.append("FINAL-2 must depend only on FINAL-1")
    if by_id.get("EXEC-1", {}).get("depends_on") != ["FINAL-2"]:
        errors.append("EXEC-1 must depend only on FINAL-2")
    if "FINAL-2" in expected_final or "EXEC-1" in expected_final or "AUTH-2" in expected_final:
        errors.append("contingent authorization entered the readiness inventory")

    keys = {}
    classes = {}
    required = {}
    for node in nodes:
        if not node["counts"]:
            continue
        key = node["evidence_key"]
        if key in keys:
            errors.append(f"shared evidence key {key} on {keys[key]} and {node['id']}")
        keys[key] = node["id"]
        artifact_class = node["artifact_class"]
        if artifact_class in classes:
            errors.append(
                f"shared artifact class {artifact_class} on {classes[artifact_class]} and {node['id']}"
            )
        classes[artifact_class] = node["id"]
        text = " ".join(node["evidence_required"].split())
        if text in required:
            errors.append(f"shared evidence text {node['id']} and {required[text]}")
        required[text] = node["id"]

    freeze_rows = {n["freeze_row"] for n in nodes if n["freeze_row"]}
    if freeze_rows != set(range(1, 26)):
        errors.append(f"freeze rows {sorted(freeze_rows)}")
    c_ids = {f"C{i:02d}" for i in range(1, 51)}
    if not c_ids <= set(by_id):
        errors.append(f"missing C rows {sorted(c_ids - set(by_id))}")
    if any(n["id"].startswith("R65-") or n["id"].startswith("RULE-") for n in nodes):
        errors.append("invented founder rule")
    if by_id["R65"]["status"] != "NOT_VERIFIABLE":
        errors.append("R65 status")
    errors.extend(check_corpus_partition(by_id))

    sorter = TopologicalSorter()
    for node in nodes:
        sorter.add(node["id"], *node["depends_on"])
    try:
        list(sorter.static_order())
    except CycleError as exc:
        errors.append(f"cycle {exc.args}")

    numerator = sum(
        1
        for n in nodes
        if n["denominator"] == "PRE_TRAINING" and n["counts"] and n["status"] == "ACCEPTED"
    )
    if numerator != 0:
        errors.append("numerator is not 0")
    errors.extend(check_freeze(nodes))
    return errors


CORPUS_ARTIFACTS = {
    "G8": "founder-corpus-grant",
    "DATA-3": "protected-corpus-creation",
    "DATA-1": "corpus-provenance-manifest",
    "DATA-5": "corpus-custody-integrity",
    "DATA-2": "contamination-holdout-separation",
}


def check_corpus_partition(by_id):
    errors = []
    if len(set(CORPUS_ARTIFACTS.values())) != len(CORPUS_ARTIFACTS):
        errors.append("corpus artifact classes are not distinct")
    for row_id, artifact_class in CORPUS_ARTIFACTS.items():
        node = by_id.get(row_id)
        if node is None or not node["counts"]:
            errors.append(f"{row_id} missing from corpus partition")
            continue
        if node["artifact_class"] != artifact_class:
            errors.append(f"{row_id} artifact class")
        if node["evidence_key"] == by_id["G8"]["evidence_key"] and row_id != "G8":
            errors.append(f"{row_id} reuses the grant key")
    if "G8" not in by_id["DATA-3"]["depends_on"]:
        errors.append("DATA-3 must follow the grant")
    if by_id["DATA-3"]["depends_on"] == ["G8"] and "grant is not this record" not in by_id["DATA-3"]["evidence_required"]:
        errors.append("DATA-3 evidence collapsed into the grant")
    for row_id in ("DATA-1", "DATA-2", "DATA-5"):
        if "founder grant is not" not in by_id[row_id]["evidence_required"]:
            errors.append(f"{row_id} does not exclude the grant")
    if "does not create a corpus" not in by_id["G8"]["evidence_required"]:
        errors.append("G8 grant text implies creation")
    if "DATA-3" not in by_id["DATA-1"]["depends_on"]:
        errors.append("DATA-1 must follow creation")
    if "DATA-5" not in by_id["DATA-2"]["depends_on"]:
        errors.append("DATA-2 must follow custody")
    if by_id["G9"]["depends_on"] == ["DATA-3"]:
        errors.append("crown milestone must not be the corpus")
    return errors


def check_freeze(nodes):
    path = ROOT / "docs/orneur/phase-21/rse/v1.2/RSE12_06_P1_ACCEPTANCE_OPERATIONS.md"
    text = path.read_text(encoding="utf-8")
    found = set(re.findall(r"\| (C\d{2}) \|", text))
    expected = {f"C{i:02d}" for i in range(1, 51)}
    errors = []
    if found != expected:
        errors.append(f"freeze C-id parse {sorted(expected ^ found)}")
    ids = {n["id"] for n in nodes}
    if not expected <= ids:
        errors.append("graph dropped a freeze C-id")
    section = text.split("## 2. Threat model", 1)[0]
    rows = {int(n) for n in re.findall(r"(?m)^\| (\d+) \|", section)}
    if rows != set(range(1, 26)):
        errors.append(f"section 1 rows {sorted(rows)}")
    return errors


def graph_document(nodes):
    pre = [n["id"] for n in nodes if n["denominator"] == "PRE_TRAINING" and n["counts"]]
    app = [n["id"] for n in nodes if n["denominator"] == "APPLICATION" and n["counts"]]
    post = [n["id"] for n in nodes if n["denominator"] == "POST_TRAINING_LAUNCH" and n["counts"]]
    exe = [n["id"] for n in nodes if n["denominator"] == "EXECUTION" and n["counts"]]
    return {
        "schema": "orneur-acceptance-graph-v1",
        "non_normative": True,
        "published_pretraining_percentage": None,
        "numerator_pretraining": 0,
        "denominator_pretraining_ids": pre,
        "denominator_application_ids": app,
        "denominator_post_training_ids": post,
        "denominator_execution_ids": exe,
        "events": [
            "PRETRAINING_READINESS_ACCEPTED",
            "FOUNDER_AUTHORIZATION_GRANTED",
            "TRAINING_EXECUTION_ALLOWED",
        ],
        "reconciliation": RECONCILIATION,
        "nodes": nodes,
        "edges": [
            {"from": node["id"], "to": dep}
            for node in nodes
            for dep in node["depends_on"]
        ],
    }


def cell(value):
    return str(value).replace("|", "/").replace("\n", " ")


def render_markdown(doc):
    nodes = doc["nodes"]
    lines = []
    a = lines.append
    a("# ORNEUR Master Execution and Acceptance Register")
    a("")
    a("NON_NORMATIVE. Not in Manifest V3. Does not amend RSE-ARCH-1.2. Does not authorize provisioning, purchase, secrets, corpus generation, qualification, model selection, GPU, spend, or training. Does not merge any pull request.")
    a("")
    a("This file remediates the register at `de7188d76a8db633886812277272c8e51080e11e`. The three Phase 0 notes on PR #14 stay as they are. Author disposition of this remediation: READY_FOR_INDEPENDENT_RETEST. That disposition is not readiness acceptance.")
    a("")
    a("## Events")
    a("")
    a("Three sequential events stay distinct.")
    a("")
    a("1. `PRETRAINING_READINESS_ACCEPTED` is FINAL-1. It is a worksheet over the pre-training inventory. Founder training permission is not one of its inputs.")
    a("2. `FOUNDER_AUTHORIZATION_GRANTED` is FINAL-2. It depends only on FINAL-1. It names the SHA, dataset manifest, foundation revision, research-only scope, spend cap, and GPU permission.")
    a("3. `TRAINING_EXECUTION_ALLOWED` is EXEC-1. It depends only on FINAL-2. It is the start record. The locks have to agree with FINAL-2.")
    a("")
    a("Intermediate founder acts sit inside readiness because later evidence needs them: purchase, provisioning, corpus grant, budget, research-only scope, model selection, runner authorization, and the class-K decision. Each of those rows says intermediate. None of them is FINAL-2.")
    a("")
    a("## Counting")
    a("")
    a("The published status column is an observation. It is not an acceptance bit. `pass_rule` is `OWN_EVIDENCE` on every row. Aliases and covered rows are identifiable and add nothing to a denominator. A predecessor becoming complete leaves every dependent unchanged.")
    a("")
    a(f"Pre-training denominator size: {len(doc['denominator_pretraining_ids'])}. Numerator: 0. Application denominator size: {len(doc['denominator_application_ids'])}. Post-training launch denominator size: {len(doc['denominator_post_training_ids'])}. Execution denominator size: {len(doc['denominator_execution_ids'])}.")
    a("")
    a("No pre-training percentage is published. R65 is `NOT_VERIFIABLE` and stands for an unmapped set. G1 and AUTH-1 are also `NOT_VERIFIABLE`. When a founder-approved source of the 65 rules exists, R65 is replaced by one child row per rule and the denominator changes. Until then the child rules are absent on purpose.")
    a("")
    a("## Future acceptance")
    a("")
    a("A later row can advance only through `scripts/acceptance/acceptance_engine.py`. The engine reads a ledger that is separate from this register. Each record must carry a detached signature over the requirement id, evidence key, artifact class, artifact digest, git SHA, denominator, reviewer role, and policy version (bound to the hash of the policy document, this engine's own source, and the published register graph together, not a free-floating label). DATA-3 separately declares a corpus_identity_sha256 distinct from its own record digest; DATA-1/DATA-2/DATA-5 bind to that identity via bound_corpus_identity_sha256, not to DATA-3's record digest. A row marked founder_approval REQUIRED needs a second, independent detached signature from a key enrolled with role FOUNDER over that same payload; a reviewer signature alone never satisfies it. DATA-5 (corpus custody) must also be signed by a reviewer key whose actual public key is distinct from the key that got DATA-3 (corpus creation) accepted -- checked by resolved key identity, not by the caller-chosen key_id label. For the four protected corpus-evidence classes, a correctly shaped, correctly signed digest is not enough: the reviewer's own key must also produce a non-disclosing custody-possession signature over a challenge derived from the digest and commit; every other evidence row requires the caller to present actual bytes that hash to the declared digest. Trust is no longer a caller-assembled list of individually-signed keys: a whole, atomically-signed trust_snapshot (which reviewer/founder keys are currently valid) and a whole root_state (which founder roots are currently valid) must each verify for the exact commit SHA under evaluation -- an older, still-validly-signed version of either is rejected as stale, the same way a stale evidence record already is -- and root_state itself must verify against a single permanent bootstrap_root_key_hex that is ALSO pinned in the engine's own source (PINNED_BOOTSTRAP_ROOT_KEYS), so a caller cannot make its own generated bootstrap authoritative merely by passing it in. Binding to the exact commit SHA alone cannot order two signed trust_snapshot generations that both name the same commit, so a separate trust_checkpoint commits to the exact hash of both trust_snapshot and root_state for that commit, and its own hash must equal a pinned_checkpoint_hash the caller supplies from a channel independent of this evaluation -- a same-commit rollback is closed by exact pinning, not by generation comparison. The committed ledger `docs/orneur/acceptance/acceptance_ledger.json` is empty. The committed trust snapshot `docs/orneur/acceptance/reviewer_trust.json` has no entries. The committed root state `docs/orneur/acceptance/founder_root_keys.json` has no roots. The committed bootstrap anchor `docs/orneur/acceptance/BOOTSTRAP_ROOT_KEY.json` has no key, and no bootstrap key is pinned in the engine's own source either. The committed trust checkpoint `docs/orneur/acceptance/TRUST_CHECKPOINT.json` and its pin `docs/orneur/acceptance/TRUST_CHECKPOINT_PIN.json` are both empty. This publication therefore accepts nothing and authorizes nothing.")
    a("")
    a("Editing a status cell, the Markdown, or the graph JSON does not accept a row. `--check` rejects a status of ACCEPTED and rejects a non-empty committed ledger or trust store. The engine ignores the published status field. A signature fails closed when it is missing, forged, duplicated, stale, aimed at the wrong requirement, reused for another control, signed by the implementer, signed by an unnamed reviewer, outside that row's denominator, or presented before a counted predecessor has its own accepted record. FINAL-2 stays after FINAL-1. EXEC-1 stays after FINAL-2. R65 cannot be signed into acceptance while it is the unmapped placeholder. FINAL-1 fails while any counted pre-training row, including R65, lacks its own acceptance.")
    a("")
    a("## Protected corpus")
    a("")
    a("Five counted artifacts stay separate. G8 is only the founder corpus-generation grant. DATA-3 is creation of the protected corpus. DATA-1 is the provenance manifest bound to that creation digest. DATA-5 is independent custody and integrity. DATA-2 is contamination and holdout separation. The grant does not pass DATA-3, DATA-1, DATA-5, or DATA-2, and it does not imply that a corpus exists. The small documented dataset note is not the protected corpus.")
    a("")
    a("## Roles")
    a("")
    a("Cursor implements RSE software and drafts this register. Claude reviews Cursor's RSE software and is the author of the application PRs and the Docker lab, so Claude does not review those. Antigravity is the proposed independent retester for application and Docker work. Product Management checks programme records and founder-record completeness. The founder, Guruprasath Annadurai, is the only role that can approve purchase, provisioning, corpus, scope, selection, budget, and the later training authorization. Founder approval is a separate column from implementation and from review.")
    a("")
    a("`UNRESOLVED_EXTERNAL` means the person is not one of those roles yet. The escalation cell says what the founder or Product Management must name. This register does not hire them.")
    a("")
    a("## Evidence vocabulary")
    a("")
    a("`SOURCE_VERIFIED` means a file in this checkout was read. `SHA_CI_PASSED` means a push run for that exact SHA succeeded. `PULL_REQUEST_CI_PASSED` is a pull-request run and is not exact-SHA proof. `CI_IN_PROGRESS` means the push run had not finished at the check. `SHA_CI_PASSED_ON_ANCESTOR` does not cover the live head. `EXTERNALLY_REPORTED` means Product Management pointed at a report that is not in git and not a GitHub review. None of these states is acceptance.")
    a("")
    a("## Repairs")
    a("")
    a("FINAL-1 depends on the pre-training inventory and does not depend on FINAL-2. FINAL-2 depends only on FINAL-1. G12 is the infrastructure record and does not depend on GPU permission. AUTH-2 is an alias of FINAL-2. MODEL-1 depends on the research-scope record and does not depend on the training lock. AUTH-3 is an alias of EXEC-1. The validator rejects any readiness edge into FINAL-2 or EXEC-1.")
    a("")
    a("C27 stays mandatory. DEC-K asks the founder to keep class K deferred, and to keep C27 unmet, until a later architecture-change authorization. DEC-K does not implement class K. Accepting DEC-K does not accept C27.")
    a("")
    a("P1 section 1 rows 1–25 each have an id. Where the objective artifact is already a C row, the hardware id is an alias and the frozen class is copied onto both. Preferred and optional rows stay in the inventory and outside the mandatory denominator. HW-16, the wired-port firmware record, stays separate from C33, the netdev digest. HW-02, TPM presence, stays separate from C24, the release test. HW-FORGE is the Forge serial required by the section 6 P1 definition.")
    a("")
    a("APP-1 and APP-2 are mandatory application work. `orca/train` does not import `orca.serve`, and the first Genesis run is not defined to boot the public assistant. They are outside the pre-training denominator for that reason. SUP-2 is the production assistant image and is classified the same way. MODEL-2C is the commercial-release right and is mandatory for a commercial launch. MODEL-2R is only the research-or-evaluation scope.")
    a("")
    a("## External reports")
    a("")
    a("EV-AG-APP and EV-AG-DOCKER record that Product Management says Antigravity previously retested the application and Docker work. The report text, the tested SHA, and the result are not in this repository. GitHub review counts on those pull requests are 0. Those nodes do not change APP-1, APP-2, SUP-1, or C39.")
    a("")
    a("## Reconciliation")
    a("")
    a("| Item | Value |")
    a("| --- | --- |")
    rec = doc["reconciliation"]
    a(f"| Checked | {rec['checked']} |")
    a(f"| main | `{rec['main']}` |")
    a(f"| Reviewed register | `{rec['reviewed_register_sha']}` push run {rec['reviewed_register_push_run']['id']} {rec['reviewed_register_push_run']['conclusion']} |")
    for pull in rec["pulls"]:
        runs = pull.get("runs", [])
        run_text = "; ".join(
            f"{run['id']} {run['event']} {run['conclusion']}"
            + (f" sha {run['sha']}" if run.get("sha") else "")
            for run in runs
        ) or pull.get("note", "")
        head = pull.get("head") or pull.get("head_before_this_remediation", "")
        a(
            f"| PR #{pull['number']} | head `{head}` reviews {pull.get('reviews', '')} {run_text} |"
        )
    a("")
    a("The new publication SHA is the git commit that adds this remediation. Its GitHub CI did not exist when the graph was built. The run above covers only the reviewed SHA.")
    a("")
    a("## Unknowns")
    a("")
    a("- The 65-rule source is absent. R65 has no children.")
    a("- G1 has no review artifact.")
    a("- AUTH-1 has no budget record.")
    a("- Antigravity's report body is not in the repository.")
    a("- PR #12 push run 37973804538 and PR #13 push run 37973767347 later completed with conclusion success. GitHub reviews on both pull requests are still 0.")
    a("- PR #11 has a pull-request run and no listed push run.")
    a("- PR #13's live head is `0328123361756b9732fc57886754d6d09c4b9c46`, which is newer than `cd95befd196c57d1885be208532a1c9a32991a39`.")
    a("- Application diffs were not read.")
    a("- No hardware, corpus, qualification, or training evidence was created.")
    a("")
    a("## Independent review request")
    a("")
    a("Review this file and `docs/orneur/acceptance/register_graph.json`. Run `python3 scripts/acceptance/validate_register_graph.py --check`.")
    a("")
    a("1. Confirm the graph is acyclic and that no readiness id depends on FINAL-2 or EXEC-1.")
    a("2. Confirm every C01–C50 id and every section 1 row 1–25 is present, and that aliases are absent from the pre-training denominator.")
    a("3. Confirm PR heads and run ids against GitHub. A later head needs its own push run.")
    a("4. Confirm R65 has no invented rule text.")
    a("5. Confirm APP-1, APP-2, SUP-2, and MODEL-2C are outside the pre-training denominator for the reasons written on those rows.")
    a("6. Confirm EV-AG-APP and EV-AG-DOCKER are not used as acceptance.")
    a("7. Confirm the committed acceptance ledger and reviewer trust store are empty.")
    a("8. Confirm the acceptance engine rejects a reused artifact, a wrong SHA, a missing reviewer, a self-review, a missing predecessor, a scope mismatch, and FINAL-1 while any counted pre-training row is open.")
    a("9. Do not merge. Do not authorize a protected operation.")
    a("")
    a("## Inventory")
    a("")
    a("| ID | Class | Frozen | Denominator | Counts | Status | States | Owner | Reviewer | Founder | Depends | Evidence required | Current evidence | Exit |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for node in nodes:
        deps = ",".join(node["depends_on"]) if node["depends_on"] else "-"
        if node["id"] == "FINAL-1":
            deps = f"{len(node['depends_on'])} pre-training ids, excluding FINAL-1"
        a(
            "| {id} | {cls} | {frozen} | {den} | {counts} | {status} | {states} | {owner} | {reviewer} | {founder} | {deps} | {ev} | {cur} | {exit} |".format(
                id=cell(node["id"]),
                cls=cell(node["class"]),
                frozen=cell(node["frozen_class"]),
                den=cell(node["denominator"]),
                counts="yes" if node["counts"] else "no",
                status=cell(node["status"]),
                states=cell(",".join(node["evidence_states"])),
                owner=cell(node["implementation_owner"]),
                reviewer=cell(node["independent_reviewer"]),
                founder=cell(node["founder_approval"]),
                deps=cell(deps),
                ev=cell(node["evidence_required"]),
                cur=cell(node["current_evidence"]),
                exit=cell(node["exit"]),
            )
        )
    a("")
    a("Source, escalation, rationale, canonical id, and covered-by are in the JSON object for each id.")
    a("")
    a("## Edges")
    a("")
    a("Each edge points from a row to a predecessor. A predecessor completing does not complete the row.")
    a("")
    a("| From | To |")
    a("| --- | --- |")
    for edge in doc["edges"]:
        if edge["from"] == "FINAL-1":
            continue
        a(f"| {edge['from']} | {edge['to']} |")
    a(f"| FINAL-1 | each of the other {len(doc['denominator_pretraining_ids']) - 1} pre-training ids |")
    a("")
    return "\n".join(lines) + "\n"


def canonical_json(doc):
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    nodes = build_nodes()
    errors = validate(nodes)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    doc = graph_document(nodes)
    rendered_json = canonical_json(doc)
    rendered_md = render_markdown(doc)
    blob = rendered_json + rendered_md
    for banned in BANNED:
        if banned in blob:
            print(f"banned string {banned}", file=sys.stderr)
            return 1
    if args.write:
        JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(rendered_json, encoding="utf-8")
        MD_PATH.write_text(rendered_md, encoding="utf-8")
    if args.check:
        if JSON_PATH.read_text(encoding="utf-8") != rendered_json:
            print("json drift", file=sys.stderr)
            return 1
        if MD_PATH.read_text(encoding="utf-8") != rendered_md:
            print("markdown drift", file=sys.stderr)
            return 1
        ledger_text = LEDGER_PATH.read_text(encoding="utf-8")
        trust_text = TRUST_PATH.read_text(encoding="utf-8")
        founder_root_text = FOUNDER_ROOT_PATH.read_text(encoding="utf-8")
        bootstrap_text = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        checkpoint_text = CHECKPOINT_PATH.read_text(encoding="utf-8")
        checkpoint_pin_text = CHECKPOINT_PIN_PATH.read_text(encoding="utf-8")
        if (
            ledger_text != EMPTY_LEDGER
            or trust_text != EMPTY_TRUST
            or founder_root_text != EMPTY_FOUNDER_ROOT
            or bootstrap_text != EMPTY_BOOTSTRAP
            or checkpoint_text != EMPTY_CHECKPOINT
            or checkpoint_pin_text != EMPTY_CHECKPOINT_PIN
        ):
            print(
                "acceptance ledger, trust snapshot, root state, bootstrap root key, trust checkpoint, "
                "or checkpoint pin is not the empty baseline",
                file=sys.stderr,
            )
            return 1
        engine_dir = str(Path(__file__).resolve().parent)
        if engine_dir not in sys.path:
            sys.path.insert(0, engine_dir)
        from acceptance_engine import assert_published_baseline, evaluate

        ledger = json.loads(ledger_text)
        trust_snapshot = json.loads(trust_text)
        root_state = json.loads(founder_root_text)
        bootstrap = json.loads(bootstrap_text)
        trust_checkpoint = json.loads(checkpoint_text)
        checkpoint_pin = json.loads(checkpoint_pin_text)
        baseline_errors = assert_published_baseline(
            nodes, rendered_md, ledger, trust_snapshot, root_state, bootstrap, trust_checkpoint,
        )
        if baseline_errors:
            print("\n".join(baseline_errors), file=sys.stderr)
            return 1
        accepted = evaluate(
            nodes,
            ledger,
            trust_snapshot=trust_snapshot,
            root_state=root_state,
            bootstrap_root_key_hex=bootstrap.get("public_key_hex", ""),
            trust_checkpoint=trust_checkpoint,
            pinned_checkpoint_hash=checkpoint_pin.get("pinned_checkpoint_hash", ""),
            subject_sha="0" * 40,
        )
        if accepted:
            print("empty ledger accepted a row", file=sys.stderr)
            return 1
    if args.self_test:
        broken = json.loads(rendered_json)
        broken["nodes"][0]["depends_on"] = ["FINAL-2"]
        # The first node is not stable under sort_keys of the document, so
        # mutate a known readiness id.
        for node in broken["nodes"]:
            if node["id"] == "G1":
                node["depends_on"] = ["FINAL-2"]
        again = validate(broken["nodes"])
        if not any("readiness depends" in err or "cycle" in err for err in again):
            print("self-test failed to catch a readiness edge into FINAL-2", file=sys.stderr)
            return 1
        for node in broken["nodes"]:
            if node["id"] == "G2":
                node["depends_on"] = ["G1", "G2"]
        cycled = validate(broken["nodes"])
        if not any("self-dependency" in err or "cycle" in err for err in cycled):
            print("self-test failed to catch a cycle", file=sys.stderr)
            return 1
    print(
        f"pretraining={len(doc['denominator_pretraining_ids'])} "
        f"numerator=0 application={len(doc['denominator_application_ids'])} "
        f"execution={len(doc['denominator_execution_ids'])} "
        f"post={len(doc['denominator_post_training_ids'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
