"""The output boundary: what this agent promises about its report, enforced.

Two layers, deliberately given different jobs so neither can mask the other:

  - the report node owns the SCORING invariant — every figure it prints is a
    whole number out of 100, dimension scores stay within their weights, the
    PASS/FAIL flag agrees with the score, and the summary counts match the rows;
  - the backbone boundary owns CREDENTIAL containment, against the union of the
    framework's detector and this template's own patterns.

No third guard blanks the output in `get_output`. It would contain a leak on its
own and thereby make both layers below unfalsifiable — more defence buying less
assurance.

There is no monetary precision grid here: this report renders no monetary
values. Prices are read as a completeness signal and never printed. The scoring
invariant is this agent's equivalent guarantee, and `docs/02_design.md` says so.
"""

import pytest

from framework.schemas.agent_status import AgentStatus

from src.nodes.compliance_report_generate_node import (
    ComplianceReportGenerateNode,
    enforce_output_invariant,
)
from src.nodes.post_process_node import PostProcessNode, contains_credential

_CLEAN_METRICS = {
    "sku_count": 1,
    "compliant_count": 1,
    "non_compliant_count": 0,
    "average_score": 90,
    "scores": {"SKU-001": 90},
}
_CLEAN_REPORT = "\n".join(
    [
        "### SKU-001 -- Score: 90/100 [PASS]",
        "| Dimension | Score | Max |",
        "|-----------|-------|-----|",
        "| Title Quality | 20 | 20 |",
    ]
)


# ── The invariant checker itself ─────────────────────────────────────────────


def test_a_consistent_report_has_no_violations() -> None:
    """The control. Without it, a checker that flagged everything would look strict."""
    assert enforce_output_invariant(_CLEAN_REPORT, _CLEAN_METRICS) == []


@pytest.mark.parametrize(
    "line,violation",
    [
        ("### SKU-001 -- Score: 140/100 [PASS]", "score_out_of_range"),
        ("### SKU-001 -- Score: -5/100 [FAIL]", "score_out_of_range"),
        ("### SKU-001 -- Score: 50/100 [PASS]", "compliance_flag_disagrees_with_score"),
        ("### SKU-001 -- Score: 90/100 [FAIL]", "compliance_flag_disagrees_with_score"),
    ],
)
def test_a_rendered_score_that_breaks_the_promise_is_caught(line: str, violation: str) -> None:
    assert violation in enforce_output_invariant(line, _CLEAN_METRICS)


def test_a_rendering_that_disagrees_with_the_computation_is_caught() -> None:
    """The report is read back, not trusted.

    The figures and their rendering can disagree, and the reader of a compliance
    report only ever sees the rendering.
    """
    report = "### SKU-001 -- Score: 71/100 [PASS]"
    assert "rendered_score_differs_from_computed" in enforce_output_invariant(report, _CLEAN_METRICS)


def test_a_dimension_scored_above_its_weight_is_caught() -> None:
    report = _CLEAN_REPORT.replace("| Title Quality | 20 | 20 |", "| Title Quality | 40 | 20 |")
    assert "dimension_score_out_of_range" in enforce_output_invariant(report, _CLEAN_METRICS)


def test_an_altered_dimension_weight_is_caught() -> None:
    report = _CLEAN_REPORT.replace("| Title Quality | 20 | 20 |", "| Title Quality | 40 | 40 |")
    assert "dimension_weight_altered" in enforce_output_invariant(report, _CLEAN_METRICS)


def test_summary_counts_that_disagree_with_the_rows_are_caught() -> None:
    metrics = {**_CLEAN_METRICS, "compliant_count": 7}
    assert "compliant_count_disagrees_with_rows" in enforce_output_invariant(_CLEAN_REPORT, metrics)


def test_an_average_outside_the_rendered_range_is_caught() -> None:
    metrics = {**_CLEAN_METRICS, "average_score": 12}
    assert "average_outside_rendered_range" in enforce_output_invariant(_CLEAN_REPORT, metrics)


def test_a_non_inert_sku_id_in_the_rendering_is_caught() -> None:
    """The last line of defence on the one caller string the report renders."""
    report = "### SKU | 999 -- Score: 90/100 [PASS]"
    assert "sku_id_not_inert" in enforce_output_invariant(report, {"scores": {}})


# ── The report node applies it ───────────────────────────────────────────────


@pytest.fixture
def report_node() -> ComplianceReportGenerateNode:
    return ComplianceReportGenerateNode()


