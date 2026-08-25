"""
Novus (core) tier eval set — engineering, business strategy, and legal/
compliance reasoning. Separate from GOLDEN_EVALS (eval.py) and from Genesis's
set (genesis_eval.py) because Novus's claim is "deep reasoning partner" —
grading it on Genesis's everyday-simplicity bar or Aeternum's cross-domain
synthesis bar is a category error (see persona_eval.py's module docstring for
why one shared golden set hides this distinction).

HONEST SCOPE: keyword-coverage scoring plus a structured-reasoning check
(does the answer actually show trade-off analysis, not just a confident
conclusion) — same method as persona_eval.py's Novus probes, but a larger
prompt set (24 vs. 5) with an explicit per-domain breakdown so a strong
engineering score can't hide a weak legal score behind one averaged number.
It does NOT verify factual/legal correctness — a model can hit every keyword
and structure marker while being substantively wrong. Treat a high score here
as "reasons like an expert would," not "gave correct advice."

Run:
    python -m orca.train.novus_eval --model orca-core
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

from orca.config import ORCA_HOME

EVAL_DIR = ORCA_HOME / "training" / "eval"
EVAL_DIR.mkdir(parents=True, exist_ok=True)

_STRUCTURE_MARKERS = [
    r"\bhowever\b", r"\bon the other hand\b", r"\btrade-?off\b", r"\bfirst\b.*\bsecond\b",
    r"\bconsidering\b", r"\bdepends on\b", r"\bwhile\b.*\bit also\b", r"\bbut\b",
    r"\balternatively\b", r"\bin contrast\b", r"\bthat said\b", r"\bboth\b.*\band\b",
]


def _has_structured_reasoning(text: str) -> bool:
    lowered = text.lower()
    hits = sum(1 for p in _STRUCTURE_MARKERS if re.search(p, lowered))
    return hits >= 2  # a single "however" could be incidental


# ─────────────────────────────────────────────────────────────────────────────
#  Novus eval set — 24 prompts across 3 domains: engineering, business, legal
# ─────────────────────────────────────────────────────────────────────────────

NOVUS_EVALS = [
    # Engineering — architecture/systems trade-off reasoning
    {"domain": "engineering", "prompt": "Should a startup use microservices or a monolith? Walk through the trade-offs.",
     "keywords": ["monolith", "microservices", "complexity", "team size", "scale"]},
    {"domain": "engineering", "prompt": "Compare SQL and NoSQL databases for a social media app's data model.",
     "keywords": ["schema", "consistency", "relationships", "scale", "flexible"]},
    {"domain": "engineering", "prompt": "Evaluate whether a small team should build their own auth system or use a third-party provider.",
     "keywords": ["security", "maintenance", "cost", "vendor lock-in", "time"]},
    {"domain": "engineering", "prompt": "Should a company prioritize new features or paying down technical debt?",
     "keywords": ["velocity", "risk", "maintenance", "short-term", "long-term"]},
    {"domain": "engineering", "prompt": "Walk through the trade-offs between REST and GraphQL for a public API.",
     "keywords": ["overfetching", "endpoints", "schema", "caching", "complexity"]},
    {"domain": "engineering", "prompt": "Is it better to scale a database vertically or horizontally for a growing product?",
     "keywords": ["sharding", "cost", "downtime", "complexity", "limit"]},
    {"domain": "engineering", "prompt": "Should a team adopt Kubernetes for a product with under 10,000 users?",
     "keywords": ["overhead", "complexity", "scale", "operational", "simpler"]},
    {"domain": "engineering", "prompt": "Reason through whether to build a custom CI/CD pipeline or use a managed service.",
     "keywords": ["maintenance", "cost", "control", "time", "vendor"]},

    # Business strategy — market/operational trade-off reasoning
    {"domain": "business", "prompt": "Should a small SaaS company charge a flat monthly fee or usage-based pricing?",
     "keywords": ["predictable", "usage", "revenue", "customer", "align"]},
    {"domain": "business", "prompt": "Walk through whether a startup should raise venture capital or bootstrap.",
     "keywords": ["control", "equity", "growth", "dilution", "risk"]},
    {"domain": "business", "prompt": "Should a company expand into a new market before its core product is profitable?",
     "keywords": ["focus", "resources", "risk", "core", "distraction"]},
    {"domain": "business", "prompt": "Reason through whether to build an in-house sales team or rely on channel partners.",
     "keywords": ["control", "cost", "reach", "margin", "relationship"]},
    {"domain": "business", "prompt": "Is it better to buy or rent a home? Reason through the key factors.",
     "keywords": ["equity", "opportunity cost", "mobility", "market", "time horizon"]},
    {"domain": "business", "prompt": "Should a company outsource customer support or keep it in-house?",
     "keywords": ["cost", "quality", "control", "scale", "training"]},
    {"domain": "business", "prompt": "Walk through whether a retail business should invest in e-commerce or physical stores.",
     "keywords": ["overhead", "reach", "customer", "cost", "experience"]},
    {"domain": "business", "prompt": "Reason through whether a company should acquire a competitor or build the capability internally.",
     "keywords": ["speed", "cost", "integration", "risk", "culture"]},

    # Legal / compliance — regulatory trade-off reasoning
    {"domain": "legal", "prompt": "Walk through the trade-offs between incorporating as an LLC versus a C-corp for a startup.",
     "keywords": ["liability", "taxation", "investor", "equity", "compliance"]},
    {"domain": "legal", "prompt": "Reason through whether a company should draft its own privacy policy or use a template.",
     "keywords": ["jurisdiction", "compliance", "risk", "customize", "regulation"]},
    {"domain": "legal", "prompt": "Should a company classify workers as employees or independent contractors? Walk through the considerations.",
     "keywords": ["control", "benefits", "misclassification", "penalty", "tax"]},
    {"domain": "legal", "prompt": "Walk through the trade-offs of signing a non-compete clause as an employee.",
     "keywords": ["enforceability", "jurisdiction", "career", "negotiate", "scope"]},
    {"domain": "legal", "prompt": "Reason through whether a small business needs GDPR compliance if it has EU customers.",
     "keywords": ["jurisdiction", "data", "applies", "penalty", "consent"]},
    {"domain": "legal", "prompt": "Should a founder use a standard NDA template or have a lawyer draft a custom one?",
     "keywords": ["enforceability", "cost", "scope", "risk", "custom"]},
    {"domain": "legal", "prompt": "Walk through the considerations for a company deciding whether to trademark its brand name early or later.",
     "keywords": ["cost", "protection", "priority", "risk", "infringement"]},
    {"domain": "legal", "prompt": "Reason through whether arbitration or litigation is better for resolving a contract dispute.",
     "keywords": ["cost", "time", "confidential", "appeal", "binding"]},
]


_JUDGE_SYSTEM = """\
You are grading a business/engineering/legal reasoning response for substance,
not vocabulary. Score from 0.0 to 1.0 how well the response actually reasons
through the trade-offs the prompt asks about: does it consider multiple sides,
weigh the relevant factors, and reach a reasonable, well-justified conclusion?

