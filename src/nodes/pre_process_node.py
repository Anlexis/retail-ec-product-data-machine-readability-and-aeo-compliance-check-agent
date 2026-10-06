"""AgentCore Platform v1.0 — RET-C2-196 PreProcessNode"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - Read input_context via state.get("input_context", {}) — read-only [C1]
#  - Trust gate: VERIFIED_EXTERNAL (this is the outer backbone external gate)
#  - Domain input check: inline in execute() (not via _extra_security_gate_input hook)
#  - Audit: emit_trace_event called positionally in execute()
#  - Never import from mediator/, api/, or other agents
#
# This node owns the caller contract. The HTTP adapter applies the same rules, but
# it is out of the path when the platform gateway calls the agent directly, so the
# guarantee has to be enforced here and provable by calling execute() with no
# framework wrapper in front of it. The rules themselves live in
# src/services/input_guard.py so the two enforcement points cannot drift.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.input_guard import MAX_INPUT_LENGTH, screen_text, validate_context


class PreProcessNode(FunctionNode):
    """Validate and enrich an incoming product-data compliance check request.

    Trust gate: VERIFIED_EXTERNAL — this backbone node is the external-facing
    gate; inner domain nodes run at ANONYMOUS.

    Domain input check: performed inline in execute() rather than through the
    _extra_security_gate_input hook, which the framework auto-wraps in a way that
    does not survive a None state.

    Refusals name the field and a closed-set reason. The rejected value is never
    echoed — not into the caller's error, and not into the audit event, which is
    the copy that persists.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Validate user_input and the request context for the compliance workflow.

        Returns:
            validated_input: stripped, screened user input string
            enriched_context: channel/source metadata dict
            status: AgentStatus.SUCCESS or AgentStatus.ERROR
        """
        user_input = state.get("user_input", "")
        correlation_id = state.get("correlation_id", "")

        # Type guard first: without it a list/dict/int would raise AttributeError
        # inside the screens instead of producing a clean validation error.
        if not isinstance(user_input, str):
            return self._refuse(
                state,
                "invalid_type",
                "user_input",
                "PreProcessNode: user_input must be a string",
            )

        if not user_input.strip():
            return self._refuse(
                state,
                "empty",
                "user_input",
                "PreProcessNode: user_input is empty or missing",
            )

        if len(user_input) > MAX_INPUT_LENGTH:
            return self._refuse(
                state,
                "too_long",
                "user_input",
                f"PreProcessNode: user_input exceeds {MAX_INPUT_LENGTH} characters",
            )

        hit = screen_text(user_input)
        if hit:
            return self._refuse(
                state,
                hit,
                "user_input",
                f"PreProcessNode: user_input rejected — {hit}",
            )

        # The request context is screened with the same rules and reduced to the
        # supported subset. Anything the caller sent that this version does not
        # declare is dropped here as well as at the adapter: an undeclared key is
        # not merely ignored downstream — it travels on the context channel, the
        # framework's first node returns that channel verbatim in its own result,
        # and a credential-shaped value there fails the run before any template
        # code gets to say why.
        raw_context = state.get("input_context", {})  # read-only [C1]
        accepted_context, refusals = validate_context(raw_context)
        if refusals:
            reason, field = refusals[0]
            return self._refuse(
                state,
                reason,
                field,
                f"PreProcessNode: input_context.{field} rejected — {reason}",
            )

        validated = user_input.strip()
        product_records = accepted_context.get("products", [])

        emit_trace_event(
            "pre_process_validated",
            {
                "input_length": len(validated),
                "context_product_count": len(product_records),
                "channel": accepted_context.get("channel", "unknown"),
                "correlation_id": correlation_id,
            },
            state,
        )

        return {
            "validated_input": validated,
            "input_context": accepted_context,
            "enriched_context": {
                "source": "ECProductAEOComplianceCheckAgent",
                "channel": accepted_context.get("channel", "unknown"),
                "merchant_id": accepted_context.get("merchant_id", ""),
            },
            "status": AgentStatus.SUCCESS,
        }

    def _refuse(self, state: dict[str, Any], reason: str, field: str, message: str) -> dict[str, Any]:
        """Emit the audit event and return the error partial. Never carries the value."""
        emit_trace_event(
            "pre_process_input_rejected",
            {
                "reason": reason,
                "field": field,
                "correlation_id": state.get("correlation_id", ""),
            },
            state,
        )
        return {
            "status": AgentStatus.ERROR,
            "error_log": [message],
        }
