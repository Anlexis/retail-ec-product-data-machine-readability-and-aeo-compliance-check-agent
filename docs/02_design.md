# Design Specification — RET-C2-196

## Agent: ECProductAEOComplianceCheckAgent

### Position in AgentCore Architecture

- **Template ID**: RET-C2-196
- **L1 Base**: AgentBaseGraph (Cat 2 nested — outer AgentBaseGraph + GraphNode main slot wrapping inner BaseGraph)
- **Category**: Cat 2
- **Industry**: RET (Retail)
- **Pattern**: ChatAgent (compliance check pipeline)

### Three-Layer Separation

- **State**: `src/schemas/state.py` — flat TypedDict extending AgentState; no Pydantic, no credentials, no InvocationContext
- **Nodes**: L1 FunctionNode inheritance; `execute(self, state: dict) -> dict` override; partial-dict return (only changed keys)
- **Graph**: `src/graph/graph.py` (outer `AgentBaseGraph`) + `src/graph/domain_workflow_graph.py` (inner `BaseGraph`); node substitution via `register_nodes()`

---

## Architecture Overview

### Use Case

EC platform merchants (Rakuten / Yahoo Shopping / Amazon Japan) need to audit product data structure for AI shopping agent parseability. The agent validates product listings against machine-readability standards and AEO (Answer Engine Optimization) criteria, producing per-SKU compliance scores and a prioritized remediation plan.

**Input**: structured product records on the request context (`input_context.products`), or a free-text product listing in the request body. The structured route is the intended one and is validated field by field; the free-text route is parsed as JSON or as `key=value` blocks and exists so a caller with no structured feed still gets a real report.

**Output**: Compliance report per SKU — AEO score (0–100), the gaps behind it, and a prioritised remediation roadmap with an effort estimate per item.

### Output invariant

The monetary precision grid that applies to templates rendering currency amounts is **not applicable here**: this report renders no monetary values. Prices are read as a completeness signal for the attribute dimension and are never printed.

The equivalent guarantee for this agent is its **scoring invariant**, and `ComplianceReportGenerateNode` enforces it on the rendered report before release:

- every SKU score printed is a whole number in 0–100;
- every dimension score is within that dimension's declared weight, and the weight printed is the declared one;
- the `PASS` / `FAIL` flag agrees with the score against the threshold;
- the summary counts equal the scorecard rows beneath them, and the fleet average lies within the range of the rendered scores;
- every rendered SKU identifier is inert.

The check reads the **rendered text back**, not the figures that produced it, so a formatting defect is caught as well as an arithmetic one. A violation withholds the whole report rather than trimming it: the document's value is that its numbers can be acted on, so a partial release is worse than none.

### Caller-input contract

All bounds live in `src/services/input_guard.py`, applied by both the HTTP adapter and `PreProcessNode`. The node is the authority — the adapter is out of the path when the platform gateway calls the agent directly.

- `sku_id` is the only caller string the report renders, and is locked to `[A-Za-z0-9._-]{1,64}`. Nothing in that alphabet can open a Markdown construct.
- Every caller number goes through a finite + bounded parser: `NaN` and `±Infinity` parse through `float()` and compare False against everything, so an unchecked one answers "no" silently rather than raising.
- Injection screening covers chat-template control tokens (`<|…|>`, `[INST]`, `<<SYS>>`, `<s>`, `<system>`) as a class, raw, Unicode-normalised and markup-stripped, over parsed keys as well as values.
- Personal-data screening is deliberately narrow on digit runs. A product feed is full of them — EAN-13, GTIN-14, UPC-A, model numbers, dimension lists — so card detection requires either a conventionally grouped form or a run of 15, 16 or 19 digits passing both a Luhn check and a major issuer prefix, and phone detection requires a separator-bearing shape.
- Unsupported request-context keys are **dropped** before the graph runs. An ignored key still travels on the context channel, where the framework's first node returns it verbatim in its own result and the framework's output scan reads it.

### Platform redaction

The platform's input filter masks personal-data shapes in the free-text request field before any template code runs, and it reads a title-case product title as a person's name. A field arriving as the redaction sentinel is recorded in `redacted_fields`, excluded from that SKU's score, and named in the report as not evaluated; the score is normalised over the dimensions that could be assessed. Scoring the sentinel instead would produce a confident finding about a field the agent never saw. The structured `products` route is not filtered this way.

### Outer Graph Pipeline (Backbone — fixed)

```
START → initialize → pre_process → main (GraphNode) → post_process → finalize → END
                                        ↓ (RETRY, max 3)
                                     pre_process
```

### Inner Graph Pipeline (Domain Workflow)

