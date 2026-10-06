"""AgentCore Platform v1.0 — RET-C2-196 ProductDataInputNode"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict (partial-dict return)
#  - required_trust_level: ANONYMOUS (inner domain node)
#  - Audit: emit_trace_event called positionally in execute()
#  - No ctor args — SDK-v1 nodes instantiated with ProductDataInputNode()

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.input_guard import (
    MASK_SENTINEL,
    MAX_ATTRIBUTES,
    MAX_PRODUCTS,
    MAX_TEXT_FIELD,
    coerce_identifier,
    finite_in_range,
)

_TEXT_FIELDS = ("title", "description", "category", "brand")

# Field names a merchant feed commonly uses instead of the canonical one.
_ALIASES = {"title": "name", "description": "desc", "category": "cat"}


def _security_gate_output(result: dict[str, Any]) -> dict[str, Any]:
    """Module-level output gate: never carry a credential-shaped value forward.

    Called explicitly from execute() — the domain output-gate helper pattern,
    not an override of the @final FunctionNode method.
    """
    from framework.security.credential_detector import detect_credentials_in_value

    for item in result.get("product_data", []):
        for key, value in list(item.items()):
            if isinstance(value, str) and detect_credentials_in_value(value):
                item[key] = "[REDACTED]"
    return result


class ProductDataInputNode(FunctionNode):
    """Assemble the SKU records the rest of the pipeline scores.

    Two input routes, in order of preference:

    1. **Structured records on the request context** (`input_context["products"]`).
       Already validated field by field against explicit bounds before the graph
       ran. This is the route a merchant integration should use, and it is the
       only one where product text reaches this node exactly as the caller sent
       it — see the note on redaction below.

    2. **Free text on `user_input`**, parsed as a JSON document or as
       newline-separated `key=value` blocks. Kept so a request carrying no
       structured records still produces a real report rather than nothing.

    On redaction: the platform's input filter masks personal-data shapes in
    `user_input` *before any template code runs*, and it reads a title-case
    product title as a person's name. "Wireless Noise Cancelling Headphones Over
    Ear" arrives here as the literal string "[MASKED]". Scoring that as if it
    were the merchant's title produces a confident, wrong finding about a listing
    that is in fact fine, so a masked field is recorded in `redacted_fields` and
    excluded from scoring instead. The request context is not filtered that way,
    which is the concrete reason route 1 exists.

    Output state fields:
        product_data: list[dict] — normalised SKU records
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Build product_data from the request context, or from validated_input."""
        correlation_id = state.get("correlation_id", "")
        context = state.get("input_context", {}) or {}
        records = context.get("products") if isinstance(context, dict) else None

        if records:
            product_data = [self._normalize(r, i, "context") for i, r in enumerate(records)]
            source = "context"
        else:
            validated_input = state.get("validated_input", state.get("user_input", ""))
            if not isinstance(validated_input, str) or not validated_input.strip():
                emit_trace_event(
                    "product_data_input_empty",
                    {"reason": "no_products_and_no_text", "correlation_id": correlation_id},
                    state,
                )
                return {
                    "status": AgentStatus.ERROR,
                    "error_log": ["ProductDataInputNode: no product records and no product text"],
                }
            product_data = self._parse_product_data(validated_input)
            source = "user_input"

        result = {"product_data": product_data, "status": AgentStatus.SUCCESS}
        result = _security_gate_output(result)

        redacted = sum(1 for s in product_data if s.get("redacted_fields"))
        emit_trace_event(
            "product_data_input_parsed",
            {
                "sku_count": len(product_data),
                "source": source,
                "redacted_field_skus": redacted,
                "correlation_id": correlation_id,
            },
            state,
        )
        return result

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalize(self, raw: Any, index: int, source: str) -> dict[str, Any]:
        """Normalise one record into the shape the scoring node expects.

        Every field is coerced to its declared type rather than trusted: a
        caller-supplied ``description`` of ``12345`` used to reach ``.split()``
        and raise, which surfaced to the caller as an opaque failure with a
        traceback in the audit trail.
        """
        if not isinstance(raw, dict):
            raw = {}

        redacted: list[str] = []
        record: dict[str, Any] = {
            "sku_id": coerce_identifier(raw.get("sku_id", raw.get("id", "")), f"SKU-{index + 1:03d}"),
            "source": source,
        }

        for field in _TEXT_FIELDS:
            value = raw.get(field, raw.get(_ALIASES.get(field, field), ""))
            text = value if isinstance(value, str) else ("" if value is None else str(value))
            text = text[:MAX_TEXT_FIELD]
            if MASK_SENTINEL in text:
                redacted.append(field)
            record[field] = text

        price = raw.get("price", "")
        record["price"] = "" if finite_in_range(price, 0.0, 1e12) is None else str(price)

        attributes = raw.get("attributes", raw.get("attrs", {}))
        if isinstance(attributes, dict):
            record["attributes"] = {str(k): str(v) for k, v in list(attributes.items())[:MAX_ATTRIBUTES]}
        else:
            record["attributes"] = {}

        image_url = raw.get("image_url", raw.get("image", ""))
        record["image_url"] = image_url if isinstance(image_url, str) else ""

        record["redacted_fields"] = redacted
        return record

    # ── Free-text parsing ─────────────────────────────────────────────────────

    def _parse_product_data(self, raw_input: str) -> list[dict[str, Any]]:
        """Parse free-text product listing data into normalised SKU records.

        Supports a JSON document (object or array) and newline-separated
        ``key=value`` / ``key: value`` blocks. Capped at MAX_PRODUCTS records:
        without a cap a 50,000-character request expands into a report of many
        megabytes, because every record contributes a scorecard and up to five
        remediation entries.
        """
        stripped = raw_input.strip()
        if stripped[:1] in ("[", "{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [self._normalize(item, i, "user_input") for i, item in enumerate(parsed[:MAX_PRODUCTS])]
            if isinstance(parsed, dict):
                return [self._normalize(parsed, 0, "user_input")]

        blocks: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in raw_input.splitlines():
            if len(blocks) >= MAX_PRODUCTS:
                break
            line = line.strip()
            if not line:
                if current:
                    blocks.append(current)
                    current = {}
                continue
            if "=" in line:
                key, _, value = line.partition("=")
            elif ":" in line:
                key, _, value = line.partition(":")
            else:
                current.setdefault("title", line)
                continue
            current[key.strip().lower()] = value.strip()
        if current and len(blocks) < MAX_PRODUCTS:
            blocks.append(current)

        if not blocks:
            # Nothing parsed as structured data: treat the whole request as one
            # listing so the caller still gets a real scorecard rather than an
            # error about a format they were never told about.
            blocks = [{"title": raw_input[:200], "description": raw_input, "category": "unknown"}]

        return [self._normalize(b, i, "user_input") for i, b in enumerate(blocks)]
