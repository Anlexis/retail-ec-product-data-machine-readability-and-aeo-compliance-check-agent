"""AgentCore Platform v1.0 — RET-C2-196 DomainWorkflowGraph (inner BaseGraph)"""

# Inner graph for the AEO compliance check domain workflow.
# Called by AEOComplianceWorkflowGraphNode.get_subgraph() in graph.py.
#
# Pipeline (linear):
#   START → product_data_input → aeo_score_calculate → gap_identify
#         → remediation_prioritize → compliance_report_generate → END
#
# Rules:
#   - Inherits BaseGraph (fully custom topology — no sub-backbone)
#   - Implements all 7 BaseGraph abstract methods
#   - register_nodes() does NOT call super() (abstract in BaseGraph)
#   - Every domain node instantiated with NO ctor args (SDK-v1 rule)
#   - Do NOT register initialize / finalize (outer backbone concern)

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.graph import context_bridge
from src.nodes.aeo_score_calculate_node import AEOScoreCalculateNode
from src.nodes.compliance_report_generate_node import ComplianceReportGenerateNode
from src.nodes.gap_identify_node import GapIdentifyNode
from src.nodes.product_data_input_node import ProductDataInputNode
from src.nodes.remediation_prioritize_node import RemediationPrioritizeNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow graph for EC product AEO compliance check.

    Inherits BaseGraph for a fully custom linear topology.
    Called by AEOComplianceWorkflowGraphNode.get_subgraph() in graph.py.

    Pipeline:
        START
          → product_data_input      (parse product listing data from input)
          → aeo_score_calculate     (compute 0-100 AEO score per SKU)
          → gap_identify            (identify compliance gaps below threshold)
          → remediation_prioritize  (prioritize gaps by business impact)
          → compliance_report_generate  (generate Markdown compliance report)
          → END
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "aeo_compliance_workflow"

    @property
    def state_schema(self) -> type:
        return State

    # ── Config validation ─────────────────────────────────────────────────────

    def _validate_config(self) -> None:
        """No mandatory config keys for this deterministic domain workflow."""
        pass

    # ── Initial state ─────────────────────────────────────────────────────────

    def _extra_initial_state(self) -> dict[str, Any]:
        """Seed the caller's request context, which the framework does not forward.

        `GraphNode.execute()` calls `subgraph.invoke(user_input, session_id, ctx)`
        with no `input_context` argument, so without this the structured product
        records the caller supplied would be absent from the inner state and the
        pipeline would silently fall back to parsing free text. The outer node
        published them in `extract_input()`; see src/graph/context_bridge.py.
        """
        return {"input_context": context_bridge.peek()}

    # ── Node registration ─────────────────────────────────────────────────────

    def register_nodes(self) -> None:
        """Register all AEO compliance domain nodes.

        No super() call — BaseGraph.register_nodes() is abstract.
        All nodes instantiated with NO ctor args per SDK-v1 rule.
        """
        self._nodes["product_data_input"] = ProductDataInputNode()
        self._nodes["aeo_score_calculate"] = AEOScoreCalculateNode()
        self._nodes["gap_identify"] = GapIdentifyNode()
        self._nodes["remediation_prioritize"] = RemediationPrioritizeNode()
        self._nodes["compliance_report_generate"] = ComplianceReportGenerateNode()

    # ── Edge wiring ───────────────────────────────────────────────────────────

    def add_edges(self) -> None:
        """Wire the linear AEO compliance check topology."""
        self._sg.add_edge(START, "product_data_input")
        self._sg.add_edge("product_data_input", "aeo_score_calculate")
        self._sg.add_edge("aeo_score_calculate", "gap_identify")
        self._sg.add_edge("gap_identify", "remediation_prioritize")
        self._sg.add_edge("remediation_prioritize", "compliance_report_generate")
        self._sg.add_edge("compliance_report_generate", END)

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, state: State) -> str:
        """Linear topology — routing is not used but required by BaseGraph ABC.

        Annotated with this graph's own State rather than the base AgentState:
        LangGraph reads a path callable's annotation as its input schema and
        projects away fields the annotation does not carry, so a base-class
        annotation makes every domain field invisible to the callable. There are
        no `add_conditional_edges` in this graph today, so nothing depends on it
        yet — the annotation is correct so that adding one later cannot
        reintroduce the defect silently.
        """
        return END if state.get("status") == AgentStatus.ERROR.value else "compliance_report_generate"

    # ── Output shape ──────────────────────────────────────────────────────────

    def get_output(self, state: AgentState) -> dict[str, Any]:
        """Shape the sub_result dict returned to AEOComplianceWorkflowGraphNode.merge_output().

        Designed together with merge_output() in graph.py so field names match.
        `report_metrics` travels with the report so the backbone's output
        boundary can re-check the rendered figures against the computed ones
        without re-deriving them.
        """
        return {
            "output": state.get("compliance_report", ""),
            "status": state.get("status"),
            "report_metrics": state.get("report_metrics", {}),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
