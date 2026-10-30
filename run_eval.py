#!/usr/bin/env -S uv run
"""Run the Harbor task suite (tasks/) against a model, via Harbor's
claude-code, codex or opencode agent.

Usage:
    ./run_eval.py [--agent A] [--model M] [--guidelines] [--dry-run] <job-label> [-- <harbor args>]

    # The paper's Opus 5.5 guidelines run: 5 attempts per question
    ./run_eval.py --model opus-5-5 --guidelines opus55 -- -k 5
    # A self-hosted model through opencode, closed-book
    ./run_eval.py --agent opencode --model qwen-3-6-moe qwen36 -- -k 5
    # Print the harbor command without running it
    ./run_eval.py --dry-run --model opus-5-5 --guidelines opus55

--model takes a key from the agent's MODELS dict (see --help) or a full
model ID. Anything after -- goes to `harbor run`: -k sets attempts per
question, -n how many trials run in parallel (default 1), and
-i <task-glob> restricts the run to matching tasks, e.g. for a retry.

The job is named <YYYYmmdd-HHMMSS>-<label>-<effort?>-<closedbook|guidelines>.

Settings without a flag are read from the environment (or .env):
    auth       ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, OPENAI_API_KEY,
               OPENROUTER_API_KEY, CODEX_AUTH_JSON_PATH
    endpoints  ANTHROPIC_BASE_URL, OPENAI_BASE_URL
    reasoning  CLAUDE_EFFORT, CLAUDE_THINKING_DISPLAY, CODEX_EFFORT, OLLAMA_THINK
    other      MOUNT_TARGET, TIMEOUT_MULTIPLIER, AGENT_VERSION_<AGENT>

Launch every run through this script, including retries, rather than
calling `harbor run` or `harbor job resume` directly: this script sets
ALLOWED_HOSTS, which enforces the container's network lockdown so the
agent's internet access is restricted to the model's API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO_DIR / "scripts" / "misc"))

from agent_versions import pinned  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    argv = sys.argv[1:] if argv is None else argv
    own_args, harbor_args = split_argv(argv)
    args = build_parser().parse_args(own_args)
    config = ExperimentConfig.from_args(args, AGENTS)
    job_label = args.job_label or f"{config.agent}-run"
    job_name = config.job_name(job_label, AGENTS[config.agent].effort_label())
    command = build_harbor_command(config, job_name, harbor_args)
    cwd = REPO_DIR / config.tasks_dir
    if args.dry_run:
        print(f"cd {shlex.quote(str(cwd))} && {shlex.join(redact_secrets(command))}")
        return
    sys.exit(run_harbor(command, cwd=cwd))


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    # Manual split (rather than argparse's own `--`/REMAINDER handling) so
    # "everything after --" is unambiguously passed straight through to
    # harbor, with no interaction with our own flag parsing.
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1:]
    return argv, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Harbor task suite against a model/agent.")
    parser.add_argument(
        "job_label", nargs="?", default=None,
        help="Job label; job name is <timestamp>-<label>-<effort?>-<condition>. Default: '<agent>-run'.",
    )
    parser.add_argument(
        "--agent", choices=sorted(AGENTS), default=os.environ.get("AGENT", "claude-code"),
        help="Which Harbor agent to drive. Default: claude-code, or $AGENT.",
    )
    parser.add_argument(
        "--model", default=os.environ.get("MODEL", ""),
        help="Model name. Default: the agent's own default model, or $MODEL. Either "
             "a key in the chosen agent's MODELS dict (claude-code: sonnet-5, "
             "opus-5, etc.; opencode: qwen-3-8-flash-next, qwen-3-6-moe) or a "
             "raw model string/tag passed straight through.",
    )
    parser.add_argument(
        "--guidelines", action="store_true",
        help="Mount reference docs read-only and allow Read/Grep/Glob.",
    )
    parser.add_argument(
        "--tasks-dir", default=os.environ.get("TASKS_DIR", "tasks/en"),
        help="Task suite directory. Default: tasks/en, or $TASKS_DIR.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the harbor command instead of running it.",
    )
    return parser


# The 101-question core set: q001-q099 plus q100 and q101. tasks/en holds
# all 196 generated tasks, and harbor runs every one unless told otherwise,
# so this has to be passed on every launch.
# Passed as harbor's -i/--include-task-name, which takes globs and repeats.
CORE_TASK_GLOBS = ("q0??-*", "q10[01]-*")


def core_task_args(harbor_args: list[str]) -> list[str]:
    """The core-set filter, unless the caller passed its own -i."""
    if any(a in ("-i", "--include-task-name") or a.startswith("--include-task-name=")
           for a in harbor_args):
        return []
    return [arg for glob in CORE_TASK_GLOBS for arg in ("-i", glob)]


def build_harbor_command(config: ExperimentConfig, job_name: str, harbor_args: list[str]) -> list[str]:
    jobs_dir = REPO_DIR / "runs" / config.lang_name
    command = AGENTS[config.agent].build_command(config)
    command += config.guidelines_flags()
    command += ["--artifact", "/output/answer.txt", "--jobs-dir", str(jobs_dir), "--job-name", job_name]
    command += core_task_args(harbor_args)
    command += harbor_args
    return command


def run_harbor(command: list[str], cwd: Path) -> int:
    return subprocess.run(command, cwd=cwd).returncode


# --ae KEY=VALUE env vars carrying secrets -- masked in --dry-run's printed
# output only (the real command list, actually executed, is untouched).
# Pattern-matched rather than an explicit per-key allowlist, which would
# silently miss whatever the next new provider's env var happens to be named.
_SECRET_ENV_KEY_RE = re.compile(r"(API_KEY|TOKEN|SECRET)$")


def redact_secrets(command: list[str]) -> list[str]:
    redacted = []
    prev_was_ae = False
    for arg in command:
        if prev_was_ae and _SECRET_ENV_KEY_RE.search(arg.split("=", 1)[0]):
            key, _, _ = arg.partition("=")
            arg = f"{key}=***"
        redacted.append(arg)
        prev_was_ae = arg == "--ae"
    return redacted


@dataclass
class ExperimentConfig:
    agent: str
    model: str
    guidelines: bool
    tasks_dir: str
    lang_name: str
    mount_target: str

    @classmethod
    def from_args(cls, args: argparse.Namespace, agents: dict[str, AgentHarness]) -> ExperimentConfig:
        agent = agents.get(args.agent)
        if agent is None:
            # Only reachable via a bad $AGENT default that bypassed --agent's
            # own choices= validation (argparse doesn't validate unused defaults).
            sys.exit(f"error: AGENT must be one of {', '.join(agents)}, got '{args.agent}'")
        return cls(
            agent=args.agent,
            model=args.model or agent.default_model,
            guidelines=args.guidelines,
            tasks_dir=args.tasks_dir,
            lang_name=Path(args.tasks_dir).name,
            mount_target=os.environ.get("MOUNT_TARGET", "/guidelines"),
        )

    @property
    def condition_label(self) -> str:
        """The run's condition as one unhyphenated token.

        Unhyphenated so that a job name splits cleanly on "-" into its parts.
        """
        return "guidelines" if self.guidelines else "closedbook"

    @property
    def extra_instruction_path(self) -> str:
        name = "guidelines_allowed" if self.guidelines else "closed_book"
        return f"instructions/extra_instructions/{name}.md"

    def job_name(self, label: str, effort: str | None = None) -> str:
        """<timestamp>-<label>-<effort?>-<condition>."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        parts = [timestamp, *(t for t in label.split("-") if t)]
        if effort:
            parts.append(effort)
        parts.append(self.condition_label)
        return "-".join(parts)

    def guidelines_flags(self) -> list[str]:
        flags = ["--extra-instruction-path", str(REPO_DIR / self.extra_instruction_path)]
        if self.guidelines:
            mount = {
                "type": "bind",
                "source": str(REPO_DIR / "data" / "iucn-guidelines" / "current"),
                "target": self.mount_target,
                "read_only": True,
            }
            flags = ["--mounts", json.dumps([mount])] + flags
        return flags


