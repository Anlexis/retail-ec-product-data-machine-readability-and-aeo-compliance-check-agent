# E-Commerce Product Data AEO Check Agent

AI agent for scoring e-commerce product data for AI shopping agent readability, built with Agentic Star.

> **Category**: Cat 2 (a multi-step pipeline for one specific job)
> **Industry**: Retail
> **Template ID**: RET-C2-196

## Overview

Scores e-commerce product listings on how well an AI shopping agent can read them, and returns a
prioritised list of what to fix.

Each SKU is scored 0–100 across five dimensions — title quality, description depth, category
precision, attribute completeness and image availability. Anything below the threshold is broken
down into the specific listing fields responsible, ranked by how much score each one would recover
and how much work it is, and written up as a Markdown compliance report with a per-SKU scorecard
and a remediation roadmap.

The pipeline is deterministic: no model is called, so the same listing always produces the same
score, and the report can be diffed run over run to show whether a catalogue is improving.

Listings can be submitted two ways. Structured records on the request context are the intended
route and are validated field by field. Free text in the request body is also accepted and parsed,
for callers who have no structured feed to hand.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

The scoring weights, the compliance threshold and the remediation advice are all judgement calls
about one retailer's catalogue. Treat them as a worked example to re-tune, not as a standard.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback and no degraded
mode: the graph fails to compile and the process does not start serving. This is intentional — a
half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

### Calling it

`POST /invoke` takes the request body below. When `INVOKE_AUTH_TOKEN` is set in the server
environment, callers present it as `Authorization: Bearer <token>`; a request that no upstream
middleware has already vouched for and that carries no valid token is refused with `401`.

```json
{
  "input": "AEO compliance check for the attached product listings.",
  "input_context": {
    "channel": "web",
    "merchant_id": "demo_merchant",
    "products": [
      {
        "sku_id": "4901234567894",
        "title": "Wireless Noise Cancelling Headphones Over Ear Black",
        "description": "Over-ear wireless headphones with active noise cancellation …",
        "category": "Electronics > Audio > Headphones",
        "brand": "Acme",
        "price": "24800",
        "attributes": {"color": "black", "weight": "250g"},
        "image_url": "https://example.invalid/img/4901234567894.jpg"
      }
    ]
  }
}
```

`sku_id` is the only caller value the report renders, so it is restricted to
`[A-Za-z0-9._-]{1,64}` — barcodes, internal SKUs and variant suffixes all fit, and nothing in
that set can open a Markdown construct. Every other field is bounded by length, type and range;
a rejected request names the field and the reason and never echoes the value.

`input_context` keys this version does not know about are dropped before the graph runs rather
than passed through.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and operational documentation
```

`config/agent.yaml` is the manifest — identity, entry point and the compile-time requirements.
`config/config.yaml` holds the runtime values, read through `src/services/runtime_config.py`.

See `docs/` for the design notes and the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Re-tune the scoring weights and the compliance threshold in
   `src/nodes/aeo_score_calculate_node.py` — they are one retailer's judgement, not a standard.
3. Rewrite the remediation advice in `src/nodes/remediation_prioritize_node.py` for your
   catalogue and your team's effort estimates.
4. Re-run the test suite.

### A note on redaction

The platform filters personal data out of the free-text request field before any template code
runs, and it reads a title-case product title as a person's name — so
`"Wireless Noise Cancelling Headphones Over Ear"` can arrive as the literal string `[MASKED]`.

Scoring that would award zero for title quality and tell the merchant to rewrite a title that is
already correct. Instead, a field that arrives redacted is excluded from that SKU's score, named
in the report as not evaluated, and the score is normalised over the dimensions that could be
assessed. The structured `products` route is not filtered this way, which is the practical reason
to prefer it.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
