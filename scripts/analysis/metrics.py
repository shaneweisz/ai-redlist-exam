"""
The measurements behind every number in the paper, imported by the
build_*_data.py scripts: the reported runs (JOBS), per-attempt outcomes and
answers, accuracy, pass@k and pass^k, majority vote, run-to-run intervals,
tokens, cost, timing and tool calls.

pass@k is implemented here (Chen et al. 2021) rather than imported from
harbor, whose version is a private internal of its own install.
"""
from __future__ import annotations

import itertools
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]

# (model, condition) -> job directory (relative to REPO_DIR).
JOBS: dict[tuple[str, str], str] = {
    ("Opus 5", "Guidelines"): "runs/en/20260728-203911-opus5-guidelines",
    ("Opus 5", "Closed-book"): "runs/en/20260728-203904-opus5-closedbook",
    # Opus 5.5 and Sonnet 5.5 at reasoning effort "high", set explicitly:
    # Opus 5.5's API default is "medium", one level below Opus 5's "high".
    ("Opus 5.5", "Guidelines"): "runs/en/20260928-140813-opus55-thinkingsummary-high-guidelines",
    ("Opus 5.5", "Closed-book"): "runs/en/20260928-165153-opus55-thinkingsummary-high-closedbook",
    ("Sonnet 5.5", "Guidelines"): "runs/en/20260929-113758-sonnet55-high-guidelines",
    ("Sonnet 5.5", "Closed-book"): "runs/en/20260929-120319-sonnet55-high-closedbook",
    ("Sonnet 5", "Guidelines"): "runs/en/20260730-215859-sonnet5-guidelines",
    ("Sonnet 5", "Closed-book"): "runs/en/20260730-215035-sonnet5-closedbook",
    ("Qwen3.6:35b-a3b", "Guidelines"): "runs/en/20260727-152131-qwen36a3b-guidelines",
    ("Qwen3.6:35b-a3b", "Closed-book"): "runs/en/20260727-151740-qwen36a3b-closedbook",
    ("Qwen3.8-Flash-Next", "Guidelines"): "runs/en/20260918-172737-qwen38flashnext-low-guidelines",
    ("Qwen3.8-Flash-Next", "Closed-book"): "runs/en/20260927-200254-qwen38flashnext-low-closedbook",
    # GPT-6 at reasoning effort "high" (run_eval.py's CodexHarness always
    # passes it explicitly).
    ("GPT-6 Luna", "Guidelines"): "runs/en/20260923-114440-gpt6luna-high-guidelines",
    ("GPT-6 Luna", "Closed-book"): "runs/en/20260923-120551-gpt6luna-high-closedbook",
    ("GPT-6 Sol", "Guidelines"): "runs/en/20260923-132236-gpt6sol-high-guidelines",
    ("GPT-6 Sol", "Closed-book"): "runs/en/20260923-171157-gpt6sol-high-closedbook",
    ("Sonnet 4.5", "Guidelines"): "runs/en/20260901-123414-sonnet45-guidelines",
    ("Sonnet 4.5", "Closed-book"): "runs/en/20260906-212300-sonnet45-closedbook",
    ("Opus 4.5", "Guidelines"): "runs/en/20260910-210735-opus45-guidelines",
    ("Opus 4.5", "Closed-book"): "runs/en/20260913-172726-opus45-closedbook",
}

# Harness/deployment per model, which makes tok/s comparisons legible:
# claude-code and codex talk to their providers' APIs directly; opencode
# talks to Ollama on a local Mac Studio (M2 Ultra).
HARNESS: dict[str, str] = {
    "Opus 5": "claude-code",
    "Opus 5.5": "claude-code",
    "Sonnet 5": "claude-code",
    "Sonnet 5.5": "claude-code",
    "Qwen3.6:35b-a3b": "opencode (local Mac Studio, M2 Ultra)",
    "Qwen3.8-Flash-Next": "opencode (local Mac Studio, M2 Ultra)",
    "GPT-6 Luna": "codex",
    "GPT-6 Sol": "codex",
    "Sonnet 4.5": "claude-code",
    "Opus 4.5": "claude-code",
}

K_VALUES = [2, 3, 4, 5]


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al. 2021): probability that a
    random size-k subset of n attempts (c of which succeeded) contains at
    least one success."""
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Probability that ALL k of a random size-k subset of n attempts (c of
    which succeeded) are correct: the unbiased hypergeometric estimator
    C(c, k) / C(n, k). Same Chen et al. (2021) family as pass_at_k, but for
    "all succeed" rather than "at least one succeeds" -- a reliability
    signal rather than a headroom one. 0 whenever there aren't enough
    successes (c < k) or attempts (n < k) to fill a k-subset."""
    if c < k or n < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def task_outcomes(job_dir: Path) -> dict[str, list[int]]:
    """Per-task list of 0/1 attempt outcomes.

    Errored trials count as failed attempts, matching harbor's own
    compute_pass_at_k_by_evals -- otherwise a job with any errors looks
    like it has fewer attempts per task than it actually does.

    WARNING -- the returned lists carry NO attempt ordering. result.json
    groups trial names *by reward value*, so each task's list comes out
    sorted by outcome: every 1 first, then every 0. Anything order-
    dependent built on this will be silently wrong -- taking the r-th
    element of each list as "round r" produces scores that climb
    monotonically across r purely as an artifact. Use round_scores() below, which recovers the
    real ordering from each trial's started_at."""
    result = json.loads((job_dir / "result.json").read_text())
    eval_data = next(iter(result["stats"]["evals"].values()))
    # A trial can be in both lists: an agent timeout still gets verified
    # (reward 0) and is also recorded as an AgentTimeoutError. Keyed by
    # trial name so each attempt counts once -- counting both inflated
    # the Qwen jobs to six or seven attempts on some tasks.
    by_trial: dict[str, int] = {}
    for reward_str, trial_names in eval_data["reward_stats"]["reward"].items():
        for trial_name in trial_names:
            by_trial[trial_name] = int(float(reward_str))
    for trial_names in eval_data.get("exception_stats", {}).values():
        for trial_name in trial_names:
            by_trial.setdefault(trial_name, 0)
    outcomes: dict[str, list[int]] = defaultdict(list)
    for trial_name, reward in by_trial.items():
        outcomes[trial_name.split("__")[0]].append(reward)
    return outcomes