class AgentHarness(ABC):
    """Knows how to build the `harbor run` invocation for one Harbor agent,
    including resolving whatever auth/tuning env vars only it needs."""

    default_model: str

    # Harbor's agent name, for looking up the CLI version pin.
    agent_name: str

    # Grants the trial container NET_ADMIN so its baked-in entrypoint
    # (scripts/setup/generate_harbor_tasks.py's NETWORK_LOCKDOWN_SH) can enforce
    # ALLOWED_HOSTS below with plain iptables -- Harbor's own
    # network_mode="allowlist" can't be used here (it needs a kernel module
    # this project's Docker Desktop host lacks).
    NETWORK_LOCKDOWN_COMPOSE = str(REPO_DIR / "docker" / "network-lockdown-cap-add.compose.yaml")

    @abstractmethod
    def build_command(self, config: ExperimentConfig) -> list[str]:
        ...

    def _version_args(self) -> list[str]:
        """Pin the agent's CLI version (scripts/misc/agent_versions.py).

        Harbor installs @latest otherwise, which lets a single job's trials
        run on different CLI builds -- see that module for why that matters.
        `version` is a constructor kwarg on
        BaseInstalledAgent, so it travels as an --ak like any other."""
        version = pinned(self.agent_name)
        return ["--ak", f"version={version}"] if version else []

    def effort_label(self) -> str | None:
        """The reasoning-effort token for this run's job name, or None when
        the agent has no such knob. Only ever reports an effort this script
        actually SET: a model's own API default is not encoded, because the
        default differs per model and is not verified here."""
        return None

    def _network_lockdown_args(self, config: ExperimentConfig, allowed_hosts: list[str]) -> list[str]:
        value = ",".join(allowed_hosts)
        # The compose override's `environment: ALLOWED_HOSTS: ${ALLOWED_HOSTS:-}`
        # is what actually reaches the container's ENTRYPOINT (see that
        # file's comment for why -- --ae alone leaves iptables at its default
        # ACCEPT policy). docker compose resolves ${ALLOWED_HOSTS} from the env of
        # the process that invokes it, i.e. this harbor subprocess's env,
        # which subprocess.run(command, cwd=cwd) in run_harbor() inherits
        # from os.environ as it stands right now.
        os.environ["ALLOWED_HOSTS"] = value
        args = ["--extra-docker-compose", self.NETWORK_LOCKDOWN_COMPOSE]
        if value:
            # Also visible inside the container for each exec'd phase
            # (setup/agent/verifier) -- not load-bearing for the lockdown
            # itself, just handy for debugging a trial's env.
            args += ["--ae", f"ALLOWED_HOSTS={value}"]
        return args

    @staticmethod
    def _hostname(url: str) -> str:
        host = urllib.parse.urlsplit(url).hostname
        if not host:
            sys.exit(f"error: couldn't parse a hostname out of '{url}' for the network allowlist.")
        return host


