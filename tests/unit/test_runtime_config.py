"""Runtime configuration: declared values must reach the thing that reads them.

The manifest used to carry an `agent.config` block. After the move to the flat
schema there is no such block, so anything still reading it returns an empty
mapping and every declared value is silently replaced by a built-in default —
manifest valid, suite green, declaration dead. These tests pin the live path
instead of the file's contents.
"""

from pathlib import Path

import pytest

from src.services.runtime_config import ConfigurationError, _bounded_int, agent_config

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_config_file_exists_where_the_loader_looks() -> None:
    assert (_REPO_ROOT / "config" / "config.yaml").exists()


def test_declared_values_are_returned() -> None:
    config = agent_config()
    assert isinstance(config["max_retry"], int)
    assert isinstance(config["timeout_s"], int)


def test_max_retry_reaches_the_backbone() -> None:
    """The framework reads `max_retry` off the graph's own config, not the file.

    Constructing the graph without passing this dict leaves the declaration
    unread while the framework substitutes its own default, which is the failure
    this asserts against — a non-default value must be the one that is live.
    """
    from src.graph.graph import ECProductAEOComplianceCheckAgent

    graph = ECProductAEOComplianceCheckAgent(config={"max_retry": 7, "timeout_s": 30})
    assert graph.config["max_retry"] == 7


def test_the_entry_point_constructs_the_graph_with_the_declared_config() -> None:
    import os

    os.environ.setdefault("INVOKE_AUTH_TOKEN", "integration-test-token")
    from src.api.server import agent

    assert agent.config["max_retry"] == agent_config()["max_retry"]
    assert agent.config["timeout_s"] == agent_config()["timeout_s"]


@pytest.mark.parametrize("value", ["3", 3.0, True, None, -1, 99])
def test_a_malformed_declaration_fails_loudly(value: object) -> None:
    """Operator configuration, not caller input: a bad value is an error, not a default.

    Degrading to a default here is how a setting stops meaning anything without
    anyone noticing.
    """
    with pytest.raises(ConfigurationError):
        _bounded_int({"max_retry": value}, "max_retry", 0, 9)


def test_an_absent_key_takes_the_documented_default() -> None:
    assert _bounded_int({}, "max_retry", 0, 9) == 3
