"""Shared request fixtures for the integration tests.

`BASE_REQUEST` is also the content of `deploy/invoke_payload.json`, and
`test_invoke_contract.py` asserts the two are equal. The deploy payload is
POSTed verbatim during the staging smoke check, so taking it from the same
object the tests assert against is what stops the two drifting into a state
where the suite is green and the deployed agent refuses the request it is sent.
"""

from typing import Any

# A rich listing: every dimension satisfiable, so it scores near the top.
RICH_PRODUCT: dict[str, Any] = {
    "sku_id": "4901234567894",
    "title": "Wireless Noise Cancelling Headphones Over Ear Black",
    "description": (
        "Over-ear wireless headphones with active noise cancellation, a thirty hour "
        "battery, multipoint pairing and a foldable travel case. Supports high "
        "resolution audio codecs and a low latency mode for gaming on console and "
        "desktop, with a detachable cable for wired listening when the battery runs "
        "flat during long journeys away from a charger."
    ),
    "category": "Electronics > Audio > Headphones",
    "brand": "Acme",
    "price": "24800",
    "attributes": {"color": "black", "weight": "250g", "connectivity": "bluetooth"},
    "image_url": "https://example.invalid/img/4901234567894.jpg",
}

# A sparse listing: short title, thin description, no category, brand or image.
SPARSE_PRODUCT: dict[str, Any] = {
    "sku_id": "SKU-1002",
    "title": "CHAIR",
    "description": "A chair.",
    "category": "unknown",
}

BASE_REQUEST: dict[str, Any] = {
    "input": "AEO compliance check for the attached product listings.",
    "session_id": "aeo-compliance-demo-001",
    "input_context": {
        "channel": "web",
        "merchant_id": "demo_merchant",
        "products": [RICH_PRODUCT, SPARSE_PRODUCT],
    },
}
