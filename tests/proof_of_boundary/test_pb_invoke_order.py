# PB-6: Backbone Invoke Order Verification — RET-C2-196
#
# Verifies that ECProductAEOComplianceCheckAgent().invoke() with a VERIFIED_EXTERNAL
# caller produces node_history = [InitializeNode, PreProcessNode,
# AEOComplianceWorkflowGraphNode, PostProcessNode, FinalizeNode].
#
# Requirements:
#   - caller_trust_level = VERIFIED_EXTERNAL (not INTERNAL — must exercise the real trust path)
#   - payload must yield AgentStatus.SUCCESS (non-SUCCESS short-circuits the backbone)
#   - NEVER use InvocationContext.for_internal() / INTERNAL context (masks inner-node trust-trap)
#
# Template-specific slots to fill per template:
#   _MAIN_SLOT_NODE : the GraphNode subclass name assigned to graph.main
#   _VALID_PAYLOAD  : a SUCCESS-yielding product listing input string


# ── Template-specific configuration ───────────────────────────────────────────

_MAIN_SLOT_NODE = "AEOComplianceWorkflowGraphNode"

# A valid product listing that exercises the full inner pipeline and returns SUCCESS.
# Includes title (30+ chars), description (60+ words), category, brand, price, image_url
# so that AEOScoreCalculateNode, GapIdentifyNode etc. all receive non-empty data.
_VALID_PAYLOAD = (
    "title=Wireless Bluetooth Headphones Premium Noise Cancelling\n"
    "description=High-quality wireless headphones delivering 30-hour battery life and advanced "
    "noise cancellation technology for commuters and remote workers. Supports USB-C fast charging "
    "and multi-device pairing. Compatible with iOS and Android smartphones and tablets.\n"
    "category=Electronics\n"
    "brand=AudioTech Pro\n"
    "price=12800\n"
    "image_url=https://cdn.example.com/products/headphones-001.jpg"
)


# ── PB-6 Test ─────────────────────────────────────────────────────────────────


class TestBackboneInvokeOrder:
    """PB-6: outer backbone must execute in the correct node order for a real external caller."""

    def test_backbone_node_history_order(self):
        """Full Graph().invoke() with VERIFIED_EXTERNAL caller asserts backbone node_history order.

        Exercises the real trust path (VERIFIED_EXTERNAL >= ANONYMOUS on inner nodes -> SUCCESS).
        A non-SUCCESS result (e.g. INTERNAL context trapping inner ANONYMOUS nodes) would
        short-circuit main -> finalize, skipping post_process -> the history check would fail.
        """
        from framework.nodes.defaults.initialize_node import InitializeNode
        from framework.nodes.defaults.finalize_node import FinalizeNode
        from framework.schemas.agent_status import AgentStatus
        from framework.schemas.invocation_context import InvocationContext
        from framework.schemas.trust_level import TrustLevel
        from src.graph.graph import ECProductAEOComplianceCheckAgent, AEOComplianceWorkflowGraphNode
        from src.nodes.pre_process_node import PreProcessNode
        from src.nodes.post_process_node import PostProcessNode

        agent = ECProductAEOComplianceCheckAgent()
        agent.compile()

        # VERIFIED_EXTERNAL: exercises the real external caller trust path.
        # NEVER use for_internal() here -- internal context masks the trust-trap.
        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        result = agent.invoke(_VALID_PAYLOAD, ctx=ctx)

        # Must succeed -- a non-SUCCESS status means the backbone was short-circuited
        assert result["status"] == AgentStatus.SUCCESS, (
            f"Expected AgentStatus.SUCCESS but got {result['status']}. " f"error_log: {result.get('error_log', [])}"
        )

        # Output must be populated (compliance report)
        assert result["output"], "result['output'] must be a non-empty compliance report string"

        # Backbone node history order
        node_history = result.get("node_history", [])
        expected_class_names = [
            InitializeNode.__name__,  # "InitializeNode"
            PreProcessNode.__name__,  # "PreProcessNode"
            AEOComplianceWorkflowGraphNode.__name__,  # "AEOComplianceWorkflowGraphNode"
            PostProcessNode.__name__,  # "PostProcessNode"
            FinalizeNode.__name__,  # "FinalizeNode"
        ]

        # node_history may contain class names (str) or class objects -- normalise to names
        history_names = [n.__name__ if isinstance(n, type) else str(n) for n in node_history]

        assert history_names == expected_class_names, (
            f"Backbone node_history order mismatch.\n"
            f"Expected: {expected_class_names}\n"
            f"Actual:   {history_names}"
        )

    def test_empty_input_returns_error_status(self):
        """Empty user_input short-circuits at pre_process -> ERROR (no backbone violation)."""
        from framework.schemas.agent_status import AgentStatus
        from framework.schemas.invocation_context import InvocationContext
        from framework.schemas.trust_level import TrustLevel
        from src.graph.graph import ECProductAEOComplianceCheckAgent

        agent = ECProductAEOComplianceCheckAgent()
        agent.compile()

        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        result = agent.invoke("", ctx=ctx)

        assert result["status"] == AgentStatus.ERROR
