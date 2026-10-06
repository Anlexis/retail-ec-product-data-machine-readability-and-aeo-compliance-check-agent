"""AgentCore Platform v1.0 — RET-C2-196 ComplianceReportGenerateNode"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict (partial-dict return)
#  - required_trust_level: ANONYMOUS (inner domain node)
#  - Output gate: module-level _enforce_output_invariant() called from execute()
#    (NOT via the _extra_security_gate_output instance hook — the framework
#    auto-wraps those and the wrapped None return breaks the real .invoke() path)
#  - Audit: emit_trace_event called positionally in execute()
#  - No ctor args — SDK-v1 nodes instantiated with ComplianceReportGenerateNode()

import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.aeo_score_calculate_node import AEO_THRESHOLD, SCORE_WEIGHTS
from src.services.input_guard import is_inert_identifier

# What this report promises its reader, and what the gate below enforces:
#
#   Every score it prints is a whole number out of 100, every dimension score is
#   within that dimension's weight, the PASS/FAIL flag agrees with the threshold,
#   and the summary counts add up to the rows beneath them.
#
# There is no monetary precision grid here because this report renders no
# monetary values — prices are read as a completeness signal and never printed.
# The scoring invariant above is the equivalent guarantee for this agent, and it
# is enforced against the RENDERED TEXT rather than against the computed figures
# alone, so a formatting defect is caught as well as an arithmetic one.

WITHHELD_NOTICE = (
    "AEO compliance report withheld: the generated report failed its own output "
    "check and was not released. No partial content is included. Re-run the "
    "request; if it recurs, the listing data is triggering a defect worth reporting."
)

_SCORE_LINE = re.compile(r"^### (?P<sku>.+?) -- Score: (?P<score>-?\d+)/100 \[(?P<flag>PASS|FAIL)\]$")
_DIMENSION_LINE = re.compile(r"^\| (?P<dimension>[A-Za-z ]+?) \| (?P<score>-?\d+) ?!? \| (?P<max>-?\d+) \|$")
_SUMMARY_ROW = re.compile(r"^\| (?P<label>[^|]+?) \| (?P<value>-?\d+)(?:/100)? \|$")

_DIMENSION_TITLES = {d.replace("_", " ").title(): d for d in SCORE_WEIGHTS}


def enforce_output_invariant(report: str, metrics: dict[str, Any]) -> list[str]:
    """Return the invariant violations in a rendered report; empty means clean.

    Reads the report back rather than trusting the values that produced it: the
    two can disagree, and a reader of the report only ever sees the rendering.
    """
    violations: list[str] = []
    scores = metrics.get("scores", {})

    seen: dict[str, int] = {}
    for line in report.splitlines():
        match = _SCORE_LINE.match(line)
        if match:
            sku = match.group("sku")
            score = int(match.group("score"))
            flag = match.group("flag")
            if not is_inert_identifier(sku):
                violations.append("sku_id_not_inert")
            if not 0 <= score <= 100:
                violations.append("score_out_of_range")
            if (flag == "PASS") != (score >= AEO_THRESHOLD):
                violations.append("compliance_flag_disagrees_with_score")
            if sku in scores and scores[sku] != score:
                violations.append("rendered_score_differs_from_computed")
            seen[sku] = score
            continue

        match = _DIMENSION_LINE.match(line)
        if match:
            dimension = _DIMENSION_TITLES.get(match.group("dimension").strip())
            if dimension is None:
                continue
            score, maximum = int(match.group("score")), int(match.group("max"))
            if maximum != SCORE_WEIGHTS[dimension]:
                violations.append("dimension_weight_altered")
            if not 0 <= score <= maximum:
                violations.append("dimension_score_out_of_range")

    if len(seen) != metrics.get("sku_count", len(seen)):
        violations.append("rendered_sku_count_differs_from_computed")

    compliant = sum(1 for s in seen.values() if s >= AEO_THRESHOLD)
    if metrics.get("compliant_count", compliant) != compliant:
        violations.append("compliant_count_disagrees_with_rows")
    if metrics.get("non_compliant_count", len(seen) - compliant) != len(seen) - compliant:
        violations.append("non_compliant_count_disagrees_with_rows")

    average = metrics.get("average_score")
    if seen and average is not None and not min(seen.values()) <= average <= max(seen.values()):
        violations.append("average_outside_rendered_range")

    return sorted(set(violations))


class ComplianceReportGenerateNode(FunctionNode):
    """Generate the structured Markdown AEO compliance report.

    Synthesises scores, gaps and remediation priorities into a per-SKU report:
    an executive summary, a per-SKU scorecard, and a prioritised roadmap.

    The report is checked against its own stated invariant before it leaves this
    node (see `enforce_output_invariant`). On violation the report is replaced
    outright — not trimmed — and the node returns an error, because a compliance
    report whose figures do not hold together is worse than none: its whole value
    to the merchant is that the numbers can be acted on.

    Output state fields:
        compliance_report: str — formatted Markdown compliance report
        report_metrics: dict — the figures rendered, for the backbone boundary
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Build the report from the upstream domain outputs and gate it."""
        aeo_scores = state.get("aeo_scores", {})
        remediation_priorities = state.get("remediation_priorities", [])
        correlation_id = state.get("correlation_id", "")

        if not aeo_scores:
            emit_trace_event(
                "compliance_report_generate_no_scores",
                {"correlation_id": correlation_id},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["ComplianceReportGenerateNode: aeo_scores is empty"],
            }

        metrics = self._metrics(aeo_scores)
        report = self._build_report(aeo_scores, remediation_priorities, metrics)

        violations = enforce_output_invariant(report, metrics)
        if violations:
            emit_trace_event(
                "compliance_report_withheld",
                {"violations": violations, "correlation_id": correlation_id},
                state,
            )
            # Every output-bearing field is cleared, and the replacement is
            # truthy on purpose: the backbone envelope falls back to `result`
            # whenever the formatted output is falsy, so an empty string here
            # would re-open the very channel this is closing.
            return {
                "compliance_report": WITHHELD_NOTICE,
                "report_metrics": {},
                "status": AgentStatus.ERROR,
                "error_log": ["ComplianceReportGenerateNode: output invariant violated"],
            }

        emit_trace_event(
            "compliance_report_generated",
            {
                "sku_count": metrics["sku_count"],
                "report_length": len(report),
                "non_compliant_skus": metrics["non_compliant_count"],
                "correlation_id": correlation_id,
            },
            state,
        )

        return {
            "compliance_report": report,
            "report_metrics": metrics,
            "status": AgentStatus.SUCCESS,
        }

    # ── Figures ───────────────────────────────────────────────────────────────

    def _metrics(self, aeo_scores: dict[str, Any]) -> dict[str, Any]:
        scores = {sku: int(info.get("score", 0)) for sku, info in aeo_scores.items()}
        compliant = sum(1 for s in scores.values() if s >= AEO_THRESHOLD)
        return {
            "sku_count": len(scores),
            "compliant_count": compliant,
            "non_compliant_count": len(scores) - compliant,
            "average_score": sum(scores.values()) // len(scores) if scores else 0,
            "scores": scores,
        }

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _build_report(
        self,
        aeo_scores: dict[str, Any],
        remediation_priorities: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> str:
        lines: list[str] = [
            "# AEO Compliance Report",
            "",
            "## Executive Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total SKUs analyzed | {metrics['sku_count']} |",
            f"| Compliant SKUs (score >= {AEO_THRESHOLD}) | {metrics['compliant_count']} |",
            f"| Non-compliant SKUs | {metrics['non_compliant_count']} |",
            f"| Fleet average AEO score | {metrics['average_score']}/100 |",
            f"| High-priority remediation items | "
            f"{sum(1 for r in remediation_priorities if r.get('priority') == 1)} |",
            "",
            "Scores are whole numbers out of 100, normalised over the dimensions that",
            "could be evaluated for each SKU. Where a dimension could not be evaluated",
            "it is named under that SKU and excluded from its score rather than counted",
            "as a failure.",
            "",
            "## Per-SKU AEO Scorecard",
            "",
        ]

        for sku_id, info in sorted(aeo_scores.items()):
            score = int(info.get("score", 0))
            flag = "PASS" if score >= AEO_THRESHOLD else "FAIL"
            lines.append(f"### {sku_id} -- Score: {score}/100 [{flag}]")
            lines.append("")
            lines.append("| Dimension | Score | Max |")
            lines.append("|-----------|-------|-----|")
            for dimension, points in sorted(info.get("breakdown", {}).items()):
                maximum = SCORE_WEIGHTS.get(dimension, 0)
                marker = "" if points >= maximum else " !"
                label = dimension.replace("_", " ").title()
                lines.append(f"| {label} | {points}{marker} | {maximum} |")
            unavailable = info.get("unavailable_dimensions", [])
            if unavailable:
                names = ", ".join(d.replace("_", " ") for d in sorted(unavailable))
                lines.append("")
                lines.append(
                    f"Not evaluated for this SKU ({names}): the source field did not reach "
                    "the checker intact, so it is excluded from the score above rather than "
                    "scored as missing. Re-submit this listing through the structured "
                    "product context to have it assessed."
                )
            lines.append("")

        lines.append("## Prioritized Remediation Roadmap")
        lines.append("")
        if not remediation_priorities:
            lines.append("No remediation items identified -- all SKUs are AEO compliant.")
        else:
            for tier, label in (
                (1, "Critical (Priority 1)"),
                (2, "Important (Priority 2)"),
                (3, "Optional (Priority 3)"),
            ):
                tier_items = [r for r in remediation_priorities if r.get("priority") == tier]
                if not tier_items:
                    continue
                lines.append(f"### {label}")
                lines.append("")
                for item in tier_items:
                    gap = str(item.get("gap_type", "")).replace("_", " ").title()
                    lines.append(f"**{item.get('sku_id', '')} -- {gap}**")
                    lines.append(f"- Field: {item.get('field', '')}")
                    lines.append(f"- Action: {item.get('action', '')}")
                    lines.append(f"- Estimated impact: {item.get('estimated_impact', '')}")
                    lines.append(f"- Effort: {item.get('effort', '')}")
                    lines.append(f"- Score points recoverable: {item.get('score_lost', 0)}")
                    lines.append("")

        lines.append("---")
        lines.append("Report generated by the EC Product AEO Compliance Check Agent.")
        return "\n".join(lines)
