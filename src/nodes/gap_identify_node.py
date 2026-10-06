"""AgentCore Platform v1.0 — RET-C2-196 GapIdentifyNode"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict (partial-dict return)
#  - required_trust_level: ANONYMOUS (inner domain node)
#  - Audit: emit_trace_event called positionally in execute()
#  - No ctor args — SDK-v1 nodes instantiated with GapIdentifyNode()

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.aeo_score_calculate_node import AEO_THRESHOLD, SCORE_WEIGHTS

# dimension -> (listing field, base severity, what the merchant should know)
DIMENSION_LABELS: dict[str, tuple[str, str, str]] = {
    "title_quality": (
        "title",
        "HIGH",
        "Title is too short or lacks descriptive keywords",
    ),
    "description_depth": (
        "description",
        "HIGH",
        "Product description is too brief for AI agent parsing",
    ),
    "category_precision": (
        "category",
        "MEDIUM",
        "Category field is missing or set to 'unknown'",
    ),
    "attribute_completeness": (
        "attributes/brand/price",
        "MEDIUM",
        "Key attributes (brand, price, structured attrs) are missing",
    ),
    "image_availability": (
        "image_url",
        "LOW",
        "No product image URL — reduces AI agent visual matching",
    ),
}


class GapIdentifyNode(FunctionNode):
    """Identify the specific AEO compliance gaps behind each SKU's score.

    For every dimension scoring below its weight, records which listing field is
    responsible, how many points it costs, and how serious it is. A dimension the
    scoring node could not evaluate produces no gap at all: reporting one would
    tell the merchant to fix a field this agent never saw the real value of.

    Output state fields:
        compliance_gaps: list — [{sku_id, gap_type, field, severity, ...}]
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Derive compliance gaps from the aeo_scores breakdown."""
        aeo_scores = state.get("aeo_scores", {})
        correlation_id = state.get("correlation_id", "")

        if not aeo_scores:
            emit_trace_event(
                "gap_identify_no_scores",
                {"correlation_id": correlation_id},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["GapIdentifyNode: aeo_scores is empty"],
            }

        compliance_gaps: list[dict[str, Any]] = []
        for sku_id, score_info in aeo_scores.items():
            compliance_gaps.extend(self._gaps_for_sku(sku_id, score_info))

        critical_count = sum(1 for g in compliance_gaps if g["severity"] == "HIGH")
        suppressed = sum(len(v.get("unavailable_dimensions", [])) for v in aeo_scores.values())

        emit_trace_event(
            "gap_identified",
            {
                "total_gaps": len(compliance_gaps),
                "critical_gaps": critical_count,
                "affected_skus": len({g["sku_id"] for g in compliance_gaps}),
                "suppressed_unavailable_dimensions": suppressed,
                "correlation_id": correlation_id,
            },
            state,
        )

        return {"compliance_gaps": compliance_gaps, "status": AgentStatus.SUCCESS}

    def _gaps_for_sku(self, sku_id: str, score_info: dict[str, Any]) -> list[dict[str, Any]]:
        breakdown = score_info.get("breakdown", {})
        overall = score_info.get("score", 0)
        gaps: list[dict[str, Any]] = []

        for dimension, awarded in breakdown.items():
            max_score = SCORE_WEIGHTS.get(dimension, 0)
            if awarded >= max_score or dimension not in DIMENSION_LABELS:
                continue
            field, severity, description = DIMENSION_LABELS[dimension]
            # A SKU already failing overall makes even a minor gap worth doing.
            if overall < AEO_THRESHOLD and severity == "LOW":
                severity = "MEDIUM"
            gaps.append(
                {
                    "sku_id": sku_id,
                    "gap_type": dimension,
                    "field": field,
                    "severity": severity,
                    "description": description,
                    "score_lost": max_score - awarded,
                    "current_score": awarded,
                    "max_score": max_score,
                }
            )
        return gaps
