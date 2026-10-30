"""
The pinned CLI version of each agent, used by run_eval.py (passed to Harbor
as `--ak version=`) and generate_harbor_tasks.py (which installs the
claude-code CLI in the task image at that version). Without a pin Harbor installs @latest, so trials of one job could
run different CLI versions.

$AGENT_VERSION_<AGENT> overrides a pin (e.g. AGENT_VERSION_CLAUDE_CODE);
set it empty to unpin.
"""
from __future__ import annotations

import os

# The versions the paper's runs used, each taken from one of those runs.
AGENT_VERSIONS: dict[str, str] = {
    "claude-code": "2.1.280",   # 20260928-140813-opus55-thinkingsummary-high-guidelines
    "opencode": "1.18.32",      # 20260927-200254-qwen38flashnext-low-closedbook
    "codex": "0.156.1",         # 20260923-171157-gpt6sol-high-closedbook
}


def pinned(agent: str) -> str | None:
    """The pin for `agent`, or None to let Harbor install @latest.

    $AGENT_VERSION_<AGENT> overrides one pin (e.g. AGENT_VERSION_CLAUDE_CODE),
    and setting it empty deliberately unpins that agent for a run."""
    override = os.environ.get(f"AGENT_VERSION_{agent.upper().replace('-', '_')}")
    if override is not None:
        return override or None
    return AGENT_VERSIONS.get(agent)
