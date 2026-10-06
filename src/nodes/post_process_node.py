"""AgentCore Platform v1.0 — RET-C2-196 PostProcessNode"""

# The backbone output boundary. Everything the caller sees passes through here.

import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security.credential_detector import detect_credentials_in_value
from shared.utils.audit_logger import emit_trace_event

# Local patterns kept because the framework detector does NOT cover them. Its
# patterns describe credential FORMATS — `AKIA…`, `sk_live_…`, `sk-…`, a JWT, a
# database URI, `Bearer <token>` — and match none of these labelled-assignment
# shapes. Delegating to the detector alone would therefore have made this gate
# NARROWER while looking like a tightening, so the check below is the UNION of
# the two: wider is safe, narrower is a bypass.
_LOCAL_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bapi[_-]?key\b\s*[:=]",
        r"\bpassword\b\s*[:=]",
        r"\bpasswd\b\s*[:=]",
        r"\bsecret\b\s*[:=]",
        r"\btoken\b\s*[:=]",
        r"\bauthorization\b\s*:",
        r"\bclient[_-]?secret\b\s*[:=]",
        r"\bprivate[_-]?key\b\s*[:=]",
    )
)

WITHHELD_NOTICE = (
    "AEO compliance report withheld: the generated report did not clear the "
    "output check and was not released. No partial content is included."
)


def contains_credential(text: object) -> bool:
    """True when ``text`` carries a credential by EITHER detector.

    The union is the contract: a value the framework catches and this template
    misses would be raised on by the framework inside this node, and the wrapper
    would then return a bare error partial — discarding the clearing below. A
    detector gap is not a smaller gate, it is a containment bypass.
    """
    if bool(detect_credentials_in_value(text)):
        return True
    if not isinstance(text, str):
        return False
    return any(pattern.search(text) for pattern in _LOCAL_CREDENTIAL_PATTERNS)


class PostProcessNode(FunctionNode):
    """Release the compliance report to the caller, or withhold it entirely.

    The envelope the framework returns is `formatted_output or result`, so
    `result` is a live caller-facing channel in its own right: a boundary that
    only rewrote `formatted_output`, or that raised instead of writing one, would
    still ship the un-gated inner report. On a violation this node therefore
    clears BOTH fields and replaces them with a notice that is deliberately
    non-empty, because a falsy `formatted_output` re-opens the fallback rather
    than closing it.

    Inner backbone node — ANONYMOUS; the external gate is PreProcessNode.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Scan the merged result and either release it or withhold it."""
        result = state.get("result", "")
        correlation_id = state.get("correlation_id", "")

        if contains_credential(result):
            emit_trace_event(
                "post_process_output_withheld",
                {"reason": "credential_pattern", "correlation_id": correlation_id},
                state,
            )
            return {
                "formatted_output": WITHHELD_NOTICE,
                "result": WITHHELD_NOTICE,
                "compliance_report": "",
                "report_metrics": {},
                "status": AgentStatus.ERROR,
                "error_log": ["PostProcessNode: output withheld — credential pattern"],
            }

        emit_trace_event(
            "post_process_formatted",
            {
                "output_length": len(result) if isinstance(result, str) else 0,
                "correlation_id": correlation_id,
            },
            state,
        )

        return {
            "formatted_output": result,
            "status": AgentStatus.SUCCESS,
        }
