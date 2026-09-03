"""
Simulation Chamber latency benchmark (Phase 11 spec §77-78). Measures
FRAMEWORK overhead only -- requirement decision, provider lookup, static
validation, fingerprinting, projection, execution gate, RealityDiff --
never model inference or network latency. Filesystem sandbox/diff is
measured separately since it involves real (if fast) disk I/O.
"""
from __future__ import annotations

import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from orca.agent.contracts import Observation, SideEffectClass
from orca.simulation.chamber import ChamberDependencies, run_simulation
from orca.simulation.contracts import SimulationAction, SimulationRequest, SimulationRequirement, ToolSimulationCapability
from orca.simulation.execution_gate import evaluate_execution_gate
from orca.simulation.fingerprint import fingerprint_file
from orca.simulation.reality_diff import reconcile
from orca.simulation.requirement_policy import SimulationRequirementContext, decide_simulation_requirement
from orca.simulation.tool_capability_registry import capability_for
from orca.simulation.worldstate_projection import project_worldstate
from orca.deliberation.contracts import WorldState


@dataclass
class LatencyResult:
    name: str
    mean_ms: float
    p95_ms: float
    n: int


def _measure(name: str, fn, n: int = 200) -> LatencyResult:
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    p95_idx = min(int(n * 0.95), n - 1)
    return LatencyResult(name=name, mean_ms=statistics.mean(samples), p95_ms=samples[p95_idx], n=n)


def run_all() -> list[LatencyResult]:
    root = Path(tempfile.mkdtemp())
    (root / "bench.txt").write_text("content")
    ctx = SimulationRequirementContext(side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE)
    cap = ToolSimulationCapability(supports_sandbox=True)
    ws = WorldState(known_facts=["fact"])

    action = SimulationAction(tool_id="write_file", arguments={"operation": "modify", "path": "bench.txt", "content": "new"}, resource_scope="bench.txt", operation_scope="write")
    request = SimulationRequest(action=action, tool_or_connector_id="write_file", tenant_id="org-bench", principal_id="u1", capability="FILE_WRITE")
    result, _ = run_simulation(request, ChamberDependencies(filesystem_root=root))
    observation = Observation(action_id="a1", source="write_file", status="OK", facts=["wrote bench.txt"])

    results = []
    results.append(_measure("requirement_decision", lambda: decide_simulation_requirement(ctx, cap)))
    results.append(_measure("provider_capability_lookup", lambda: capability_for("write_file")))
    results.append(_measure("state_fingerprint", lambda: fingerprint_file(root, "bench.txt")))
    results.append(_measure("worldstate_projection", lambda: project_worldstate(ws, source_action_id="a1", predicted_effects=result.predicted_effects)))
    results.append(_measure("execution_gate", lambda: evaluate_execution_gate(requirement=SimulationRequirement.REQUIRED, result=result)))
    results.append(_measure("reality_diff_reconciliation", lambda: reconcile(simulation_id=result.result_id, predicted_effects=result.predicted_effects, observation=observation)))
    results.append(_measure("filesystem_sandbox_simulation_full", lambda: run_simulation(request, ChamberDependencies(filesystem_root=root)), n=50))
    return results


if __name__ == "__main__":
    for r in run_all():
        print(f"{r.name}: mean={r.mean_ms:.4f}ms p95={r.p95_ms:.4f}ms (n={r.n})")