class ClaudeCodeHarness(AgentHarness):
    default_model = "opus-5-5"
    agent_name = "claude-code"
    DEFAULT_EFFORT = "high"

    # Full Anthropic model IDs, each verified against a run's raw transcript
    # to resolve to the model it claims. Deliberately not the bare CLI
    # aliases (anthropic/opus, anthropic/sonnet), which drift as new models
    # ship. --model accepts either a key below or a raw anthropic/<id>
    # string directly.
    MODELS: ClassVar[dict[str, str]] = {
        "sonnet-4-5": "anthropic/claude-sonnet-4-5",
        "sonnet-5": "anthropic/claude-sonnet-5",
        "sonnet-5-5": "anthropic/claude-sonnet-5-5",
        "opus-4-5": "anthropic/claude-opus-4-5-20251101",
        "opus-5": "anthropic/claude-opus-5",
        "opus-5-5": "anthropic/claude-opus-5-5",
    }

    def build_command(self, config: ExperimentConfig) -> list[str]:
        model = self.MODELS.get(config.model, config.model)
        allowed_tools = "Bash,Write,Read,Grep,Glob" if config.guidelines else "Bash,Write,Read"
        command = [
            "harbor", "run", "-p", ".", "-a", "claude-code", "-m", model,
            *self._version_args(),
            "-n", "1", "--max-retries", "3",
            *self._auth_args(),
            "--ak", f"allowed_tools={allowed_tools}",
            "--ak", f"disallowed_tools={self._disallowed_tools()}",
            *self._network_lockdown_args(config, [self._allowed_host()]),
        ]
        # Always explicit, never the model's own API default, which differs
        # between models. $CLAUDE_EFFORT ("low"/"medium"/"high"/"xhigh"/"max")
        # overrides it.
        command += ["--ak", f"reasoning_effort={self.effort_label()}"]
        # $CLAUDE_THINKING_DISPLAY ("summarized"/"omitted") overrides the
        # model's API default for whether thinking blocks come back with
        # text in them. The 4.5 models return readable thinking, while Opus
        # 5, Sonnet 5 and Opus 5.5 default to "omitted": a block with an
        # empty `thinking` field and a signature only. Display is a
        # visibility setting, not a billing one -- the thinking happens and
        # is charged either way -- so leaving it unset archives less than
        # the API will give for the same money (on the Opus 5 guidelines
        # job, roughly 80% of billed output tokens were not recorded).
        # Defaults to "summarized"; set CLAUDE_THINKING_DISPLAY=omitted to
        # opt out. What comes back is a summary the model writes of its own
        # reasoning, never the raw chain of thought: treat it as the model's
        # account of what it did, not a trace of it.
        thinking_display = os.environ.get("CLAUDE_THINKING_DISPLAY", "summarized")
        if thinking_display:
            command += ["--ak", f"thinking_display={thinking_display}"]
        return command

    def effort_label(self) -> str | None:
        return os.environ.get("CLAUDE_EFFORT", self.DEFAULT_EFFORT)

    def _allowed_host(self) -> str:
        # Bash is not in claude-code's disallowed_tools (see
        # _disallowed_tools below), and WebSearch/WebFetch denial alone
        # doesn't stop a `curl`; the network lockdown closes that gap.
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        return self._hostname(base_url) if base_url else "api.anthropic.com"

    def _disallowed_tools(self) -> str:
        # --allowedTools does NOT actually restrict access in this Claude Code
        # CLI version combined with --permission-mode=bypassPermissions --
        # this denylist is what
        # actually gates tool access. Task/Workflow/Skill always denied (no
        # legitimate subagent-delegation use for a single exam question, and
        # burns the full agent timeout on the blocked deep-research workaround
        # otherwise).
        return "WebSearch,WebFetch,Task,Workflow,Skill"

    def _auth_args(self) -> list[str]:
        # ANTHROPIC_BASE_URL points claude-code at any Anthropic Messages-API-
        # compatible endpoint instead of the real API.
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        if base_url:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "ollama")
            return ["--ae", f"ANTHROPIC_BASE_URL={base_url}", "--ae", f"ANTHROPIC_API_KEY={api_key}"]
        return ["--ae", "CLAUDE_FORCE_OAUTH=1", "--ae", f"CLAUDE_CODE_OAUTH_TOKEN={self._oauth_token()}"]

    def _oauth_token(self) -> str:
        # main() loads .env (via python-dotenv) before this ever runs, so a
        # token kept there is already in os.environ by now.
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if not token:
            sys.exit("error: CLAUDE_CODE_OAUTH_TOKEN not set. Run 'claude setup-token' to mint one, or add it to .env.")
        return token


