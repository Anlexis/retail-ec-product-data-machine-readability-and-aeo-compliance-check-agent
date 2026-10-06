"""AgentCore Platform v1.0 — RET-C2-196 RemediationPrioritizeNode"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict (partial-dict return)
#  - required_trust_level: ANONYMOUS (inner domain node — review finding 5 ruling)
#  - S-4: emit_trace_event called positionally in execute()
#  - No ctor args — SDK-v1 nodes instantiated with RemediationPrioritizeNode()

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Priority tiers (lower number = higher priority)
_PRIORITY_MAP = {
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
}

_REMEDIATION_ACTIONS = {
    "title_quality": (
        "Rewrite product title: aim for 30–80 chars, include brand + model + key attribute. "
        "Example: 'Sony WH-1000XM5 Wireless Noise Cancelling Headphones, Black'"
    ),
    "description_depth": (
        "Expand product description to 60+ words. Include: product function, key specs, "
        "use cases, compatibility. Use structured bullet points for AI parseability."
    ),
    "category_precision": (
        "Set a precise category path (e.g. 'Electronics > Audio > Headphones > Wireless'). "
        "Avoid generic 'Other' or blank values that prevent AI category matching."
    ),
    "attribute_completeness": (
        "Populate brand, price, and at least 3 structured attributes (color, size, material, "
        "compatibility). Structured attributes directly feed AI shopping agent filter queries."
    ),
    "image_availability": (
        "Add a high-quality product image URL. AI shopping agents use images for visual "
        "similarity matching. Minimum: 500x500px, white background, product centered."
    ),
}

_ESTIMATED_IMPACT = {
    "title_quality": "HIGH — title is the primary AI agent match signal",
    "description_depth": "HIGH — description drives semantic search relevance",
    "category_precision": "MEDIUM — category determines agent discovery scope",
    "attribute_completeness": "MEDIUM — attributes enable filter-based queries",
    "image_availability": "LOW — visual matching is secondary to text signals",
}

_EFFORT_ESTIMATE = {
    "title_quality": "15 min/SKU",
    "description_depth": "30 min/SKU",
    "category_precision": "5 min/SKU",
    "attribute_completeness": "20 min/SKU",
    "image_availability": "60 min/SKU (photo/shoot or image sourcing)",
}


class RemediationPrioritizeNode(FunctionNode):
    """Prioritize AEO compliance gaps by business impact and remediation effort.

    Assigns priority tiers (1=Critical, 2=Important, 3=Optional) to each
    compliance gap based on severity, score_lost, and estimated AI traffic
    impact. Groups gaps by SKU for a per-SKU remediation roadmap.

    Output state fields:
        remediation_priorities: list — [
            {sku_id, priority, gap_type, action, estimated_impact, effort, score_lost}
        ]
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Prioritize compliance gaps into a remediation roadmap.

        Returns partial dict with remediation_priorities and status.
        """
        compliance_gaps = state.get("compliance_gaps", [])

        if compliance_gaps is None:
            emit_trace_event(
                "remediation_prioritize_no_gaps",
                {"correlation_id": state.get("correlation_id", "")},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["RemediationPrioritizeNode: compliance_gaps is None"],
            }

        # Sort by priority (HIGH first), then score_lost descending
        sorted_gaps = sorted(
            compliance_gaps,
            key=lambda g: (_PRIORITY_MAP.get(g.get("severity", "LOW"), 3), -g.get("score_lost", 0)),
        )

        remediation_priorities: list[dict[str, Any]] = []
        for gap in sorted_gaps:
            gap_type = gap.get("gap_type", "")
            remediation_priorities.append(
                {
                    "sku_id": gap.get("sku_id", ""),
                    "priority": _PRIORITY_MAP.get(gap.get("severity", "LOW"), 3),
                    "priority_label": gap.get("severity", "LOW"),
                    "gap_type": gap_type,
                    "field": gap.get("field", ""),
                    "action": _REMEDIATION_ACTIONS.get(gap_type, "Review and improve this field."),
                    "estimated_impact": _ESTIMATED_IMPACT.get(gap_type, "MEDIUM"),
                    "effort": _EFFORT_ESTIMATE.get(gap_type, "30 min/SKU"),
                    "score_lost": gap.get("score_lost", 0),
                }
            )

        high_priority_count = sum(1 for r in remediation_priorities if r["priority"] == 1)

        emit_trace_event(
            "remediation_prioritized",
            {
                "total_items": len(remediation_priorities),
                "high_priority_items": high_priority_count,
                "affected_skus": len({r["sku_id"] for r in remediation_priorities}),
                "correlation_id": state.get("correlation_id", ""),
            },
            state,
        )

        return {
            "remediation_priorities": remediation_priorities,
            "status": AgentStatus.SUCCESS,
        }