```
START → product_data_input → aeo_score_calculate → gap_identify → remediation_prioritize → compliance_report_generate → END
```

### Node Configuration

| Layer | Node | Class | Trust Level | Responsibility |
|-------|------|-------|-------------|----------------|
| Outer backbone | initialize | InitializeNode (default) | — | Session init, schema version |
| Outer backbone | pre_process | PreProcessNode | `VERIFIED_EXTERNAL` | S-1 input gate, validate product data request |
| Outer backbone | main | AEOComplianceWorkflowGraphNode (GraphNode) | — | Delegates to inner DomainWorkflowGraph |
| Outer backbone | post_process | PostProcessNode | `ANONYMOUS` | Format compliance report for response |
| Outer backbone | finalize | FinalizeNode (default) | — | Response metadata, timing |
| Inner domain | product_data_input | ProductDataInputNode | `ANONYMOUS` | Parse SKU list from validated input |
| Inner domain | aeo_score_calculate | AEOScoreCalculateNode | `ANONYMOUS` | Compute AEO score (0–100) per SKU |
| Inner domain | gap_identify | GapIdentifyNode | `ANONYMOUS` | Identify compliance gaps (score < threshold) |
| Inner domain | remediation_prioritize | RemediationPrioritizeNode | `ANONYMOUS` | Prioritize gaps by revenue impact |
| Inner domain | compliance_report_generate | ComplianceReportGenerateNode | `ANONYMOUS` | Generate structured Markdown compliance report |

### Data Flow

```
user_input (product data description / SKU list)
    │
    ▼ pre_process (VERIFIED_EXTERNAL gate)
validated_input, enriched_context
    │
    ▼ AEOComplianceWorkflowGraphNode → inner graph
        │
        ▼ ProductDataInputNode
        product_data: list[{sku_id, title, description, category, attributes}]
        │
        ▼ AEOScoreCalculateNode
        aeo_scores: {sku_id: {score, breakdown}}
        │
        ▼ GapIdentifyNode
        compliance_gaps: [{sku_id, gap_type, field, severity, description}]
        │
        ▼ RemediationPrioritizeNode
        remediation_priorities: [{sku_id, priority, action, estimated_impact, effort}]
        │
        ▼ ComplianceReportGenerateNode
        compliance_report: str (Markdown)
    │ ← inner get_output() → merge_output()
result: str
    │
    ▼ post_process
formatted_output: str
    │
    ▼ finalize → response to caller
```

### State Definition

| Field | Type | Set by | Purpose |
|-------|------|--------|---------|
| `validated_input` | `str` | pre_process | Screened user input |
| `input_context` | `dict` | pre_process | The request context reduced to the supported, screened subset |
| `enriched_context` | `dict` | pre_process | Channel, source metadata |
| `product_data` | `list` | ProductDataInputNode | Normalised SKU records, each carrying `redacted_fields` |
| `aeo_scores` | `dict` | AEOScoreCalculateNode | Per-SKU AEO readability scores |
| `compliance_gaps` | `list` | GapIdentifyNode | Identified compliance gaps |
| `remediation_priorities` | `list` | RemediationPrioritizeNode | Prioritized remediation items |
| `compliance_report` | `str` | ComplianceReportGenerateNode | Formatted compliance report |
| `report_metrics` | `dict` | ComplianceReportGenerateNode | The figures the report renders, so the boundary checks the rendering against the computation rather than re-deriving it |
| `result` | `str` | AEOComplianceWorkflowGraphNode (merge_output) | Inner graph output mapped to outer state |
| `formatted_output` | `str` | post_process | Final formatted response |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types; no Pydantic, no dataclass)
- No JWT, API keys, or credentials in State (checkpoint DB leakage risk)
- InvocationContext via `config["configurable"]` only (not in State)

---

## Framework Utilization

### Shared Components

- [x] S-1 Trust gate: `required_trust_level = TrustLevel.VERIFIED_EXTERNAL` on `PreProcessNode` (backbone external gate); inner domain nodes use `ANONYMOUS`
- [x] S-2 Input gate: FunctionNode's `@final _security_gate_input()` runs automatically; the domain checks (bounds, injection, personal data, request-context contract) are applied **inline in `PreProcessNode.execute()`**, not through the `_extra_security_gate_input()` hook — the framework auto-wraps that hook in a way that does not survive a None state
- [x] S-3 Output gate: FunctionNode's `@final _security_gate_output()` runs automatically; the domain output checks are module-level helpers called explicitly from `execute()` — `enforce_output_invariant()` in ComplianceReportGenerateNode for the scoring invariant, and `contains_credential()` in PostProcessNode for credential containment at the backbone boundary
- [x] S-4 Audit: `emit_trace_event()` called positionally in every `execute()` — domain-specific events only (not `node_start` / `node_complete` / `node_error`, which BaseNode.__call__() emits automatically)
- [x] S-5 Credential scan: framework's built-in `@final _security_gate_output()` credential scan on all FunctionNode outputs; no secrets stored in State

