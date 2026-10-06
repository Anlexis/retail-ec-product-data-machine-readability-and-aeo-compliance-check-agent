"""AgentCore Platform v1.0 — RET-C2-196 State Schema"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from typing import Any

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """RET-C2-196 ECProductAEOComplianceCheckAgent state.

    Extends AgentState with EC product AEO compliance check fields.
    All shared fields (user_input, status, session_id, node_history,
    error_log, hitl_*, validated_input, correlation_id, etc.) are
    inherited from AgentState.

    Domain-specific fields (all JSON-serializable primitives / lists / dicts):

    pre_process outputs:
        enriched_context   — channel and source metadata dict

    ProductDataInputNode output:
        product_data       — list of parsed SKU dicts
                             [{sku_id, title, description, category, attributes}]

    AEOScoreCalculateNode output:
        aeo_scores         — per-SKU AEO readability scores
                             {sku_id: {score: int(0-100), breakdown: dict}}

    GapIdentifyNode output:
        compliance_gaps    — list of compliance gap dicts
                             [{sku_id, gap_type, field, severity, description}]

    RemediationPrioritizeNode output:
        remediation_priorities — prioritized remediation items
                             [{sku_id, priority: int(1-3), action, estimated_impact, effort}]

    ComplianceReportGenerateNode output:
        compliance_report  — formatted Markdown compliance report string
        report_metrics     — the figures the report renders, for the output boundary

    Outer graph merge (via AEOComplianceWorkflowGraphNode.merge_output):
        result             — inner graph compliance_report mapped to outer state

    PostProcessNode output:
        formatted_output   — final formatted response string
    """

    # Pre-process enrichment
    enriched_context: dict[str, Any]

    # Inner domain workflow fields
    product_data: list[dict[str, Any]]  # [{sku_id, title, description, category, ...}]
    aeo_scores: dict[str, Any]  # {sku_id: {"score": int, "breakdown": dict}}
    compliance_gaps: list[dict[str, Any]]  # [{sku_id, gap_type, field, severity, ...}]
    remediation_priorities: list[dict[str, Any]]  # [{sku_id, priority, action, ...}]
    compliance_report: str  # formatted Markdown compliance report

    # Figures the report renders, carried alongside it so the output boundary can
    # check the rendering against the computation instead of re-deriving it:
    #   {sku_count, compliant_count, non_compliant_count, average_score,
    #    scores: {sku_id: int}, max_dimension: {dimension: int}}
    report_metrics: dict[str, Any]

    # Outer graph merge fields
    result: str  # mapped from inner graph get_output()
    formatted_output: str  # from PostProcessNode