class OpenCodeHarness(AgentHarness):
    default_model = "qwen-3-6-moe"
    agent_name = "opencode"
    DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434/v1"

    # Local Ollama tags. Values are full <provider>/<model-id> strings --
    # "openai" here means "local, via the OpenAI-compatible endpoint" (see
    # _auth_args), not literally OpenAI. Deliberately not qwen3.6's -mlx
    # tags: Ollama's MLX runner doesn't decode image tokens for qwen3.6,
    # while the GGUF tag does. --model accepts either a key below or a raw
    # provider/model string directly (bare tags with no "/" are assumed
    # local Ollama and get "openai/" prepended).
    MODELS: ClassVar[dict[str, str]] = {
        "qwen-3-6-moe": "openai/qwen3.6:35b-a3b",
        # Qwen3.8-Flash-Next: 125B MoE (6B active). The only tag on Ollama
        # is -mlx (no GGUF alternative).
        "qwen-3-8-flash-next": "openai/qwen3.8-flash-next:125b-mlx",
        # The same weights served by Alibaba through OpenRouter.
        "qwen-3-8-flash-next-openrouter": "openrouter/qwen/qwen3.8-flash",
    }

    def build_command(self, config: ExperimentConfig) -> list[str]:
        model = self._resolve_model(config)
        provider = model.split("/", 1)[0]
        opencode_config = self._permission_config()
        # $OLLAMA_THINK ("low"/"medium"/"high"/etc, model-dependent) controls
        # reasoning effort for local Ollama models. NOT wired through
        # opencode's own "reasoningEffort" model option -- that forces
        # opencode to route the request through the OpenAI Responses API
        # (a "developer"-role message), which Ollama's OpenAI-compatible
        # endpoint rejects ('unexpected message role "developer"'). Instead
        # this goes in as a raw options.extraBody field, which opencode
        # merges straight into the request body untouched -- still the plain
        # chat-completions path, and Ollama's /v1/chat/completions accepts a
        # bare "think" field as a non-standard extension. For OpenRouter-hosted
        # models the same variable becomes OpenRouter's own `reasoning.effort`
        # field, so a hosted run can be pinned to its local counterpart's level.
        think = os.environ.get("OLLAMA_THINK", "")
        if think:
            model_tag = model.split("/", 1)[1]
            options = {"reasoning": {"effort": think}} if provider == "openrouter" else {"extraBody": {"think": think}}
            opencode_config["provider"] = {provider: {"models": {model_tag: {"options": options}}}}
        command = [
            "harbor", "run", "-p", ".", "-a", "opencode", "-m", model,
            *self._version_args(),
            "-n", "1", "--max-retries", "3",
            *self._auth_args(provider),
            "--ae", "OPENCODE_FAKE_VCS=git",
            "--ak", f"opencode_config={json.dumps(opencode_config)}",
            *self._network_lockdown_args(config, self._allowed_hosts(provider)),
        ]
        if config.guidelines:
            command += ["--agent-timeout-multiplier", os.environ.get("TIMEOUT_MULTIPLIER", "12")]
        return command

    def effort_label(self) -> str | None:
        return os.environ.get("OLLAMA_THINK") or None

    def _resolve_model(self, config: ExperimentConfig) -> str:
        model = self.MODELS.get(config.model, config.model)
        return model if "/" in model else f"openai/{model}"

    def _allowed_hosts(self, provider: str) -> list[str]:
        # The `websearch`/`webfetch` permission denial in _permission_config
        # below doesn't cover opencode's `bash` tool, which models could
        # use to `curl` search engines directly.
        if provider == "openrouter":
            return ["openrouter.ai"]
        return [self._hostname(os.environ.get("OPENAI_BASE_URL", self.DEFAULT_OLLAMA_URL))]

    def _auth_args(self, provider: str) -> list[str]:
        if provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                sys.exit("error: set OPENROUTER_API_KEY in .env for openrouter models.")
            return ["--ae", f"OPENROUTER_API_KEY={api_key}"]
        base_url = os.environ.get("OPENAI_BASE_URL", self.DEFAULT_OLLAMA_URL)
        self._ensure_ollama_running(base_url)
        return [
            "--ae", f"OPENAI_BASE_URL={base_url}",
            "--ae", f"OPENAI_API_KEY={os.environ.get('OPENAI_API_KEY', 'ollama')}",
        ]

    def _permission_config(self) -> dict:
        # websearch/webfetch denied by default (opencode loops retrying them
        # with no one to answer an interactive prompt); task/skill always
        # denied, matching claude-code's Task/Workflow/Skill denylist.
        return {"permission": {"websearch": "deny", "webfetch": "deny", "task": "deny", "skill": "deny"}}

    def _ensure_ollama_running(self, base_url: str) -> None:
        if base_url != self.DEFAULT_OLLAMA_URL:
            return  # only applies to the default local Ollama target
        try:
            urllib.request.urlopen("http://localhost:11434/api/version", timeout=3)
        except OSError:
            sys.exit("error: Ollama doesn't seem to be running on localhost:11434.")


