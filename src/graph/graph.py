"""AgentCore Platform v1.0 — RET-C2-196 ECProductAEOComplianceCheckAgent"""

# Cat 2 outer graph — AgentBaseGraph + GraphNode in the main slot.
#
# The fixed 5-node backbone is identical to Cat 1:
#   START → initialize → pre_process → main (GraphNode) → post_process → finalize → END
#
# Domain complexity is encapsulated in AEOComplianceWorkflowGraphNode,
# which delegates to the inner DomainWorkflowGraph.
#
# Class name: ECProductAEOComplianceCheckAgent
#   MUST match the manifest entry point and src/api/server.py import.
#
# Rules:
#   - Inherits AgentBaseGraph (direct framework inheritance)
#   - Call super().register_nodes() first (injects initialize + finalize)
#   - GraphNode subclass assigned to the main slot
#   - Do NOT override add_edges() on the outer graph

from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState

from src.graph import context_bridge
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class AEOComplianceWorkflowGraphNode(GraphNode):
    """Wraps DomainWorkflowGraph; assigned to the `main` slot.

    Delegates the 5-step AEO compliance check domain workflow to
    DomainWorkflowGraph (inner BaseGraph).
    """

    # Re-raise inner graph exceptions as SubgraphError (fail-fast).
    error_strategy: ClassVar[str] = "propagate"

    # HITL interrupts handled inside the inner graph only.
    propagate_hitl: ClassVar[bool] = False

    def get_subgraph(self) -> Any:
        """Instantiate and return the inner AEO compliance domain workflow graph."""
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        return DomainWorkflowGraph()

    def extract_input(self, state: AgentState) -> str:
        """Pass validated_input to the inner graph, and bridge the request context.

        This is the only hook the framework calls with the OUTER state before the
        subgraph runs, which makes it the one place the caller's request context
        can be handed across the boundary: the framework invokes the subgraph
        without an `input_context` argument, so an inner node reading
        `state["input_context"]` otherwise sees an empty mapping on every call —
        silently, with the structured product records the caller supplied simply
        absent. The inner graph seeds it back in `_extra_initial_state()`.
        """
        context_bridge.stash(state.get("input_context", {}))
        return str(state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Map inner graph sub_result fields back into the outer state.

        sub_result is the dict returned by DomainWorkflowGraph.get_output().
        Returns ONLY changed state keys (never the full state).
        Designed together with DomainWorkflowGraph.get_output() so field
        names and types are consistent.
        """
        return {
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
            "report_metrics": sub_result.get("report_metrics", {}),
        }


class ECProductAEOComplianceCheckAgent(AgentBaseGraph):
    """EC Product AEO Compliance Check Agent — RET-C2-196.

    Cat 2 outer graph. Domain logic is encapsulated in
    AEOComplianceWorkflowGraphNode (main slot), which runs the inner
    DomainWorkflowGraph (5-step AEO compliance check pipeline).

    Backbone: initialize → pre_process → main → post_process → finalize
    """

    @property
    def name(self) -> str:
        return "ECProductAEOComplianceCheckAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = AEOComplianceWorkflowGraphNode()
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
