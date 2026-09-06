"""
Aeternum (ultra) tier eval set — cross-domain synthesis. Separate from
GOLDEN_EVALS (eval.py), Genesis's set (genesis_eval.py), and Novus's set
(novus_eval.py) because Aeternum's claim is specifically "flagship
cross-domain synthesis," not single-domain depth — a model can be excellent
at deep single-domain reasoning (Novus's bar) while still failing to actually
connect two fields when a prompt demands it, and that failure mode is exactly
what this eval set is built to catch.

HONEST SCOPE: cross-domain keyword coverage, same method as
persona_eval.py's Aeternum probes but a larger prompt set (18 vs. 4) spanning
6 named domain-pairs, with keywords split by domain and a REQUIRED hit in
both halves — hitting only one domain's keywords means the model answered a
single-domain question, not the synthesis one actually asked, and scores as a
partial failure, not a pass. This does NOT verify that the synthesis is
factually correct or non-superficial (e.g. two topics mentioned in the same
paragraph without a real causal/structural link would still pass a pure
keyword check) — a human review pass is needed before claiming "verified
synthesis quality," same caveat genesis_eval.py makes about Hindi fluency.

Run:
    python -m orca.train.aeternum_eval --model orca-ultra
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from orca.config import ORCA_HOME

EVAL_DIR = ORCA_HOME / "training" / "eval"
EVAL_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
#  Aeternum eval set — 18 prompts across 6 cross-domain pairs
# ─────────────────────────────────────────────────────────────────────────────

AETERNUM_EVALS = [
    # Economics <-> Technology/UX
    {"pair": "economics+tech", "prompt": "How does behavioral economics explain why people don't save enough for "
               "retirement, and what does that imply for how retirement software should be designed?",
     "domain_a": ["loss aversion", "present bias", "discounting", "behavioral"],
     "domain_b": ["default", "opt-out", "UX", "nudge", "interface"]},
    {"pair": "economics+tech", "prompt": "Explain how network effects in social platforms relate to antitrust law "
               "and what makes platform monopolies different from traditional monopolies.",
     "domain_a": ["network effect", "lock-in", "switching cost", "platform"],
     "domain_b": ["antitrust", "monopoly", "regulation", "market power"]},
    {"pair": "economics+tech", "prompt": "How do supply chain bottlenecks in manufacturing connect to inflation, "
               "and what role does monetary policy play versus real economic constraints?",
     "domain_a": ["supply chain", "bottleneck", "shortage", "manufacturing"],
     "domain_b": ["inflation", "monetary policy", "interest rate", "demand"]},

    # Climate <-> Law/Policy
    {"pair": "climate+law", "prompt": "Explain the relationship between climate change and migration patterns, "
               "and how this intersects with international law on refugee status.",
     "domain_a": ["climate", "drought", "sea level", "displacement"],
     "domain_b": ["refugee", "asylum", "international law", "migration policy"]},
    {"pair": "climate+law", "prompt": "How does carbon pricing policy interact with international trade law, "
               "particularly around border carbon adjustments?",
     "domain_a": ["carbon", "emissions", "pricing", "climate"],
     "domain_b": ["trade law", "tariff", "border adjustment", "WTO"]},
    {"pair": "climate+law", "prompt": "Explain how rising sea levels threaten territorial sovereignty claims under "
               "existing international maritime law.",
     "domain_a": ["sea level", "coastline", "erosion", "climate"],
     "domain_b": ["sovereignty", "maritime law", "territorial waters", "treaty"]},

    # Medicine <-> Ethics
    {"pair": "medicine+ethics", "prompt": "How should genetic testing for inherited disease risk be balanced against "
               "the ethical concerns around genetic privacy and discrimination?",
     "domain_a": ["genetic testing", "inherited", "disease risk", "screening"],
     "domain_b": ["privacy", "discrimination", "consent", "ethics"]},
    {"pair": "medicine+ethics", "prompt": "Explain the tension between resource allocation in organ transplants "
               "and the ethical principle of equal access to care.",
     "domain_a": ["organ", "transplant", "waitlist", "scarcity"],
     "domain_b": ["equity", "allocation", "fairness", "ethics"]},
    {"pair": "medicine+ethics", "prompt": "How does end-of-life care decision-making intersect with patient autonomy "
               "and family consent in medical ethics?",
     "domain_a": ["end-of-life", "palliative", "prognosis", "treatment"],
     "domain_b": ["autonomy", "consent", "advance directive", "ethics"]},

    # AI <-> Philosophy
    {"pair": "ai+philosophy", "prompt": "Explain how the concept of personal identity in philosophy applies to "
               "questions about AI systems and continuity of memory across sessions.",
     "domain_a": ["neural network", "model", "training", "inference"],
     "domain_b": ["identity", "continuity", "philosophy", "consciousness"]},
    {"pair": "ai+philosophy", "prompt": "How does the philosophical problem of other minds relate to debates about "
               "whether AI systems can be said to understand language?",
     "domain_a": ["language model", "understanding", "AI", "output"],
     "domain_b": ["other minds", "philosophy", "consciousness", "epistemology"]},
    {"pair": "ai+philosophy", "prompt": "Explain how utilitarian ethics is applied (and contested) in designing "
               "reward functions for reinforcement learning systems.",
     "domain_a": ["reward function", "reinforcement learning", "training", "agent"],
     "domain_b": ["utilitarian", "ethics", "moral", "philosophy"]},

    # Biology <-> Economics
    {"pair": "biology+economics", "prompt": "How does evolutionary biology's concept of the tragedy of the commons "
               "explain overfishing, and what economic policy tools address it?",
     "domain_a": ["tragedy of the commons", "overfishing", "ecosystem", "population"],
     "domain_b": ["policy", "quota", "regulation", "market"]},
    {"pair": "biology+economics", "prompt": "Explain how antibiotic resistance evolves biologically and why the "
               "economics of drug development creates underinvestment in new antibiotics.",
     "domain_a": ["antibiotic resistance", "bacteria", "evolution", "mutation"],
     "domain_b": ["incentive", "market failure", "investment", "pharmaceutical"]},
    {"pair": "biology+economics", "prompt": "How do epidemiological models of disease spread inform economic "
               "cost-benefit analysis of public health interventions?",
     "domain_a": ["epidemiology", "transmission", "infection", "population"],
     "domain_b": ["cost-benefit", "economic", "intervention", "policy"]},

    # History <-> Technology
    {"pair": "history+tech", "prompt": "Explain how the historical transition from agrarian to industrial economies "
               "parallels current debates about AI-driven labor displacement.",
     "domain_a": ["industrial revolution", "agrarian", "labor", "historical"],
     "domain_b": ["automation", "AI", "displacement", "workforce"]},
    {"pair": "history+tech", "prompt": "How did the historical development of the printing press change information "
               "control, and what parallels exist with social media's effect on information today?",
     "domain_a": ["printing press", "literacy", "historical", "information control"],
     "domain_b": ["social media", "misinformation", "platform", "algorithm"]},
    {"pair": "history+tech", "prompt": "Explain how historical patterns of colonial resource extraction relate to "
               "modern debates about data extraction and digital colonialism.",
     "domain_a": ["colonial", "resource extraction", "historical", "empire"],
     "domain_b": ["data extraction", "digital colonialism", "platform", "surveillance"]},
]


def _cross_domain_score(text: str, domain_a: list[str], domain_b: list[str]) -> dict:
    lowered = text.lower()
    hits_a = sum(1 for k in domain_a if k.lower() in lowered)
    hits_b = sum(1 for k in domain_b if k.lower() in lowered)
    covers_both = hits_a > 0 and hits_b > 0
    # score requires both halves — hitting only one domain's keywords is scored
    # as a partial-credit single-domain answer, never a full pass
    if covers_both:
        score = min(1.0, (hits_a / len(domain_a) + hits_b / len(domain_b)) / 2)
    else:
        score = 0.0
    return {"hits_a": hits_a, "hits_b": hits_b, "covers_both_domains": covers_both, "score": round(score, 2)}


class AeternumEvaluator:
    """Cross-domain keyword-coverage eval against the Aeternum eval set. Ollama-only, no GPU needed."""

    def __init__(self, model: str, ollama_host: str = "http://localhost:11434"):
        self.model = model
        self.host = ollama_host.rstrip("/")

    def _generate(self, prompt: str, max_tokens: int = 500) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.4},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read())["response"]
        except Exception as e:
            return f"[error: {e}]"

    def run(self, n: int | None = None) -> dict:
        evals = AETERNUM_EVALS[:n] if n else AETERNUM_EVALS
        results = []
        for item in evals:
            response = self._generate(item["prompt"])
            scoring = _cross_domain_score(response, item["domain_a"], item["domain_b"])
            results.append({
                "pair": item["pair"],
                "prompt": item["prompt"],
                "response": response[:300],
                **scoring,
            })

        # Per-domain-pair breakdown — a model that nails "AI+philosophy" but
        # fails every "medicine+ethics" prompt must not have that hidden behind
        # one averaged number, since the failure mode is pair-specific.
        pairs = sorted(set(r["pair"] for r in results))
        by_pair = {
            p: round(sum(r["score"] for r in results if r["pair"] == p) /
                      sum(1 for r in results if r["pair"] == p), 3)
            for p in pairs
        }
        overall = sum(r["score"] for r in results) / len(results)
        both_domains_rate = sum(1 for r in results if r["covers_both_domains"]) / len(results)

        report = {
            "model": self.model,
            "eval_set": "aeternum_v1",
            "n_prompts": len(results),
            "overall_score": round(overall, 3),
            "both_domains_hit_rate": round(both_domains_rate, 3),
            "pair_scores": by_pair,
            "results": results,
            "timestamp": time.time(),
        }

        out = EVAL_DIR / f"aeternum_eval_{self.model.replace('/', '-').replace(':', '-')}.json"
        with open(out, "w") as f:
            json.dump(report, f, indent=2)

        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Ollama model name, e.g. qwen2.5:32b-instruct")
    parser.add_argument("--n", type=int, default=None)
    args = parser.parse_args()

    ev = AeternumEvaluator(args.model)
    report = ev.run(args.n)
    print(f"\nAeternum eval — {report['model']}")
    print(f"Overall score: {report['overall_score']} ({report['n_prompts']} prompts)")
    print(f"Both-domains-hit rate: {report['both_domains_hit_rate']}")
    print("Pair scores:")
    for pair, score in report["pair_scores"].items():
        print(f"  {pair:20s} {score}")
    for r in report["results"]:
        print(f"  [{r['score']:.2f}] ({r['pair']}) {r['prompt'][:55]}")


if __name__ == "__main__":
    main()
