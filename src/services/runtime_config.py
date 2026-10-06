"""AgentCore Platform v1.0 — RET-C2-196 runtime configuration"""

# The single reader of config/config.yaml.
#
# The manifest (config/agent.yaml) carries identity and the compile-time gates and
# nothing else; every value that changes how a run behaves lives in
# config/config.yaml and is read here. Keeping one reader matters because the
# manifest used to carry an `agent.config` block: code that still looked there
# would now find nothing, take a built-in default instead, and report success.
#
# The values are operator configuration, not caller input, so a malformed
# declaration fails loudly at import rather than degrading to a default. A
# silently-ignored setting is the failure mode this module exists to prevent.

from pathlib import Path
from typing import Any

from framework.utils.config_loader import load_agent_config

# src/services/<this file> -> parents[2] is the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Applied only when config/config.yaml omits the key entirely. A key that is
# present but unusable is an error, never a silent fall back to these.
_DEFAULTS: dict[str, int] = {"max_retry": 3, "timeout_s": 30}

# The framework rejects max_retry at or above its own ceiling, so staying below
# it here turns a deploy-time failure into an import-time one with the file named.
_MAX_RETRY_CEILING = 10
_MAX_TIMEOUT_S = 3600


class ConfigurationError(ValueError):
    """A declared runtime value is absent, malformed, or out of range."""


def _bounded_int(source: dict[str, Any], key: str, low: int, high: int) -> int:
    """Read one integer setting, or raise naming the key and the accepted range.

    ``bool`` is rejected explicitly: it is a subclass of ``int``, so ``True``
    would otherwise be accepted and silently behave as ``1``.
    """
    if key not in source:
        return _DEFAULTS[key]
    value = source[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"config/config.yaml: {key!r} must be an integer in [{low}, {high}]")
    if not low <= value <= high:
        raise ConfigurationError(f"config/config.yaml: {key!r} must be an integer in [{low}, {high}]")
    return int(value)


def agent_config() -> dict[str, Any]:
    """Return the runtime configuration the graph is constructed with.

    ``max_retry`` has a live reader in the framework backbone: it bounds the
    pre_process retry route and is validated when the graph is built. Passing
    this dict to the graph constructor is what makes the declared value
    effective — construct the graph with no config and the framework substitutes
    its own default while the declaration sits unread.

    ``timeout_s`` is the declared per-call budget for the hosting runtime.
    Nothing in the framework or in this template enforces it today, so it is a
    statement of intent rather than a limit, and it is validated here only so a
    malformed value cannot sit in the file looking effective.
    """
    raw = load_agent_config(_REPO_ROOT)
    return {
        "max_retry": _bounded_int(raw, "max_retry", 0, _MAX_RETRY_CEILING - 1),
        "timeout_s": _bounded_int(raw, "timeout_s", 1, _MAX_TIMEOUT_S),
    }