def test_a_real_report_is_released(report_node: ComplianceReportGenerateNode) -> None:
    state = {
        "aeo_scores": {
            "SKU-001": {
                "score": 90,
                "compliant": True,
                "unavailable_dimensions": [],
                "breakdown": {
                    "title_quality": 20,
                    "description_depth": 25,
                    "category_precision": 15,
                    "attribute_completeness": 25,
                    "image_availability": 5,
                },
            }
        },
        "remediation_priorities": [],
    }
    result = report_node.execute(state)
    assert result["status"] == AgentStatus.SUCCESS
    assert "SKU-001" in result["compliance_report"]
    assert result["report_metrics"]["sku_count"] == 1


def test_a_violating_report_is_withheld_whole_not_trimmed(
    report_node: ComplianceReportGenerateNode,
) -> None:
    """Partial release of a report whose figures do not hold together is worse.

    The whole value of the document to a merchant is that the numbers can be
    acted on; a trimmed version still carries the ones that survived the cut.
    """
    state = {
        "aeo_scores": {
            "SKU-001": {
                "score": 300,
                "compliant": True,
                "unavailable_dimensions": [],
                "breakdown": {"title_quality": 20},
            }
        },
        "remediation_priorities": [],
    }
    result = report_node.execute(state)
    assert result["status"] == AgentStatus.ERROR
    assert "SKU-001" not in result["compliance_report"]
    assert "300" not in result["compliance_report"]
    assert result["compliance_report"], "a falsy replacement re-opens the envelope fallback"
    assert result["report_metrics"] == {}


# ── Credential containment at the backbone boundary ──────────────────────────


@pytest.fixture
def post_node() -> PostProcessNode:
    return PostProcessNode()


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "sk_live_" + "abcdefghijklmnopqrstuvwx",
        "sk-abcdefghijklmnopqrstuvwxyz12",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc",
        "postgresql://db.internal:5432/appdb",
        "Bearer abc123.def456.ghi789xyz",
    ],
)
def test_framework_detected_credentials_are_caught(secret: str) -> None:
    """These are the ones the template's own pattern set missed entirely.

    Measured before the fix: the local set caught none of the six. A value the
    framework catches and the template misses makes the framework raise inside
    this node, and the wrapper then returns a bare error partial — discarding the
    clearing below. A detector gap is a containment bypass, not a smaller gate.
    """
    assert contains_credential(f"report text {secret} more text")


@pytest.mark.parametrize(
    "secret",
    [
        "password=hunter2",
        "api_key: swordfish",
        "client_secret = abc",
        "Authorization: something",
        "private_key=xyz",
    ],
)
def test_locally_detected_credentials_are_kept(secret: str) -> None:
    """The framework's patterns describe credential FORMATS and match none of these.

    Replacing the local set with the framework detector would have made this gate
    narrower while looking like a tightening. The check is the union of the two.
    """
    from framework.security.credential_detector import detect_credentials_in_value

    assert not detect_credentials_in_value(secret), "kept only because the framework misses it"
    assert contains_credential(secret)


def test_ordinary_report_text_is_not_withheld() -> None:
    """The control: a gate that withholds everything contains nothing useful."""
    assert not contains_credential("# AEO Compliance Report\n| Total SKUs analyzed | 2 |")


def test_a_violation_clears_every_output_bearing_field(post_node: PostProcessNode) -> None:
    """`get_output` returns `formatted_output or result`, so both are live channels.

    Rewriting only one leaves the un-gated report reachable through the other,
    and a falsy replacement re-opens the fallback rather than closing it.
    """
    state = {"result": "# Report\nAKIAIOSFODNN7EXAMPLE appears here"}
    result = post_node.execute(state)
    assert result["status"] == AgentStatus.ERROR
    for field in ("formatted_output", "result", "compliance_report"):
        assert "AKIAIOSFODNN7EXAMPLE" not in str(result[field])
    assert result["formatted_output"]
    assert result["report_metrics"] == {}


def test_a_clean_report_passes_through_unchanged(post_node: PostProcessNode) -> None:
    report = "# AEO Compliance Report\nAll SKUs compliant."
    result = post_node.execute({"result": report})
    assert result["status"] == AgentStatus.SUCCESS
    assert result["formatted_output"] == report


def test_the_error_envelope_carries_no_traceback_or_paths(post_node: PostProcessNode) -> None:
    state = {"result": "password=hunter2"}
    result = post_node.execute(state)
    blob = " ".join(str(v) for v in result.values())
    assert "hunter2" not in blob
    assert "Traceback" not in blob
    assert "/src/" not in blob