def pass_hat_summary(job_dir: Path) -> dict[int, float]:
    """pass^k across the job, computed from the same per-task outcomes
    pass@k uses so the two are directly comparable."""
    outcomes = task_outcomes(job_dir)
    n = min(len(o) for o in outcomes.values())
    return {
        k: sum(pass_hat_k(n, sum(o), k) for o in outcomes.values()) / len(outcomes) * 100
        for k in K_VALUES
        if k <= n
    }


def trial_names(job_dir: Path) -> set[str]:
    """The trials result.json counts as part of this job.

    This is deliberately not the same as "every subdirectory": a job that
    was narrowed to a smaller task set after running can keep the deleted
    tasks' sibling directories on disk, and result.json is the only authority on which trials the job
    actually consists of."""
    result = json.loads((job_dir / "result.json").read_text())
    eval_data = next(iter(result["stats"]["evals"].values()))
    names = {name for names in eval_data["reward_stats"]["reward"].values() for name in names}
    return names | {name for names in eval_data.get("exception_stats", {}).values() for name in names}


def answers_by_task(job_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """Per-task (answer text, reward) for every attempt. An attempt with no
    answer file (timed out, errored) is kept as its own distinct "no answer"
    outcome rather than dropped, so it can lose a vote instead of silently
    not casting one; one with no reward file scores 0, matching
    task_outcomes and round_scores."""
    valid = trial_names(job_dir)
    by_task: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for trial_dir in sorted(job_dir.glob("*")):
        if trial_dir.name not in valid:
            continue
        reward = trial_reward(trial_dir)
        answer_path = trial_dir / "artifacts" / "output" / "answer.txt"
        answer = answer_path.read_text().strip() if answer_path.exists() else "\0no-answer"
        by_task[trial_dir.name.split("__")[0]].append((answer, reward))
    return by_task


def plurality_score(pairs: list[tuple[str, int]]) -> float:
    """Is the plurality answer correct, as the expected value under random
    tie-breaking: the share of the tied top answers that are correct.

    Ties are not a corner case -- 6 to 19 of the 101 questions end in one on
    the weaker runs -- so how they are scored is worth stating. This used to
    take the first occurrence, which for answers_by_task means the first
    trial directory name, i.e. a random hash suffix: it awarded a whole
    question on a coin flip and made the reported score depend on how the
    trials happened to be named (up to 3 points on Qwen3.8's guidelines
    run, 88.1 under that ordering against 86.2 here). Averaging over the
    tied answers is what a deployer breaking ties at random would score in
    expectation, and it does not depend on any ordering at all.

    Confirmed directly (2026-09-01, across two full 101-question jobs) that
    identical answer text always yields identical reward for these
    exact-match/pattern graders, so any one occurrence's reward stands in
    for the tied text's correctness."""
    counts = Counter(answer for answer, _ in pairs)
    top = max(counts.values())
    tied = [answer for answer, count in counts.items() if count == top]
    rewards = dict(pairs)
    return sum(rewards[answer] for answer in tied) / len(tied)


def majority_vote_accuracy(job_dir: Path) -> float | None:
    """Mean over tasks of "is the plurality answer across all attempts
    correct" -- self-consistency, and unlike pass@k an actually deployable
    strategy, since picking the modal answer needs no oracle.

    Ties are scored as their expected value under random tie-breaking (see
    plurality_score), so a question can contribute a fraction. Returns None
    if the job has no trials at all, rather than a fake 0%."""
    by_task = answers_by_task(job_dir)
    if not by_task:
        return None
    return sum(plurality_score(pairs) for pairs in by_task.values()) / len(by_task) * 100


def answers_by_round(job_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """Per-task (answer text, reward) ordered by round, truncated to the R
    rounds every task has -- answers_by_task with round_scores' ordering, so
    a subset of rounds means the same repeat of the exam for every task.

    A trial with no reward file (errored, timed out) scores 0 and votes as
    its own distinct "no answer", matching round_scores and answers_by_task
    respectively. Dropping it instead would cost the whole job a round: R is
    the minimum over tasks, so one task short of an answer truncates every
    task (it took Qwen3.6 guidelines from 10 subsets to 4)."""
    valid = trial_names(job_dir)
    by_task: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for trial_result_path in job_dir.glob("*/result.json"):
        trial_dir = trial_result_path.parent
        if trial_dir.name not in valid:
            continue
        started_at = json.loads(trial_result_path.read_text()).get("started_at")
        if not started_at:
            continue
        reward = trial_reward(trial_dir)
        answer_path = trial_dir / "artifacts" / "output" / "answer.txt"
        answer = answer_path.read_text().strip() if answer_path.exists() else "\0no-answer"
        by_task[trial_dir.name.split("__")[0]].append((started_at, answer, reward))
    if not by_task:
        return {}
    rounds = min(len(attempts) for attempts in by_task.values())
    return {
        task: [(answer, reward) for _, answer, reward in sorted(attempts)[:rounds]]
        for task, attempts in by_task.items()
    }


def majority_vote_at_k(job_dir: Path, k: int) -> dict | None:
    """Majority vote over k of the job's R rounds, averaged over all C(R, k)
    ways of choosing them, with the standard deviation across those choices.

    majority_vote_accuracy uses every attempt; this answers the deployment
    question "what if I ran it k times instead?", which at k < R has no
    single answer -- which k runs you happened to make matters. Each of the
    C(R, k) subsets is scored exactly as majority_vote_accuracy scores the
    full set (plurality answer per task, ties as their expected value under
    random tie-breaking -- see plurality_score), and the spread over the
    subsets is reported alongside the mean.

    `sd` is that spread, NOT a standard error: the C(R, k) subsets overlap
    heavily (at R=5, k=3 every pair of subsets shares at least one round),
    so they are not independent samples and dividing by sqrt(C(R, k)) would
    claim a precision the design does not have. Read it as "how much the
    answer moves depending on which k runs you got".

    None when the job has fewer than k rounds; `sd` is None at k = R, where
    there is only one subset."""
    by_task = answers_by_round(job_dir)
    if not by_task:
        return None
    rounds = len(next(iter(by_task.values())))
    if rounds < k:
        return None
    scores = []
    for subset in itertools.combinations(range(rounds), k):
        correct = sum(plurality_score([pairs[r] for r in subset]) for pairs in by_task.values())
        scores.append(correct / len(by_task) * 100)
    return {
        "mean": statistics.mean(scores),
        "sd": statistics.stdev(scores) if len(scores) > 1 else None,
        "subsets": len(scores),
    }


def answer_agreement(job_dir: Path) -> dict | None:
    """How much the attempts on a task agree with each other, independent
    of whether they are right: the share of tasks answered identically
    every time, the mean number of distinct answers per task, and the
    share of tasks whose plurality winner drew no more than two votes.

    The last one is the honesty check on majority voting -- a "majority"
    resting on 2 of 5 votes is a thin plurality, and reporting how often
    that happens keeps the vote from being oversold. It is measured
    against the votes actually cast on that task rather than a fixed
    threshold, so it stays meaningful for jobs with a different number of
    attempts (at one attempt per task nothing is thin: the lone answer is
    a strict majority of one)."""
    by_task = answers_by_task(job_dir)
    if not by_task:
        return None
    counts = [Counter(answer for answer, _ in pairs) for pairs in by_task.values()]
    return {
        "unanimous": sum(1 for c in counts if len(c) == 1) / len(counts) * 100,
        "mean_distinct": sum(len(c) for c in counts) / len(counts),
        "thin_plurality": sum(1 for c in counts if 2 * c.most_common(1)[0][1] <= sum(c.values()))
        / len(counts)
        * 100,
    }


def round_scores(job_dir: Path) -> list[float]:
    """The job's per-round benchmark scores, as percentages.

    Running every task R times is the same as running the whole exam R
    times: round r grades each task on its r-th attempt, so the spread of
    s_1..s_R is how much the score moves on a rerun. Attempts are ordered
    by each trial's started_at, which is the only place the ordering
    survives -- see task_outcomes' warning.

    R is the *minimum* attempts any task has, so a task with extra
    attempts contributes its earliest R and no round is left ragged.
    A trial with no reward file (errored, timed out) scores 0, matching
    task_outcomes."""
    valid = trial_names(job_dir)
    by_task: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for trial_result_path in job_dir.glob("*/result.json"):
        trial_dir = trial_result_path.parent
        if trial_dir.name not in valid:
            continue
        started_at = json.loads(trial_result_path.read_text()).get("started_at")
        if not started_at:
            continue
        reward = trial_reward(trial_dir)
        by_task[trial_dir.name.split("__")[0]].append((started_at, reward))
    if not by_task:
        return []
    ordered = {task: [r for _, r in sorted(attempts)] for task, attempts in by_task.items()}
    rounds = min(len(attempts) for attempts in ordered.values())
    return [
        sum(attempts[r] for attempts in ordered.values()) / len(ordered) * 100
        for r in range(rounds)
    ]


def run_to_run_ci(job_dir: Path) -> dict | None:
    """95% run-to-run interval: mean +/- 1.96 * SE, SE = std(s_1..s_R)/sqrt(R).

    The Terminal-Bench / DeepSWE convention, adopted here for comparability
    with how agent benchmarks report uncertainty. It answers "how much does
    the score move if the same exam is rerun", holding the question set
    fixed -- which is the right question here, since the 101 are the exam's
    complete set of distinct items rather than a sample from a larger pool
    (data/exam/dedup_keep_list.txt collapses pure number-substitution
    variants, it does not subsample).

    The interval is centred on summarize()'s avg. On every current job
    that equals the mean of the round scores, since each task has exactly
    R attempts; they would differ only if a task had more attempts than
    the R rounds can hold, or a trial with no started_at. `round_mean` is
    returned alongside so any such gap stays visible.

    None when the job has fewer than two rounds -- a single-attempt job has
    no rerun spread to report."""
    scores = round_scores(job_dir)
    if len(scores) < 2:
        return None
    centre = summarize(job_dir)["avg"]
    se = statistics.stdev(scores) / math.sqrt(len(scores))
    return {
        "mean": centre,
        "round_mean": sum(scores) / len(scores),
        "se": se,
        "lo": centre - 1.96 * se,
        "hi": centre + 1.96 * se,
        "rounds": len(scores),
    }


def round_se(job_dir: Path, value_of, statistic=statistics.mean) -> float | None:
    """Run-to-run standard error of a per-question quantity, the counterpart
    of run_to_run_ci's SE for anything measured per trial.

    Rounds are built the way round_scores builds them: attempt r of every
    task is round r, ordered by started_at, R the minimum attempts any task
    has. Each round's value is `statistic` (the mean, or the median where a
    figure plots the median) of value_of(trial_dir, trial) over its
    questions; SE = std(rounds)/sqrt(R). Only the width comes from the
    rounds -- the point estimate stays the figure's own statistic over every
    trial, which can differ slightly where a trial has no recoverable round
    position.

    A trial whose value cannot be read (value_of returns None) is left out
    of its round rather than counted as zero. None when fewer than two
    rounds survive."""
    valid = trial_names(job_dir)
    by_task: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for trial_result_path in job_dir.glob("*/result.json"):
        trial_dir = trial_result_path.parent
        if trial_dir.name not in valid:
            continue
        trial = json.loads(trial_result_path.read_text())
        started_at = trial.get("started_at")
        value = value_of(trial_dir, trial)
        if not started_at or value is None:
            continue
        by_task[trial_dir.name.split("__")[0]].append((started_at, value))
    if not by_task:
        return None
    ordered = [[value for _, value in sorted(attempts)] for attempts in by_task.values()]
    rounds = min(len(attempts) for attempts in ordered)
    if rounds < 2:
        return None
    per_round = [statistic(attempts[r] for attempts in ordered) for r in range(rounds)]
    return statistics.stdev(per_round) / math.sqrt(rounds)


def token_run_to_run_se(job_dir: Path, model: str) -> float | None:
    """Run-to-run SE of total tokens per question (input + cache write +
    cache read + output), the width of Figure 2's token whiskers."""
    def total_tokens(trial_dir: Path, _trial: dict) -> float | None:
        usage = usage_for(trial_dir, model)
        if usage is None:
            return None
        return sum(usage[k] for k in ("input", "cache_write", "cache_read", "output"))
    return round_se(job_dir, total_tokens)


def usd_run_to_run_se(job_dir: Path, model: str) -> float | None:
    """Run-to-run SE of mean USD per question. None for a self-hosted run,
    which has no per-token price, rather than a spread around zero."""
    def usd(trial_dir: Path, _trial: dict) -> float | None:
        usage = usage_for(trial_dir, model)
        return usage["cost"] if usage and usage["cost"] else None
    return round_se(job_dir, usd)


def agent_seconds(trial: dict) -> float | None:
    """Agent wall-clock seconds for one trial, as timing() measures it."""
    execution = trial.get("agent_execution") or {}
    started_at, finished_at = execution.get("started_at"), execution.get("finished_at")
    if not started_at or not finished_at:
        return None
    seconds = (
        datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    ).total_seconds()
    return seconds if seconds > 0 else None


def seconds_run_to_run_se(job_dir: Path) -> float | None:
    """Run-to-run SE of mean agent seconds per question. The mean, like cost
    and tokens, because it is what adds up to the time a batch of questions
    takes; the self-hosted models' long tail of slow trials is part of that
    time (their mean is 1.5-1.7x their median, the hosted APIs' 1.0-1.2x)."""
    return round_se(job_dir, lambda _dir, trial: agent_seconds(trial))


def summarize(job_dir: Path) -> dict:
    outcomes_by_task = task_outcomes(job_dir)

    all_outcomes = [outcome for outcomes in outcomes_by_task.values() for outcome in outcomes]
    avg = sum(all_outcomes) / len(all_outcomes) * 100
    n = min(len(outcomes) for outcomes in outcomes_by_task.values())

    pass_at = {
        k: sum(pass_at_k(n, sum(outcomes), k) for outcomes in outcomes_by_task.values())
        / len(outcomes_by_task)
        * 100
        for k in K_VALUES
        if k <= n
    }

    return {"avg": avg, "n": n, "n_tasks": len(outcomes_by_task), "pass_at": pass_at}


def trial_reward(trial_dir: Path) -> int:
    """0/1 for one trial: the exam key's verdict, as the verifier wrote it."""
    reward_path = trial_dir / "verifier" / "reward.txt"
    return int(float(reward_path.read_text().strip())) if reward_path.exists() else 0


# --- Per-trial usage extraction --------------------------------------------
#
# Harbor's own per-trial result.json (agent_result.n_input_tokens/
# n_cache_tokens/n_output_tokens) is NOT safe to sum directly: for both
# claude-code and opencode, n_input_tokens is already the *full* prompt
# total (fresh input + cache-read + cache-write folded in), and
# n_cache_tokens is just the cache-read portion *again*, as an informational
# subset -- not additive. Adding n_input + n_cache double-counts cache-read.
# Confirmed directly against the raw per-trial logs (see below); this is why
# usage is parsed from the raw agent logs here instead of trusting the
# harbor-aggregated fields.
#
# claude-code's own `total_cost_usd` is NOT trusted as the $ figure: Claude
# Code CLI 2.1.208 computes it for both Opus 5 and Sonnet 5 from one stale
# local rate table ($3 input / $6 1h-cache-write / $0.30 cache-read / $15
# output) regardless of which model ran. $ for every claude-code model is
# therefore computed here from PUBLISHED_RATES x real token counts.
#
# Each usage dict has four token buckets, deliberately non-overlapping so
# they sum to the whole prompt plus completion:
#   "input"       fresh input tokens -- neither served from cache nor written
#                 to it. Tiny for claude-code (tens of tokens per trial), since
#                 the cached prefix covers essentially the entire prompt.
#   "cache_write" tokens written to the cache for reuse by later turns, billed
#                 at a premium over base input (2x for the 1h TTL). This is
#                 99.6-99.9% of everything freshly processed in every
#                 claude-code run here, and exactly 0 in every opencode run.
#   "cache_read"  tokens served from a previous turn's cache, billed at a
#                 steep discount -- 10% of the base input rate for every
#                 claude-code model here except Opus 5.5, which is 5%
#                 (see PUBLISHED_RATES).
#   "output"      completion tokens (+ opencode's separately-logged
#                 "reasoning" tokens, which its aggregated n_output_tokens
#                 excludes)
#

# Published per-model rates ($/Mtok), from
# https://platform.claude.com/docs/en/about-claude/pricing. All Sonnet 5 runs
# here fall within its introductory pricing period. write_5m is tracked for
# completeness, but every claude-code trial used only the 1h ephemeral cache.
# A claude-code model missing from this table silently vanishes from the
# cost figures (usage_for() routes it to the opencode parser, which finds
# nothing), so add the rates when you add a model.
PUBLISHED_RATES: dict[str, dict[str, float]] = {
    "Opus 5": {"base_input": 5, "write_5m": 6.25, "write_1h": 10, "cache_read": 0.5, "output": 25},
    "Opus 5.5": {"base_input": 4, "write_5m": 5, "write_1h": 8, "cache_read": 0.2, "output": 20},
    "Sonnet 5": {"base_input": 2, "write_5m": 2.5, "write_1h": 4, "cache_read": 0.2, "output": 10},
    "Sonnet 5.5": {"base_input": 2, "write_5m": 2.5, "write_1h": 4, "cache_read": 0.2, "output": 10},
    "Opus 4.5": {"base_input": 5, "write_5m": 6.25, "write_1h": 10, "cache_read": 0.5, "output": 25},
    "Sonnet 4.5": {"base_input": 3, "write_5m": 3.75, "write_1h": 6, "cache_read": 0.3, "output": 15},
}


def claude_code_usage(trial_dir: Path, model: str) -> dict | None:
    """Parse Claude Code's own stream-json log for the final `result`
    event's whole-trial token usage, then compute $ from PUBLISHED_RATES
    (see module-level comment for why total_cost_usd itself isn't used)."""
    log_path = trial_dir / "agent" / "claude-code.txt"
    if not log_path.exists():
        return None
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            usage = event.get("usage") or {}
            if not usage:
                return None
            cache_creation = usage.get("cache_creation") or {}
            base_input = usage.get("input_tokens") or 0
            write_5m = cache_creation.get("ephemeral_5m_input_tokens", 0) or 0
            write_1h = cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
            cache_read = usage.get("cache_read_input_tokens") or 0
            output = usage.get("output_tokens") or 0
            rates = PUBLISHED_RATES[model]
            cost = (
                base_input * rates["base_input"]
                + write_5m * rates["write_5m"]
                + write_1h * rates["write_1h"]
                + cache_read * rates["cache_read"]
                + output * rates["output"]
            ) / 1e6
            return {
                "input": base_input,
                "cache_write": write_5m + write_1h,
                "cache_read": cache_read,
                "output": output,
                "cost": cost,
            }
    return None


def opencode_usage(trial_dir: Path) -> dict | None:
    """Parse opencode's raw step_finish event log. Unlike claude-code,
    opencode's tokens.{input,output,reasoning,cache.{read,write}} fields
    are genuinely orthogonal (they sum to tokens.total, confirmed) -- but
    cache-write tokens aren't in any harbor-aggregated field at all, only
    here, so they'd otherwise go uncounted entirely. Its `cost` field is 0
    for the self-hosted models here."""
    log_path = trial_dir / "agent" / "opencode.txt"
    if not log_path.exists():
        return None
    input_tokens = cache_write = cache_read = output_tokens = 0
    total_cost = 0.0
    seen = False
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "step_finish":
            continue
        part = event.get("part", {})
        tokens = part.get("tokens") or {}
        cache = tokens.get("cache") or {}
        input_tokens += tokens.get("input", 0) or 0
        cache_write += cache.get("write", 0) or 0
        cache_read += cache.get("read", 0) or 0
        output_tokens += (tokens.get("output", 0) or 0) + (tokens.get("reasoning", 0) or 0)
        total_cost += part.get("cost", 0) or 0
        seen = True
    if not seen:
        return None
    return {
        "input": input_tokens,
        "cache_write": cache_write,
        "cache_read": cache_read,
        "output": output_tokens,
        "cost": total_cost,
    }


# GPT-6 published API rates (developers.openai.com, 2026-09-23). These runs
# were billed to a ChatGPT subscription rather than metered per token, so the
# USD figure is what the same work WOULD cost on the API -- comparable with
# the Anthropic rows, but not an amount anyone was charged. Cache-write is
# priced separately by OpenAI but never appears in harbor's aggregated
# counters, so it is folded into base input.
CODEX_RATES: dict[str, dict[str, float]] = {
    "GPT-6 Luna": {"base_input": 0.10, "cache_read": 0.01, "output": 0.50},
    "GPT-6 Sol": {"base_input": 2.00, "cache_read": 0.20, "output": 10.00},
}


def codex_usage(trial_dir: Path, model: str) -> dict | None:
    """Token usage for a codex-agent trial, from harbor's own aggregated
    counters in result.json.

    Unlike claude-code and opencode there is no per-step token log to parse:
    codex.txt is the CLI's own event stream and does not carry a trial total.
    harbor's agent_result does (n_input_tokens includes the cached portion,
    with n_cache_tokens the part of it that was a cache read), so that is
    what is read here."""
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        return None
    agent_result = json.loads(result_path.read_text()).get("agent_result") or {}
    if agent_result.get("n_input_tokens") is None:
        return None
    total_input = agent_result.get("n_input_tokens") or 0
    cache_read = agent_result.get("n_cache_tokens") or 0
    output = agent_result.get("n_output_tokens") or 0
    rates = CODEX_RATES.get(model)
    cost = None
    if rates:
        cost = (
            max(total_input - cache_read, 0) / 1e6 * rates["base_input"]
            + cache_read / 1e6 * rates["cache_read"]
            + output / 1e6 * rates["output"]
        )
    return {
        "input": max(total_input - cache_read, 0),
        "cache_write": 0,
        "cache_read": cache_read,
        "output": output,
        "cost": cost if cost is not None else 0.0,
    }


def usage_for(trial_dir: Path, model: str) -> dict | None:
    """Dispatch to whichever agent's usage reader fits this trial."""
    if model in PUBLISHED_RATES:
        return claude_code_usage(trial_dir, model)
    if (trial_dir / "agent" / "codex.txt").exists():
        return codex_usage(trial_dir, model)
    return opencode_usage(trial_dir)


def trial_usages(job_dir: Path, model: str) -> list[dict]:
    """Per-trial token/cost usage for the trials this job actually consists
    of -- filtered through trial_names() for the same reason
    answers_by_task() is: a narrowed-then-resumed job can leave the dropped
    tasks' directories on disk."""
    valid = trial_names(job_dir)
    usages = []
    for trial_dir in job_dir.glob("*"):
        if trial_dir.name not in valid:
            continue
        if not (trial_dir / "result.json").exists():
            continue
        usage = usage_for(trial_dir, model)
        if usage is not None:
            usages.append(usage)
    return usages


# What the agent actually did, per attempt. The token columns say what an
# attempt cost; this says what it did to run that bill up -- a guidelines
# attempt greps and reads its way through ~300 pages of PDF-derived text, a
# closed-book one has nothing to read and only writes its answer.
#
# Both harnesses log every call, but in different shapes: claude-code's
# stream-json carries `tool_use` content blocks inside its `assistant`
# events, opencode emits a top-level `{"type": "tool_use"}` event per call.
# Names differ only in case between them (Bash/bash, Read/read), so they are
# lowercased into one vocabulary. Only the call is counted, not whether it
# succeeded: a failed grep still cost a turn and its tokens.
#
# A tool call is counted once per block, so one assistant message asking for
# three tools counts three -- that is three tool results coming back and
# three things the agent did, even though it was one turn.
#
# Each call is kept as (tool name, shell command), the command empty for
# everything but bash, because the tool name alone does not say what the
# agent did. Counting by tool name makes the models incomparable: Opus 5 and
# Sonnet 5 run their searching and reading through bash where Opus 4.5
# calls the dedicated grep/read tools, so an identical search shows
# up in a different column depending on the model's idiom. call_action()
# below puts both on one axis.


def claude_code_tool_calls(trial_dir: Path) -> list[tuple[str, str]] | None:
    """Every tool call one claude-code attempt made, in order, as
    (lowercased tool name, bash command), or None when the log is missing.

    Sidechain events (`parent_tool_use_id` set) would double-count a
    subagent's own calls under the parent, but the eval denies Task/Workflow
    outright (run_eval.py's disallowed_tools), so none appear; the filter is
    kept so that stays true if an agent is ever given them."""
    log_path = trial_dir / "agent" / "claude-code.txt"
    if not log_path.exists():
        return None
    calls = []
    for line in log_path.open(errors="replace"):
        line = line.strip()
        # The bulk of this file is tool *results*, some of them megabytes of
        # guidelines text. Skipping any line that can't hold a tool_use block
        # before paying for json.loads keeps a full rebuild to minutes.
        if not line.startswith("{") or '"tool_use"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant" or event.get("parent_tool_use_id"):
            continue
        for block in event.get("message", {}).get("content", []) or []:
            if block.get("type") == "tool_use" and block.get("name"):
                command = (block.get("input") or {}).get("command") or ""
                calls.append((block["name"].lower(), command))
    return calls


def opencode_tool_calls(trial_dir: Path) -> list[tuple[str, str]] | None:
    """Every tool call one opencode attempt made, in order, as (lowercased
    tool name, bash command), or None when the log is missing."""
    log_path = trial_dir / "agent" / "opencode.txt"
    if not log_path.exists():
        return None
    calls = []
    for line in log_path.open(errors="replace"):
        line = line.strip()
        if not line.startswith("{") or '"tool_use"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        name = part.get("tool")
        if name:
            command = ((part.get("state") or {}).get("input") or {}).get("command") or ""
            calls.append((name.lower(), command))
    return calls


# Codex's exec argument is a JavaScript snippet, not a bare command: the
# shell it actually runs is nested in a tools.exec_command({cmd:"..."}) call.
# Extracting it is what lets a codex run be compared with the others at all --
# fed the raw snippet, shell_action() would see JavaScript and file every
# call under "other". Escaped quotes inside the command are common (rg
# patterns), hence the backslash-aware body.
_CODEX_CMD = re.compile(r'cmd:\s*"((?:[^"\\]|\\.)*)"')
# The JS API calls that are not exec_command. Measured over the 4,183 codex
# tool calls in the GPT-6 runs: 4,078 (97.5%) carry a cmd:"...", and the 105
# that do not are these -- view_image, plus the model grepping its own
# ALL_TOOLS list looking for an image reader. They are real calls doing real
# work, not parse failures, so they are mapped rather than dropped.
_CODEX_JS_ACTIONS = [("tools.view_image", "read"), ("ALL_TOOLS", "other")]


def codex_tool_calls(trial_dir: Path) -> list[tuple[str, str]] | None:
    """Every tool call one codex attempt made, as (tool name, shell command).

    Read from the ATIF trajectory rather than an agent log: codex.txt is the
    CLI's own event stream and carries no per-call record this can use.

    Codex exposes ONE tool (`exec`, its unified-exec sandbox) where
    claude-code exposes Bash/Read/Grep/Glob/Write, so the by-tool columns
    cannot mean the same thing for it. The shell it runs is reported as
    "bash", which is what it is, and that routes call_action() to
    shell_action() -- so the action axis, the one the table actually
    compares models on, lands correctly."""
    trajectory_path = trial_dir / "agent" / "trajectory.json"
    if not trajectory_path.exists():
        return None
    try:
        trajectory = json.loads(trajectory_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    calls: list[tuple[str, str]] = []
    for step in trajectory.get("steps") or []:
        for tool_call in step.get("tool_calls") or []:
            argument = (tool_call.get("arguments") or {}).get("input") or ""
            match = _CODEX_CMD.search(argument)
            if match:
                command = match.group(1).encode().decode("unicode_escape", "replace")
                calls.append(("bash", command))
                continue
            for needle, action in _CODEX_JS_ACTIONS:
                if needle in argument:
                    calls.append((f"codex_{action}", ""))
                    break
            else:
                calls.append(("other", ""))
    return calls


def tool_call_reader(job_dir: Path, model: str):
    """The per-trial tool-call parser for this job's agent: claude-code for a
    model with published Anthropic rates, codex for a codex job, opencode
    otherwise."""
    if model in PUBLISHED_RATES:
        return claude_code_tool_calls
    config = job_dir / "config.json"
    if config.exists() and "codex" in json.loads(config.read_text()).get("agents", [{}])[0].get("name", ""):
        return codex_tool_calls
    return opencode_tool_calls


def trial_tool_calls(job_dir: Path, model: str) -> list[list[tuple[str, str]]]:
    """One list of (tool name, shell command) calls per attempt, for the
    trials this job actually consists of -- filtered through trial_names()
    for the same reason trial_usages() is.

    An attempt that made no tool call at all is a real, meaningful zero
    (qwen3.6:35b-a3b sometimes answers in prose and never calls write; see
    run_eval.py), so an empty list is kept in the result. Only an attempt
    with no agent log on disk is dropped, since that is a missing
    measurement rather than a measured zero."""
    valid = trial_names(job_dir)
    reader = tool_call_reader(job_dir, model)
    per_trial = []
    for trial_dir in job_dir.glob("*"):
        if trial_dir.name not in valid or not (trial_dir / "result.json").exists():
            continue
        calls = reader(trial_dir)
        if calls is not None:
            per_trial.append(calls)
    return per_trial


# --- What a call was for -------------------------------------------------
#
# Every call is put on one axis of five actions, so that a model that greps
# through bash and one that calls the grep tool land in the same column and
# can actually be compared. The axis is the work the exam asks for: find the
# relevant passage (search), read it (read), see what documents exist
# (list), do the arithmetic a criterion needs (compute), and write the
# answer file (answer).
#
# Only bash needs classifying; the dedicated tools say what they are.
TOOL_ACTIONS = {
    # Synthetic names from codex_tool_calls for its non-shell JS API calls,
    # which have no shell command to classify.
    "codex_read": "read",
    "codex_other": "other",
    "grep": "search",
    "read": "read",
    "glob": "list",
    # An attempt's whole job is to produce /output/answer.txt, and these are
    # the only two tools that write anything.
    "write": "answer",
    "edit": "answer",
}

# Shell utilities by what the agent was doing with them. Checked in the
# priority order of shell_action() below, not as a partition: a real command
# is a pipeline, and `grep -n ... | head -60` is a search whose `head` is a
# pager, not a read.
SHELL_SEARCH = {"grep", "egrep", "fgrep", "rg", "ag", "awk"}
SHELL_READ = {"cat", "sed", "head", "tail", "less", "more", "nl", "strings"}
SHELL_LIST = {"ls", "find", "tree", "du", "stat", "file", "wc"}
# The exam's reduction-rate questions are arithmetic, and some models shell
# out rather than do it in their heads. Invisible in a by-tool-name count,
# which sees only "bash".
SHELL_COMPUTE = {"python3", "python", "bc", "perl", "expr"}
# Writing the answer file, or making the directory to write it into.
SHELL_WRITE = {"mkdir", "touch", "printf", "echo", "tee", "cp", "mv"}
# Run another command; look through them to what they actually run, so
# `timeout 30 sed -n ...` reads as the sed it is.
SHELL_WRAPPERS = {"timeout", "nice", "time", "env", "xargs", "sudo", "nohup", "stdbuf"}

ANSWER_FILE = re.compile(r"answer\.txt")
# Split a command into its pipeline/list segments. Crude on purpose -- this
# only has to find the head of each segment, not parse shell.
SHELL_SEGMENTS = re.compile(r"[|;&]+|\$\(|\)|`|\n")
# A heredoc body is data, not commands: `python3 <<'EOF' ... EOF` would
# otherwise have its script read as a pipeline of shell.
HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?.*?^\1", re.S | re.M)
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def shell_heads(command: str) -> list[str]:
    """The utility at the head of each segment of a shell command, in order,
    with heredoc bodies and quoted strings removed first so their contents
    don't read as commands (a grep pattern is not a program)."""
    text = QUOTED.sub(" ", HEREDOC.sub(" ", command))
    heads = []
    for segment in SHELL_SEGMENTS.split(text):
        for token in segment.split():
            if token.startswith(("-", "(")) or "=" in token:
                continue
            name = token.rsplit("/", 1)[-1]
            # Skip a wrapper and its own numeric arguments (timeout's
            # seconds) to reach the command it runs.
            if name in SHELL_WRAPPERS or name.replace(".", "").isdigit():
                continue
            heads.append(name)
            break
    return heads


def shell_action(command: str) -> str:
    """What a bash command was for, on the same axis as TOOL_ACTIONS.

    Order matters, because a real command is a pipeline that does several
    things. Writing the answer file wins outright -- that is the attempt's
    whole purpose, and the write is usually chained onto whatever produced
    it (`mkdir -p /output && printf 'C\n' > /output/answer.txt && cat ...`).
    Compute comes next: when a model shells out to python it is the point of
    the command, even after a `cd`.

    Otherwise the FIRST recognised utility decides, not a global priority
    over all of them -- the head of a pipeline is what the command set out
    to do and the rest is presentation. `ls -R /guidelines | head -50` is a
    listing whose `head` is a pager, and a global priority that ranked read
    above list would score it as a read.

    Checked against the whole corpus: 23 of 26,252 commands fall through to
    "other", so the axis is close to total. Nearly all of those 23 are curl
    probes, plus a handful of `true`, `cd` and `which`."""
    if ANSWER_FILE.search(command):
        return "answer"
    heads = shell_heads(command)
    if set(heads) & SHELL_COMPUTE:
        return "compute"
    for name in heads:
        for action, utilities in (
            ("search", SHELL_SEARCH),
            ("read", SHELL_READ),
            ("list", SHELL_LIST),
            # A bare `mkdir -p /output` with no redirect yet: still the
            # agent setting up to write its answer.
            ("answer", SHELL_WRITE),
        ):
            if name in utilities:
                return action
    return "other"


def call_action(name: str, command: str) -> str:
    """The action one (tool name, shell command) call performed."""
    return shell_action(command) if name == "bash" else TOOL_ACTIONS.get(name, "other")


def dollar_rates(model: str) -> dict | None:
    """Per-token-type $/Mtok (new / cache_read / output).

    For claude-code models these are PUBLISHED_RATES directly, one bucket
    one rate -- no cross-bucket blending, which is the point of having split
    input from cache_write. The only blend left is within cache_write, over
    the 5m and 1h TTLs by this model's actual mix; every trial checked used
    the 1h cache exclusively, so in practice it returns write_1h, but the
    blend is kept so a future 5m-cached run is priced correctly rather than
    silently at the 1h rate.

    For codex models these are CODEX_RATES, with no cache-write rate (see
    there). None for the self-hosted opencode models, which have no per-token
    price."""
    if model in CODEX_RATES:
        rates = CODEX_RATES[model]
        return {"input": rates["base_input"], "cache_write": None, "cache_read": rates["cache_read"], "output": rates["output"]}
    if model in PUBLISHED_RATES:
        rates = PUBLISHED_RATES[model]
        total_write_5m = total_write_1h = 0
        for (m, _), d in JOBS.items():
            if m != model:
                continue
            for trial_dir in (REPO_DIR / d).glob("*"):
                if not (trial_dir / "result.json").exists():
                    continue
                log_path = trial_dir / "agent" / "claude-code.txt"
                if not log_path.exists():
                    continue
                for line in log_path.read_text().splitlines():
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "result":
                        usage = event.get("usage") or {}
                        cache_creation = usage.get("cache_creation") or {}
                        total_write_5m += cache_creation.get("ephemeral_5m_input_tokens", 0) or 0
                        total_write_1h += cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
        total_write = total_write_5m + total_write_1h
        write_rate = (
            (total_write_5m * rates["write_5m"] + total_write_1h * rates["write_1h"]) / total_write
            if total_write else rates["write_1h"]
        )
        return {
            "input": rates["base_input"],
            "cache_write": write_rate,
            "cache_read": rates["cache_read"],
            "output": rates["output"],
        }
    return None


def cost_and_tokens(job_dir: Path, model: str) -> dict | None:
    """Per-condition token volume (mean new/cache_read/output per trial)
    and $ cost (mean + median, reported as both since cost is heavily
    right-skewed by a long tail of expensive trials)."""
    usages = trial_usages(job_dir, model)
    if not usages:
        return None
    costs = [u["cost"] for u in usages if u["cost"]]
    return {
        "input": sum(u["input"] for u in usages) / len(usages),
        "cache_write": sum(u["cache_write"] for u in usages) / len(usages),
        "cache_read": sum(u["cache_read"] for u in usages) / len(usages),
        "output": sum(u["output"] for u in usages) / len(usages),
        "cost": {"mean": sum(costs) / len(costs), "median": statistics.median(costs)} if costs else None,
    }


def timing(job_dir: Path) -> dict | None:
    """Effective agent throughput (output tok/s, including opencode's
    separately-logged reasoning tokens) plus mean/median agent wall-clock
    time per task, from agent_execution.started_at/finished_at -- pure
    agent time, excluding environment/verifier overhead."""
    durations = []
    total_tokens = 0
    total_seconds = 0.0
    valid = trial_names(job_dir)
    for trial_result_path in job_dir.glob("*/result.json"):
        if trial_result_path.parent.name not in valid:
            continue
        trial = json.loads(trial_result_path.read_text())
        agent_execution = trial.get("agent_execution") or {}
        agent_result = trial.get("agent_result") or {}
        started_at = agent_execution.get("started_at")
        finished_at = agent_execution.get("finished_at")
        output_tokens = agent_result.get("n_output_tokens")
        if not started_at or not finished_at:
            continue
        duration = (
            datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        ).total_seconds()
        if duration <= 0:
            continue
        durations.append(duration)
        if output_tokens:
            total_tokens += output_tokens + opencode_reasoning_tokens(trial_result_path.parent)
            total_seconds += duration
    if not durations:
        return None
    return {
        "tok_s": total_tokens / total_seconds if total_seconds else None,
        "mean_seconds": sum(durations) / len(durations),
        "median_seconds": statistics.median(durations),
    }


def opencode_reasoning_tokens(trial_dir: Path) -> int:
    """opencode splits "reasoning" tokens into a separate field in its raw
    event log that agent_result.n_output_tokens doesn't include --
    claude-code has no equivalent gap. Skipping it would undercount
    generated volume and make tok/s incomparable across harnesses."""
    log_path = trial_dir / "agent" / "opencode.txt"
    if not log_path.exists():
        return 0
    total = 0
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "step_finish":
            total += (event.get("part", {}).get("tokens") or {}).get("reasoning", 0)
    return total