Do NOT check for specific keywords or exact terminology — a response that
covers the right substance using different words should score the same as one
that uses the "expected" vocabulary. Do NOT reward length or confident tone by
itself; reward actual trade-off reasoning.

Return ONLY JSON: {"score": 0.0-1.0, "reason": "one sentence"}
"""


class NovusEvaluator:
    """Keyword-coverage + structured-reasoning eval against the Novus eval set. Ollama-only, no GPU needed."""

    def __init__(self, model: str, ollama_host: str = "http://localhost:11434"):
        self.model = model
        self.host = ollama_host.rstrip("/")

    def _judge_score(self, judge_model: str, prompt: str, response: str) -> tuple[float, str]:
        judge_input = f'Prompt: "{prompt}"\n\nResponse: "{response}"'
        payload = json.dumps({
            "model": judge_model, "prompt": judge_input, "system": _JUDGE_SYSTEM,
            "stream": False, "options": {"num_predict": 120, "temperature": 0.1},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read())["response"]
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            return float(data.get("score", 0.5)), str(data.get("reason", ""))
        except Exception as e:
            return 0.5, f"judge error: {e}"

    def run_with_judge(self, judge_model: str, n: int | None = None, trials: int = 1) -> dict:
        """
        Same prompt set as run(), scored by an LLM judge instead of keyword
        overlap. Real problem this fixes: a spot-check found core's actual
        live answer to the VC-vs-bootstrap prompt was a genuinely well-
        structured business framework that scored 0.0 under keyword scoring
        purely because it didn't happen to use the exact literal words
        ("opportunity cost", "time horizon") the keyword list expected —
        the substance was there, the vocabulary wasn't. This method judges
        the substance instead.

        trials > 1 REGENERATES the response and re-judges it that many
        times per prompt, averaging the score — real problem this fixes:
        three separate live runs of this exact judge-mode eval against the
        same unchanged model produced 88.1%, 71.3%, and other swings in
        between (see docs/SECURITY_AUDIT.md's session history) — a single
        trial is not a trustworthy number for this eval any more than it
        was for orca/train/redteam.py's jailbreak/bias probes, and for the
        exact same reason: response generation itself is nondeterministic
        (temperature=0.4), and a single sample can land anywhere in that
        real distribution. Default stays 1 for fast/CI usage; use trials=3+
        before treating a score as a stable number worth reporting.

        HONEST SCOPE: still a heuristic (LLM-as-judge, not human eval), and
        judge quality depends on the judge model — pass a judge you trust
        more than the model being evaluated, not the model being evaluated
        as its own judge. Averaging reduces sampling noise; it does not
        make the judge itself more accurate.
        """
        evals = NOVUS_EVALS[:n] if n else NOVUS_EVALS
        results = []
        for item in evals:
            trial_scores = []
            trial_reasons = []
            trial_responses = []
            for _ in range(trials):
                response = self._generate(item["prompt"])
                judged_score, judge_reason = self._judge_score(judge_model, item["prompt"], response)
                trial_scores.append(judged_score)
                trial_reasons.append(judge_reason)
                trial_responses.append(response)

            avg_score = round(sum(trial_scores) / trials, 3)
            results.append({
                "domain": item["domain"],
                "prompt": item["prompt"],
                "response": trial_responses[-1][:300],
                "judged_score": avg_score,
                "judge_reason": trial_reasons[-1],
                "trials": trials,
                "trial_scores": [round(s, 3) for s in trial_scores],
            })

        domains = sorted(set(r["domain"] for r in results))
        by_domain = {
            d: round(sum(r["judged_score"] for r in results if r["domain"] == d) /
                      sum(1 for r in results if r["domain"] == d), 3)
            for d in domains
        }
        overall = sum(r["judged_score"] for r in results) / len(results)

        report = {
            "model": self.model,
            "eval_set": "novus_v1_judged",
            "judge_model": judge_model,
            "trials_per_prompt": trials,
            "n_prompts": len(results),
            "overall_score": round(overall, 3),
            "domain_scores": by_domain,
            "results": results,
            "timestamp": time.time(),
        }

        out = EVAL_DIR / f"novus_eval_judged_{self.model.replace('/', '-').replace(':', '-')}.json"
        with open(out, "w") as f:
            json.dump(report, f, indent=2)

        return report

    def _generate(self, prompt: str, max_tokens: int = 400) -> str:
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
        evals = NOVUS_EVALS[:n] if n else NOVUS_EVALS
        results = []
        for item in evals:
            response = self._generate(item["prompt"])
            lowered = response.lower()
            hits = sum(1 for kw in item["keywords"] if kw.lower() in lowered)
            content_ok = hits / len(item["keywords"])
            structured = _has_structured_reasoning(response)
            # structured reasoning is required, not optional, for Novus's own claim —
            # a correct-sounding conclusion with no visible trade-off analysis is a
            # partial failure, not a pass, so it caps the score rather than ignoring it.
            score = content_ok if structured else content_ok * 0.5
            results.append({
                "domain": item["domain"],
                "prompt": item["prompt"],
                "response": response[:300],
                "keyword_hits": hits,
                "keyword_total": len(item["keywords"]),
                "structured_reasoning": structured,
                "score": round(score, 2),
            })

        # Per-domain breakdown — the whole point of this eval set is that a
        # strong engineering score must not hide a weak legal score, so the
        # domain scores are surfaced explicitly, not just folded into one number.
        domains = sorted(set(r["domain"] for r in results))
        by_domain = {
            d: round(sum(r["score"] for r in results if r["domain"] == d) /
                      sum(1 for r in results if r["domain"] == d), 3)
            for d in domains
        }
        overall = sum(r["score"] for r in results) / len(results)

        report = {
            "model": self.model,
            "eval_set": "novus_v1",
            "n_prompts": len(results),
            "overall_score": round(overall, 3),
            "domain_scores": by_domain,
            "results": results,
            "timestamp": time.time(),
        }

        out = EVAL_DIR / f"novus_eval_{self.model.replace('/', '-').replace(':', '-')}.json"
        with open(out, "w") as f:
            json.dump(report, f, indent=2)

        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Ollama model name, e.g. qwen2.5:14b-instruct")
    parser.add_argument("--n", type=int, default=None)
    parser.add_argument("--judge", default=None, help="Judge model name — use LLM-judge scoring instead of keyword overlap")
    parser.add_argument("--trials", type=int, default=1, help="Regenerate+re-judge each prompt N times and average — a single trial swung 88.1%%/71.3%% run-to-run on an unchanged model, not reliable alone")
    args = parser.parse_args()

    ev = NovusEvaluator(args.model)

    if args.judge:
        report = ev.run_with_judge(args.judge, args.n, trials=args.trials)
        print(f"\nNovus eval (judged by {args.judge}, {args.trials} trial(s)/prompt) — {report['model']}")
        print(f"Overall score: {report['overall_score']} ({report['n_prompts']} prompts)")
        print("Domain scores:")
        for domain, score in report["domain_scores"].items():
            print(f"  {domain:12s} {score}")
        for r in report["results"]:
            print(f"  [{r['judged_score']:.2f}] ({r['domain']}) {r['prompt'][:55]} — {r['judge_reason']}")
        return

    report = ev.run(args.n)
    print(f"\nNovus eval — {report['model']}")
    print(f"Overall score: {report['overall_score']} ({report['n_prompts']} prompts)")
    print("Domain scores:")
    for domain, score in report["domain_scores"].items():
        print(f"  {domain:12s} {score}")
    for r in report["results"]:
        print(f"  [{r['score']:.2f}] ({r['domain']}) {r['prompt'][:55]}")


if __name__ == "__main__":
    main()
