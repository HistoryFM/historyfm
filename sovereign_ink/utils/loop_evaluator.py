"""Loop convergence evaluator for quality-loop governance.

Codifies the 3-of-5 metric improvement rule and consecutive-pass
convergence criteria that were previously documented but not enforced
in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

TRACKED_METRICS = [
    "immediate_jeopardy_deficit_scenes_per_10k_words",
    "exposition_drag_runs_per_10k_words",
    "ending_propulsion_deficit_flag_rate",
    "offstage_opposition_overuse_flag_rate",
    "dialogue_uniformity_flag_rate",
]

PRIMARY_CANARY_METRICS = [
    "offstage_opposition_overuse_flag_rate",
    "immediate_jeopardy_deficit_scenes_per_10k_words",
]

SECONDARY_CANARY_METRICS = [
    "ending_propulsion_deficit_flag_rate",
    "exposition_drag_runs_per_10k_words",
]


@dataclass
class LoopSnapshot:
    """Quality metrics captured at the end of one loop iteration."""

    loop_id: str
    track: str
    chapters_included: list[int]
    timestamp: str
    metrics: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "loop_id": self.loop_id,
            "track": self.track,
            "chapters_included": self.chapters_included,
            "timestamp": self.timestamp,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LoopSnapshot:
        return cls(
            loop_id=data["loop_id"],
            track=data["track"],
            chapters_included=data["chapters_included"],
            timestamp=data["timestamp"],
            metrics=data["metrics"],
        )

    @classmethod
    def from_quality_aggregate(
        cls,
        aggregate: dict,
        loop_id: str,
        track: str,
    ) -> LoopSnapshot:
        """Build a snapshot from a Stage 5 quality aggregate artifact."""
        polish = aggregate.get("normalized_per_10k_words", {}).get(
            "v3_polish", {}
        )
        flag_rates = aggregate.get("flag_rates", {}).get("v3_polish", {})

        metrics = {
            "immediate_jeopardy_deficit_scenes_per_10k_words": float(
                polish.get(
                    "immediate_jeopardy_deficit_scenes_per_10k_words", 0
                )
            ),
            "exposition_drag_runs_per_10k_words": float(
                polish.get("exposition_drag_runs_per_10k_words", 0)
            ),
            "ending_propulsion_deficit_flag_rate": float(
                flag_rates.get("ending_propulsion_deficit_flag_rate", 0)
            ),
            "offstage_opposition_overuse_flag_rate": float(
                flag_rates.get("offstage_opposition_overuse_flag_rate", 0)
            ),
            "dialogue_uniformity_flag_rate": float(
                flag_rates.get("dialogue_uniformity_flag_rate", 0)
            ),
        }

        return cls(
            loop_id=loop_id,
            track=track,
            chapters_included=aggregate.get("chapters_included", []),
            timestamp=aggregate.get(
                "generated_at", datetime.now().isoformat()
            ),
            metrics=metrics,
        )


@dataclass
class LoopEvaluation:
    """Result of comparing two consecutive loop snapshots."""

    current_loop: str
    baseline_loop: str
    metric_deltas: dict[str, float]
    improved: list[str]
    regressed: list[str]
    stable: list[str]
    gate_passed: bool
    consecutive_passes: int
    converged: bool

    def to_dict(self) -> dict:
        return {
            "current_loop": self.current_loop,
            "baseline_loop": self.baseline_loop,
            "metric_deltas": self.metric_deltas,
            "improved": self.improved,
            "regressed": self.regressed,
            "stable": self.stable,
            "gate_passed": self.gate_passed,
            "consecutive_passes": self.consecutive_passes,
            "converged": self.converged,
        }


def compute_loop_metrics(quality_reports: dict[int, dict]) -> dict[str, float]:
    """Compute the 5 core loop metrics from per-chapter quality reports.

    Each report is expected to have ``v3_polish.counts`` and
    ``v3_polish.word_count`` from :func:`build_quality_snapshot`.
    """
    if not quality_reports:
        return {m: 0.0 for m in TRACKED_METRICS}

    total_words = 0
    total_jeopardy = 0
    total_expo = 0
    ending_deficit = 0
    offstage_overuse = 0
    dialogue_uniform = 0
    chapter_count = len(quality_reports)

    for report in quality_reports.values():
        polished = report.get("v3_polish", {})
        counts = polished.get("counts", {})
        total_words += int(polished.get("word_count", 0))
        total_jeopardy += int(
            counts.get("immediate_jeopardy_deficit_scenes", 0)
        )
        total_expo += int(counts.get("exposition_drag_runs", 0))
        ending_deficit += int(
            counts.get("ending_propulsion_deficit_flag", 0)
        )
        offstage_overuse += int(
            counts.get("offstage_opposition_overuse_flag", 0)
        )
        dialogue_uniform += int(
            counts.get("dialogue_uniformity_flag", 0)
        )

    denom_10k = max(total_words / 10000.0, 1e-9)
    ch = max(chapter_count, 1)

    return {
        "immediate_jeopardy_deficit_scenes_per_10k_words": round(
            total_jeopardy / denom_10k, 4
        ),
        "exposition_drag_runs_per_10k_words": round(
            total_expo / denom_10k, 4
        ),
        "ending_propulsion_deficit_flag_rate": round(
            ending_deficit / ch, 4
        ),
        "offstage_opposition_overuse_flag_rate": round(
            offstage_overuse / ch, 4
        ),
        "dialogue_uniformity_flag_rate": round(
            dialogue_uniform / ch, 4
        ),
    }


def evaluate_loop(
    current: LoopSnapshot,
    baseline: LoopSnapshot,
    improvement_threshold: float = 0.0,
    required_improvements: int = 3,
    consecutive_passes_for_convergence: int = 2,
    prior_consecutive_passes: int = 0,
) -> LoopEvaluation:
    """Compare current loop metrics against baseline.

    A loop passes the gate if at least ``required_improvements`` of the 5
    tracked metrics improve or remain stable.  Convergence is declared when
    ``consecutive_passes_for_convergence`` consecutive loops pass.

    All tracked metrics are "lower is better".
    """
    improved: list[str] = []
    regressed: list[str] = []
    stable: list[str] = []
    deltas: dict[str, float] = {}

    for metric in TRACKED_METRICS:
        cur = current.metrics.get(metric, 0.0)
        base = baseline.metrics.get(metric, 0.0)
        delta = cur - base
        deltas[metric] = round(delta, 4)

        if delta < -improvement_threshold:
            improved.append(metric)
        elif delta > improvement_threshold:
            regressed.append(metric)
        else:
            stable.append(metric)

    gate_passed = (len(improved) + len(stable)) >= required_improvements
    consecutive = (prior_consecutive_passes + 1) if gate_passed else 0
    converged = consecutive >= consecutive_passes_for_convergence

    return LoopEvaluation(
        current_loop=current.loop_id,
        baseline_loop=baseline.loop_id,
        metric_deltas=deltas,
        improved=improved,
        regressed=regressed,
        stable=stable,
        gate_passed=gate_passed,
        consecutive_passes=consecutive,
        converged=converged,
    )


@dataclass
class CanaryReport:
    """Comparison of canary (pressure-contract-enabled) vs baseline run."""

    canary_track: str
    baseline_track: str
    primary_improved: list[str]
    primary_regressed: list[str]
    secondary_improved: list[str]
    secondary_regressed: list[str]
    cost_per_chapter_canary: float
    cost_per_chapter_baseline: float
    retries_per_chapter_canary: float
    retries_per_chapter_baseline: float
    scene_contract_pass_rate: float
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "canary_track": self.canary_track,
            "baseline_track": self.baseline_track,
            "primary_improved": self.primary_improved,
            "primary_regressed": self.primary_regressed,
            "secondary_improved": self.secondary_improved,
            "secondary_regressed": self.secondary_regressed,
            "cost_per_chapter_canary": self.cost_per_chapter_canary,
            "cost_per_chapter_baseline": self.cost_per_chapter_baseline,
            "retries_per_chapter_canary": self.retries_per_chapter_canary,
            "retries_per_chapter_baseline": self.retries_per_chapter_baseline,
            "scene_contract_pass_rate": self.scene_contract_pass_rate,
            "recommendation": self.recommendation,
        }


def evaluate_canary(
    canary_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    canary_track: str = "canary",
    baseline_track: str = "baseline",
    cost_canary: float = 0.0,
    cost_baseline: float = 0.0,
    retries_canary: float = 0.0,
    retries_baseline: float = 0.0,
    scene_contract_pass_rate: float = 1.0,
    cost_blowout_factor: float = 2.5,
) -> CanaryReport:
    """Compare canary (pressure-contract-enabled) run against baseline.

    The canary passes if:
    - Both primary metrics (offstage opposition, immediate jeopardy) improve
    - Cost does not exceed *cost_blowout_factor* × baseline
    """
    primary_improved: list[str] = []
    primary_regressed: list[str] = []
    secondary_improved: list[str] = []
    secondary_regressed: list[str] = []

    for metric in PRIMARY_CANARY_METRICS:
        delta = canary_metrics.get(metric, 0.0) - baseline_metrics.get(metric, 0.0)
        if delta < 0:
            primary_improved.append(metric)
        elif delta > 0:
            primary_regressed.append(metric)

    for metric in SECONDARY_CANARY_METRICS:
        delta = canary_metrics.get(metric, 0.0) - baseline_metrics.get(metric, 0.0)
        if delta < 0:
            secondary_improved.append(metric)
        elif delta > 0:
            secondary_regressed.append(metric)

    cost_ok = (
        cost_baseline <= 0
        or cost_canary <= cost_baseline * cost_blowout_factor
    )
    primary_pass = len(primary_regressed) == 0 and len(primary_improved) >= 1

    if primary_pass and cost_ok:
        recommendation = "PROCEED — primary metrics improved, cost within bounds"
    elif primary_pass and not cost_ok:
        recommendation = (
            f"HOLD — quality improved but cost blowout "
            f"({cost_canary:.2f} vs {cost_baseline:.2f}×{cost_blowout_factor})"
        )
    elif not primary_pass:
        recommendation = (
            f"INVESTIGATE — primary metrics regressed: "
            f"{', '.join(primary_regressed)}"
        )
    else:
        recommendation = "INVESTIGATE — inconclusive"

    return CanaryReport(
        canary_track=canary_track,
        baseline_track=baseline_track,
        primary_improved=primary_improved,
        primary_regressed=primary_regressed,
        secondary_improved=secondary_improved,
        secondary_regressed=secondary_regressed,
        cost_per_chapter_canary=cost_canary,
        cost_per_chapter_baseline=cost_baseline,
        retries_per_chapter_canary=retries_canary,
        retries_per_chapter_baseline=retries_baseline,
        scene_contract_pass_rate=scene_contract_pass_rate,
        recommendation=recommendation,
    )


def format_canary_report(report: CanaryReport) -> str:
    """Format a canary comparison report for human review."""
    lines = [
        f"## Canary Evaluation: {report.canary_track} vs {report.baseline_track}",
        "",
        f"**Recommendation:** {report.recommendation}",
        "",
        "### Primary Metrics (must improve)",
    ]
    for m in PRIMARY_CANARY_METRICS:
        if m in report.primary_improved:
            lines.append(f"  - {m}: IMPROVED ✓")
        elif m in report.primary_regressed:
            lines.append(f"  - {m}: REGRESSED ✗")
        else:
            lines.append(f"  - {m}: STABLE")

    lines.append("")
    lines.append("### Secondary Metrics")
    for m in SECONDARY_CANARY_METRICS:
        if m in report.secondary_improved:
            lines.append(f"  - {m}: IMPROVED")
        elif m in report.secondary_regressed:
            lines.append(f"  - {m}: REGRESSED")
        else:
            lines.append(f"  - {m}: STABLE")

    lines.extend([
        "",
        "### Cost & Efficiency",
        f"  - Cost/chapter (canary): ${report.cost_per_chapter_canary:.3f}",
        f"  - Cost/chapter (baseline): ${report.cost_per_chapter_baseline:.3f}",
        f"  - Retries/chapter (canary): {report.retries_per_chapter_canary:.1f}",
        f"  - Retries/chapter (baseline): {report.retries_per_chapter_baseline:.1f}",
        f"  - Scene contract pass rate: {report.scene_contract_pass_rate:.0%}",
    ])

    return "\n".join(lines)


def format_loop_evaluation(evaluation: LoopEvaluation) -> str:
    """Format a loop evaluation into a human-readable report."""
    lines = [
        f"## Loop Evaluation: {evaluation.current_loop} vs "
        f"{evaluation.baseline_loop}",
        "",
        f"Gate result: {'PASSED' if evaluation.gate_passed else 'FAILED'}",
        f"Consecutive passes: {evaluation.consecutive_passes}",
        f"Converged: {'YES' if evaluation.converged else 'NO'}",
        "",
        "### Metric Deltas (negative = improvement)",
        "",
    ]

    for metric in TRACKED_METRICS:
        delta = evaluation.metric_deltas.get(metric, 0.0)
        if metric in evaluation.improved:
            direction = "improved"
        elif metric in evaluation.regressed:
            direction = "regressed"
        else:
            direction = "stable"
        sign = "+" if delta > 0 else ""
        lines.append(f"- {metric}: {sign}{delta} ({direction})")

    lines.append("")
    lines.append(
        f"Summary: {len(evaluation.improved)} improved, "
        f"{len(evaluation.stable)} stable, "
        f"{len(evaluation.regressed)} regressed"
    )

    return "\n".join(lines)
