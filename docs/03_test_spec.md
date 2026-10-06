# Test Specification — RET-C2-196

## Agent: ECProductAEOComplianceCheckAgent

### Test Strategy

- **Coverage target**: 90%+ (unit + boundary)
- **Test types**: Unit (per-node `execute()` and the shared guard), Integration (the real ASGI app), Proof-of-Boundary (backbone + import isolation + state safety)
- **Framework compliance**: mandatory TC-01–TC-11 per SDK-v1 conventions
- **Execution environment**: the real SDK wheel, at the version the shared pipeline installs

### Why the integration layer exists

Node-level tests cannot see whether a caller can reach the agent at all. This template's entry point once left every request at `ANONYMOUS` while its own entry node required `VERIFIED_EXTERNAL`, so every call returned `status: error` with a null output while the unit suite stayed entirely green. Everything under `tests/integration/` therefore goes through `POST /invoke` on the app the deployment serves, at the declared trust level.

The committed `deploy/invoke_payload.json` is generated from `tests/integration/fixtures.py::BASE_REQUEST`, and the suite asserts both that the two are equal and that the committed payload succeeds. The staging smoke check posts that file verbatim, so a payload invented separately from the tests can refuse while the suite is green — with the only record a line in a job artifact.

---

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result |
|-------|------|----------------|
| TC-01 | State contract: `src/schemas/state.py` is a flat TypedDict (no Pydantic, no dataclass) | Type check pass |
| TC-02 | `PreProcessNode`: empty input returns `AgentStatus.ERROR` with non-empty `error_log` | ERROR + log entry |
| TC-03 | No JWT/credential in State fields | CI `gate-credential-scan`: 0 violations |
| TC-04 | No `agenticstar` / Level-0 imports anywhere in `src/` | AST scan: 0 violations |
| TC-05 | S-4: no `node_start` / `node_complete` / `node_error` emitted in any `execute()` body | 0 duplicate lifecycle events |
| TC-06 | S-2: `_security_gate_input()` is NOT overridden on any FunctionNode subclass (it is `@final`) | `TypeError` would fire at class definition — verify none present |
| TC-07 | S-3: `_security_gate_output()` is NOT overridden on any FunctionNode subclass (it is `@final`) | `TypeError` would fire at class definition — verify none present |
| TC-08 | `required_trust_level` enforced: caller below threshold → refused (S-1) | `SecurityViolationError` or `AgentStatus.ERROR` |
| TC-09 | S-2 domain check (inline in `PreProcessNode.execute()`): input past the size bound is refused | ERROR, `error_log` present, no `validated_input` carried forward |
| TC-10 | S-3 domain checks: `enforce_output_invariant()` withholds a report whose rendered figures disagree; `contains_credential()` withholds on either detector | ERROR, every output-bearing field cleared, replacement truthy |
| TC-11 | S-4: `emit_trace_event()` called positionally in every `execute()` path | Domain event emitted per node on every invocation |

---

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result |
|-------|----------|------|----------------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures |
| PB-2 | State serialization | Post-invoke State is primitives only (list/dict/str/int) | No Pydantic/dataclass objects |
| PB-3 | Import isolation | No Level-0 (`agenticstar`) imports | AST scan: 0 violations |
| PB-4 | Checkpoint safety | No JWT/Pydantic in state | Inspection pass |
| PB-5 | Inner graph trust path | Caller `VERIFIED_EXTERNAL` → inner ANONYMOUS nodes admit → SUCCESS | `AgentStatus.SUCCESS` |
| PB-6 | Backbone invoke order | `ECProductAEOComplianceCheckAgent().invoke()` with `VERIFIED_EXTERNAL` caller → `node_history` = `[InitializeNode, PreProcessNode, AEOComplianceWorkflowGraphNode, PostProcessNode, FinalizeNode]` | Order verified |

**PB-6 valid payload example:**
```
title=Wireless Bluetooth Headphones Premium Noise Cancelling
description=High-quality wireless headphones with 30-hour battery life and advanced noise cancellation technology for commuters and remote workers.
category=Electronics
brand=AudioTech Pro
price=12800
image_url=https://cdn.example.com/products/headphones-001.jpg
```

---

## Domain Business Logic Tests

### ProductDataInputNode

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-01 | JSON array input | `[{"sku_id": "SKU-001", "title": "Widget", "description": "A widget", "category": "Tools"}]` | `product_data` = list with 1 item, `sku_id` = "SKU-001" |
| BL-02 | Line key=value input | `title=Widget Pro\ndescription=A widget for professionals\ncategory=Tools` | `product_data` = list with 1 item, `title` = "Widget Pro" |
| BL-03 | Empty input returns ERROR | `validated_input = ""` | `status = AgentStatus.ERROR` |
| BL-04 | Fallback to single SKU wrapper | `validated_input = "Just a product description"` | `product_data` = list with 1 item |