### Security Gate Placement

| Gate | Node | Implementation |
|------|------|----------------|
| S-1 Trust | PreProcessNode | `required_trust_level = VERIFIED_EXTERNAL`; the HTTP adapter establishes it from a bearer credential, so a request reaches the pipeline at all |
| S-2 Input | PreProcessNode | inline in `execute()`, rules from `src/services/input_guard.py` |
| S-3 Output (invariant) | ComplianceReportGenerateNode | `enforce_output_invariant()` on the rendered report |
| S-3 Output (containment) | PostProcessNode | `contains_credential()` — the union of the framework's detector and this template's own patterns; on a hit, every output-bearing field is cleared and replaced with a truthy notice |
| S-4 Audit | Every node | `emit_trace_event(event, payload, state)` positional in execute() |
| S-5 Credential | All FunctionNode subclasses | Framework built-in `@final _security_gate_output()` |

**Why two output layers, and why not three.** The report node owns the scoring invariant; the backbone boundary owns credential containment. They are given different jobs so that disabling either is observable in the tests. A third guard blanking the output in `get_output()` was deliberately *not* added: it would contain a leak on its own and thereby make both layers below unfalsifiable.

**Why the union, not the framework detector alone.** The framework's patterns describe credential *formats* — `AKIA…`, `sk_live_…`, `sk-…`, JWT, database URI, `Bearer <token>` — and match none of the labelled-assignment shapes (`password=…`, `api_key: …`) the local set catches. Delegating wholly to the framework would have made this gate narrower while looking like a tightening. Conversely a local-only set misses all six framework classes, and a value the framework catches and the template misses makes the framework raise *inside* the node, so the wrapper returns a bare error partial and discards the clearing. Wider is safe; narrower is a bypass.

### Composition Pattern

- **Pattern**: Cat 2 — GraphNode (outer `AgentBaseGraph` + `GraphNode` in main slot → inner `BaseGraph`)
- **Inner graph**: `src/graph/domain_workflow_graph.py` (`DomainWorkflowGraph(BaseGraph)`)
- **Error propagation**: `error_strategy = "propagate"` (re-raise inner graph exceptions as SubgraphError)
- **HITL**: `propagate_hitl = False` (HITL stays inside inner graph)
- **Request context across the boundary**: `GraphNode.execute()` invokes its subgraph as `subgraph.invoke(user_input, session_id, ctx)` — with no `input_context` argument, while `BaseGraph.invoke` accepts one and seeds it into the initial state. The inner graph therefore receives `{}` unless something carries it. `src/graph/context_bridge.py` is that carrier: the outer node publishes in `extract_input()`, the inner graph seeds in `_extra_initial_state()`. A ContextVar rather than an attribute, because the subgraph is constructed fresh on every call and a ContextVar is per-task, so concurrent requests cannot see each other's data.

### Runtime configuration

`config/agent.yaml` is the manifest and carries identity and the compile-time requirements only. Runtime values live in `config/config.yaml` and are read through the single reader `src/services/runtime_config.py`; the entry point constructs the graph with them. Constructing the graph without them would leave every declared value unread while the framework substitutes its own defaults.

`max_retry` has a live reader in the framework backbone (it bounds the pre_process retry route). `timeout_s` does not: nothing in the framework or in this template enforces it, so it is a declared budget for the hosting runtime rather than a limit.

---

## Import Isolation Confirmation

- [x] Template does not import agenticstar-platform SDK (Level 0 — prohibited)
- [x] Import targets: `framework.*` and `shared.*` only
- [x] No imports from `agents/base/` (L2 retired pattern)
- [x] `src.*` imports within template only (no cross-agent imports)

---

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Fixed 5-step compliance workflow; no autonomous reasoning loop required |
| Inner graph parent | BaseGraph (custom topology) | AgentBaseGraph (standard backbone) | BaseGraph | Domain nodes follow a fully custom linear sequence — no sub-backbone needed |
| S-1 gate node | PreProcessNode | Inner domain node | PreProcessNode (outer backbone) | Outer backbone is the external-facing gate; inner nodes are ANONYMOUS per review finding 5 ruling |
| Report format | JSON | Markdown | Markdown | Human-readable priority list; easier for EC merchants to act on |
| AEO score basis | Keyword matching | Field completeness + structured attributes | Field completeness + structured attributes | More actionable and deterministic without external ML dependency |
