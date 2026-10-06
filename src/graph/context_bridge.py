"""AgentCore Platform v1.0 — RET-C2-196 request-context bridge"""

# Carries the caller's request context across the outer→inner graph boundary.
#
# The framework's GraphNode invokes its subgraph as
# `subgraph.invoke(user_input, session_id=…, ctx=…)` — there is no
# `input_context` argument in that call, while `BaseGraph.invoke` accepts one and
# seeds it into the initial state. The consequence is measurable and silent: the
# outer graph receives the caller's context, the inner graph receives `{}`, and
# every inner node reading `state["input_context"]` sees an empty mapping with
# nothing failing anywhere.
#
# A ContextVar rather than an attribute on the node, for two reasons: the
# subgraph is constructed fresh inside `get_subgraph()` on every call, so there
# is no shared object to hang it on; and a ContextVar is per-task, so two
# concurrent requests in the same process cannot see each other's data — which an
# attribute on the node instance could not guarantee.
#
# Lifecycle: the outer node publishes in `extract_input()`, the one hook the
# framework calls with the outer state before the subgraph runs; the inner graph
# reads it in `_extra_initial_state()`, the hook `BaseGraph.invoke` applies to the
# initial state. Every subgraph invocation is preceded by exactly one
# `extract_input()`, so each run overwrites the previous value and a stale read is
# not reachable. Nothing else in the template touches this module.

from contextvars import ContextVar
from typing import Any

_REQUEST_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("ret_c2_196_request_context", default={})


def stash(context: dict[str, Any] | None) -> None:
    """Publish the caller's request context for the inner graph.

    Copied rather than stored by reference, so an inner node cannot mutate the
    outer graph's state through it.
    """
    _REQUEST_CONTEXT.set(dict(context) if context else {})


def peek() -> dict[str, Any]:
    """Return a copy of the request context published for this task, or ``{}``."""
    return dict(_REQUEST_CONTEXT.get())