### AEOScoreCalculateNode

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-05 | High-quality product scores ≥ 70 | Full product with title(30+ chars), description(60+ words), category, brand, price, image | `score >= 70`, `compliant = True` |
| BL-06 | Minimal product scores < 70 | SKU with short title only | `score < 70`, `compliant = False` |
| BL-07 | Empty product_data returns ERROR | `product_data = []` | `status = AgentStatus.ERROR` |
| BL-08 | Score breakdown sums to total | Any valid SKU | `sum(breakdown.values()) == score` |

### GapIdentifyNode

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-09 | Non-compliant SKU generates gaps | SKU with score < 70 | `compliance_gaps` non-empty, each has `sku_id/gap_type/severity/description` |
| BL-10 | Compliant SKU can still have partial gaps | SKU with score >= 70 but some dims below max | Gaps may exist but LOW severity |
| BL-11 | Empty aeo_scores returns ERROR | `aeo_scores = {}` | `status = AgentStatus.ERROR` |
| BL-12 | Gap severity matches dimension priority | `title_quality` gap | `severity = "HIGH"` |

### RemediationPrioritizeNode

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-13 | HIGH severity gaps → Priority 1 | Gap with `severity="HIGH"` | `priority = 1`, `priority_label = "HIGH"` |
| BL-14 | Sorted by priority then score_lost | Mixed severity gaps | Priority 1 items appear before Priority 2 |
| BL-15 | Action text populated for all gap types | Gap with any known gap_type | `action` is non-empty string |
| BL-16 | None compliance_gaps returns ERROR | `compliance_gaps = None` | `status = AgentStatus.ERROR` |

### ComplianceReportGenerateNode

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-17 | Report contains executive summary | Valid aeo_scores | `compliance_report` contains "Executive Summary" |
| BL-18 | Report contains per-SKU scorecard | Valid aeo_scores with 1 SKU | `compliance_report` contains SKU ID |
| BL-19 | Output invariant withholds a report whose figures disagree | aeo_scores rendering a score outside 0–100, or a flag disagreeing with its score | ERROR, report replaced whole, `report_metrics = {}` |
| BL-20 | Empty aeo_scores returns ERROR | `aeo_scores = {}` | `status = AgentStatus.ERROR` |
| BL-21 | All-compliant fleet: no remediation section items | All SKUs score >= 70, remediation_priorities = [] | Report contains "No remediation items" |

### End-to-End (through the real ASGI `/invoke`)

`tests/integration/test_invoke_contract.py`. Every row drives the app the deployment serves, with a bearer credential, at the declared trust level.

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| E2E-01 | The deployed agent serves a real report | The fixture request | `status == "success"`, `output` carries the report and a scorecard row per SKU |
| E2E-02 | No credential is refused | The fixture request, no `Authorization` header | `401`, and a wrong token's value is not echoed |
| E2E-03 | The committed deploy payload equals the fixture, and succeeds | `deploy/invoke_payload.json` | equal to `BASE_REQUEST`; `status == "success"` |
| E2E-04 | Score moves with listing quality | A complete listing vs a bare one | complete ≥ threshold, bare < threshold, complete > bare |
| E2E-05 | Both compliance outcomes are reachable | The fixture's two SKUs | report contains both `[PASS]` and `[FAIL]` |
| E2E-06 | The request context reaches the inner graph | Structured `products`, no listing in the free-text field | the structured SKU is scored |
| E2E-07 | Unsupported context keys are dropped | A key this version does not declare | `status == "success"` |
| E2E-08 | Injection is refused, nothing published | Control tokens, directives, a markup-split directive | `status == "error"`, `output` falsy |
| E2E-09 | Ordinary retail listings are not refused | EAN-13, GTIN-14, UPC-A, marketing imperatives, model numbers | `status == "success"`, report non-empty |
| E2E-10 | Non-finite numbers are refused, not absorbed | `NaN`, `Infinity`, `-Infinity`, over-magnitude, non-numeric on `price` | `400` naming the field |
| E2E-11 | A credential shape in the context is refused readably | `Bearer …` in a product description | `400` naming `products[0]`, value never echoed |
| E2E-12 | A forged SKU id cannot manufacture report structure | `sku_id` carrying newlines and pipes | `400` naming `sku_id` |
| E2E-13 | Structural caps hold | Oversized body; more product records than the cap | `400` |
| E2E-14 | Wrong field types are refused cleanly | `description` as int, `title` as list, `attributes` as int, `sku_id` as dict | `400` naming the field |
| E2E-15 | A redacted title is not reported as a short title | The same listing via free text and via the context | report says "Not evaluated", never renders the sentinel; via context the dimension scores full marks |

---

## Test Execution Summary

- Tests location: `tests/unit/`, `tests/integration/`, `tests/proof_of_boundary/`
- Execution command: `python -m pytest tests/ -v`
- Expected: all PASS against the real SDK wheel. The two `tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py` cases skip by design: this template does not enable human-in-the-loop, so there is no cross-boundary interrupt to propagate.
