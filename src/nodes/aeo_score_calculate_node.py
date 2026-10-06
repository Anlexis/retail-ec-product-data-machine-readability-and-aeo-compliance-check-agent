"""AgentCore Platform v1.0 — RET-C2-196 AEOScoreCalculateNode"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict (partial-dict return)
#  - required_trust_level: ANONYMOUS (inner domain node)
#  - Audit: emit_trace_event called positionally in execute()
#  - No ctor args — SDK-v1 nodes instantiated with AEOScoreCalculateNode()

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Scoring dimension weights (sum to 100), and the record field each one reads.
SCORE_WEIGHTS: dict[str, int] = {
    "title_quality": 20,  # descriptive, keyword-rich title
    "description_depth": 25,  # structured, complete description
    "category_precision": 15,  # accurate, specific category
    "attribute_completeness": 25,  # brand, price, attributes populated
    "image_availability": 15,  # image_url present and non-empty
}

# Which record fields a dimension depends on. Used to drop a dimension whose
# input never reached this node intact, rather than scoring the placeholder.
DIMENSION_INPUTS: dict[str, tuple[str, ...]] = {
    "title_quality": ("title",),
    "description_depth": ("description",),
    "category_precision": ("category",),
    "attribute_completeness": ("brand",),
    "image_availability": (),
}

AEO_THRESHOLD = 70  # normalised score below this = non-compliant


class AEOScoreCalculateNode(FunctionNode):
    """Calculate the AEO readability score (0–100) for each SKU.

    Five dimensions: title quality, description depth, category precision,
    attribute completeness, image availability. A SKU scoring below the threshold
    is one that AI shopping agents will struggle to parse for product discovery.

    Scores are normalised to 0–100 over the dimensions that could actually be
    evaluated. A dimension whose input arrived redacted by the platform's input
    filter is excluded from both the numerator and the denominator and named in
    `unavailable_dimensions`. Scoring it instead would award zero for a field the
    merchant filled in correctly — a confident finding about something this agent
    never saw.

    Output state fields:
        aeo_scores: dict — {sku_id: {score, breakdown, compliant, ...}}
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Calculate AEO scores for every SKU in product_data."""
        product_data = state.get("product_data", [])
        correlation_id = state.get("correlation_id", "")

        if not product_data:
            emit_trace_event(
                "aeo_score_calculate_no_data",
                {"correlation_id": correlation_id},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["AEOScoreCalculateNode: product_data is empty"],
            }

        aeo_scores: dict[str, Any] = {}
        for sku in product_data:
            sku_id = sku.get("sku_id", "unknown")
            aeo_scores[sku_id] = self._score_sku(sku)

        non_compliant = sum(1 for v in aeo_scores.values() if not v["compliant"])
        degraded = sum(1 for v in aeo_scores.values() if v["unavailable_dimensions"])

        emit_trace_event(
            "aeo_score_calculated",
            {
                "sku_count": len(aeo_scores),
                "non_compliant_count": non_compliant,
                "degraded_scoring_count": degraded,
                "threshold": AEO_THRESHOLD,
                "correlation_id": correlation_id,
            },
            state,
        )

        return {"aeo_scores": aeo_scores, "status": AgentStatus.SUCCESS}

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_sku(self, sku: dict[str, Any]) -> dict[str, Any]:
        redacted = set(sku.get("redacted_fields", []))
        unavailable = [
            dimension for dimension, inputs in DIMENSION_INPUTS.items() if any(field in redacted for field in inputs)
        ]

        breakdown = self._score_breakdown(sku)
        for dimension in unavailable:
            breakdown.pop(dimension, None)

        awarded = sum(breakdown.values())
        available = sum(SCORE_WEIGHTS[d] for d in breakdown)
        # Normalised so the reported figure is always out of 100 regardless of how
        # many dimensions were evaluable; the output boundary enforces that range.
        score = round(100 * awarded / available) if available else 0

        return {
            "score": score,
            "points_awarded": awarded,
            "points_available": available,
            "breakdown": breakdown,
            "unavailable_dimensions": unavailable,
            "compliant": score >= AEO_THRESHOLD,
        }

    def _score_breakdown(self, sku: dict[str, Any]) -> dict[str, int]:
        """Score a single SKU across every dimension, each capped at its weight."""
        breakdown: dict[str, int] = {}

        title = sku.get("title") or ""
        title_score = 0
        if len(title) >= 10:
            title_score += 10
        if len(title) >= 30:
            title_score += 5
        if title and title != title.upper():  # not all-caps keyword spam
            title_score += 5
        breakdown["title_quality"] = min(title_score, SCORE_WEIGHTS["title_quality"])

        description = sku.get("description") or ""
        words = len(description.split())
        description_score = 0
        if words >= 10:
            description_score += 10
        if words >= 30:
            description_score += 10
        if words >= 60:
            description_score += 5
        breakdown["description_depth"] = min(description_score, SCORE_WEIGHTS["description_depth"])

        category = sku.get("category") or ""
        if category and category.lower() not in ("unknown", "other"):
            category_score = 15
        elif category:
            category_score = 5
        else:
            category_score = 0
        breakdown["category_precision"] = min(category_score, SCORE_WEIGHTS["category_precision"])

        attribute_score = 0
        if sku.get("brand"):
            attribute_score += 8
        if sku.get("price"):
            attribute_score += 8
        attributes = sku.get("attributes") or {}
        if len(attributes) >= 1:
            attribute_score += 5
        if len(attributes) >= 3:
            attribute_score += 4
        breakdown["attribute_completeness"] = min(attribute_score, SCORE_WEIGHTS["attribute_completeness"])

        breakdown["image_availability"] = SCORE_WEIGHTS["image_availability"] if sku.get("image_url") else 0

        return breakdown