class CodexHarness(AgentHarness):
    """OpenAI's Codex CLI, via Harbor's `codex` agent. Like claude-code, and
    unlike opencode, this one ALWAYS passes reasoning effort explicitly (see
    $CODEX_EFFORT below) rather than letting the model's own API default
    apply."""

    default_model = "gpt-6-luna"
    agent_name = "codex"
    DEFAULT_EFFORT = "high"
    # Codex takes a bare model id (its CLI gets `--model <id>` directly), not
    # the provider/model form opencode needs. --model accepts any raw id too,
    # for a model not listed here yet.
    MODELS: ClassVar[dict[str, str]] = {
        "gpt-6-luna": "gpt-6-luna",
        "gpt-6-sol": "gpt-6-sol",
    }

    def build_command(self, config: ExperimentConfig) -> list[str]:
        model = self.MODELS.get(config.model, config.model)
        # Always explicit, never the model's own default, which differs
        # between models. Harbor's codex agent does default this flag to
        # "high" itself, but a Harbor upgrade could change that without
        # anything in this repo changing.
        effort = os.environ.get("CODEX_EFFORT", self.DEFAULT_EFFORT)
        # The container network lockdown blocks the web for every agent;
        # Codex's own web_search setting is disabled as well.
        return [
            "harbor", "run", "-p", ".", "-a", "codex", "-m", model,
            *self._version_args(),
            "-n", "1", "--max-retries", "3",
            *self._auth_args(),
            "--ak", f"reasoning_effort={effort}",
            "--ak", "web_search=disabled",
            *self._network_lockdown_args(config, self._allowed_hosts()),
        ]

    # ChatGPT-subscription auth (auth_mode "chatgpt") does NOT talk to
    # api.openai.com: Codex routes inference through chatgpt.com's backend
    # and refreshes the OAuth tokens against auth.openai.com (the id_token's
    # own `iss`). api.openai.com is the API-key path. All three are allowed
    # for either mode -- they're all OpenAI auth/inference endpoints, none
    # is a search engine or an IUCN source, so exam integrity is unaffected
    # and a mid-run token refresh can't be silently strangled by the
    # lockdown.
    ALLOWED_HOSTS: ClassVar[tuple[str, ...]] = (
        "chatgpt.com", "auth.openai.com", "api.openai.com",
    )

    def effort_label(self) -> str | None:
        # Always set by build_command, so always worth recording.
        return os.environ.get("CODEX_EFFORT", self.DEFAULT_EFFORT)

    def _allowed_hosts(self) -> list[str]:
        base_url = os.environ.get("OPENAI_BASE_URL", "")
        return [self._hostname(base_url)] if base_url else list(self.ALLOWED_HOSTS)

    def _auth_args(self) -> list[str]:
        # Subscription auth is the default here, mirroring what
        # ClaudeCodeHarness does with CLAUDE_FORCE_OAUTH -- Harbor's codex
        # agent uploads ~/.codex/auth.json into the container when
        # CODEX_FORCE_AUTH_JSON is truthy (see that agent's
        # _resolve_auth_json_path). `codex login` writes that file; its
        # auth_mode is "chatgpt" for a ChatGPT subscription.
        #
        # Precedence is deliberate: the subscription wins over a stray
        # $OPENAI_API_KEY, because $OPENAI_API_KEY is overloaded in this
        # repo -- OpenCodeHarness passes it as a dummy ("ollama") for the
        # local Ollama endpoint. Letting a key win by accident would
        # silently bill per-token API usage for a run meant to go through
        # the subscription. Set CODEX_AUTH_JSON_PATH to point at a
        # different auth.json, or unset/remove it to fall back to the key.
        explicit_path = os.environ.get("CODEX_AUTH_JSON_PATH", "")
        if explicit_path:
            if not Path(explicit_path).is_file():
                sys.exit(f"error: CODEX_AUTH_JSON_PATH does not exist: {explicit_path}")
            return ["--ae", f"CODEX_AUTH_JSON_PATH={explicit_path}"]

        default_auth = Path.home() / ".codex" / "auth.json"
        if default_auth.is_file():
            return ["--ae", "CODEX_FORCE_AUTH_JSON=1"]

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key or api_key == "ollama":
            sys.exit(
                "error: no codex credentials. Run 'codex login' to use a ChatGPT "
                "subscription, or set a real OPENAI_API_KEY for API-key billing."
            )
        return ["--ae", f"OPENAI_API_KEY={api_key}"]


AGENTS: dict[str, AgentHarness] = {
    "claude-code": ClaudeCodeHarness(),
    "codex": CodexHarness(),
    "opencode": OpenCodeHarness(),
}


if __name__ == "__main__":
    main()
