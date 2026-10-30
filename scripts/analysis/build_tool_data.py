#!/usr/bin/env -S uv run
"""
Count each attempt's tool calls into data/figures/tools.csv, for the paper's
tool-use table.

One row per (model, condition): the distribution of tool calls over that
job's attempts, then the mean split two ways, by which tool was called and by
what the call did (metrics.call_action). The table reports the second split,
since models differ in whether they search and read through bash or through
dedicated tools. An attempt that called nothing counts as zero; only attempts
with no agent log on disk are dropped (n_attempts records how many were read).

Usage:
    python3 scripts/analysis/build_tool_data.py
"""
from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_DIR / "scripts" / "analysis"))

from metrics import HARNESS, JOBS, call_action, trial_tool_calls  # noqa: E402

OUTPUT_PATH = REPO_DIR / "data" / "figures" / "tools.csv"

# Bands of the per-attempt call count, as (csv key, low, high-inclusive);
# None is unbounded. Singletons at the bottom because that is where the
# closed-book rows live (93% of Opus 5.5's attempts make exactly one call)
# and bands above, because the guidelines rows run to a median of 11. Fixed
# small integers (0/1/2/3/4+) were tried first and pinned six of the eleven
# guidelines rows at 73% or more in the top band.
BUCKETS = [
    ("0", 0, 0),
    ("1", 1, 1),
    ("2", 2, 2),
    ("3_5", 3, 5),
    ("6_10", 6, 10),
    ("11plus", 11, None),
]

# The tools that get their own column. Everything else a run logged --
# edit, todowrite, toolsearch, and the occasional hallucinated name the
# harness rejected ("grag", "grail", "invalid") -- lands in `other`, which
# is a few calls in tens of thousands on every row. Named here rather than
# taken from the data so a new tool appearing in a future run shows up as a
# bump in `other` instead of silently widening the table.
NAMED_TOOLS = ["bash", "read", "grep", "glob", "write"]
TOOL_COLUMNS = [*NAMED_TOOLS, "other"]

# What the agent used those tools FOR (metrics.call_action). The
# by-tool columns above can't be compared across models -- Opus 5 runs its
# searching through bash where Opus 4.5 calls the grep tool -- so the table
# reports these instead, and keeps the by-tool columns here as the record of
# what was actually logged.
ACTIONS = ["search", "read", "list", "compute", "answer", "other"]

COLUMNS = [
    "model",
    "harness",
    "condition",
    "job_dir",
    "n_attempts",
    # The distribution over attempts. SD is the spread across attempts, NOT
    # a run-to-run standard error like results.csv's accuracy_se -- these
    # say how much one attempt differs from the next, which is the question
    # a reader asks of a tool-call count.
    "mean",
    "sd",
    "p25",
    "median",
    "p75",
    "max",
    # Share of attempts that called no tool at all. A real behaviour, not a
    # parse failure: an agent that never calls write leaves /output/answer.txt
    # empty and scores 0 however good its prose was. Equals bucket_0 below.
    "none_pct",
    # The same attempts as a distribution rather than as moments: the share
    # landing in each band of BUCKETS. A tool-call count is a small skewed
    # integer, so a mean and an SD describe it poorly -- these say what the
    # agents actually did, and show shape the moments hide (Opus 5.5 with the
    # guidelines is bimodal: 62% answer on one call, then a second lump at
    # 3-5).
    *[f"bucket_{key}" for key, _, _ in BUCKETS],
    # Mean calls per attempt of each tool, so the columns sum to `mean`.
    *[f"calls_{tool}" for tool in TOOL_COLUMNS],
    # The same calls by what they were for, so these sum to `mean` too.
    *[f"action_{action}" for action in ACTIONS],
]


def rounded(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def row_for(model: str, condition: str, job: str, per_trial: list[list[tuple[str, str]]]) -> dict:
    totals = [len(calls) for calls in per_trial]
    by_name: Counter = Counter()
    by_action: Counter = Counter()
    for calls in per_trial:
        for name, command in calls:
            by_name[name] += 1
            by_action[call_action(name, command)] += 1
    named = sum(by_name[tool] for tool in NAMED_TOOLS)
    by_tool = {tool: by_name[tool] for tool in NAMED_TOOLS} | {"other": sum(by_name.values()) - named}

    quartiles = statistics.quantiles(totals, n=4, method="inclusive")
    return {
        "model": model,
        "harness": HARNESS.get(model, ""),
        "condition": condition,
        "job_dir": job,
        "n_attempts": len(totals),
        "mean": rounded(statistics.fmean(totals), 2),
        # A one-attempt job has no spread; stdev would raise rather than
        # report that honestly.
        "sd": rounded(statistics.stdev(totals), 2) if len(totals) > 1 else "",
        "p25": rounded(quartiles[0], 1),
        "median": rounded(quartiles[1], 1),
        "p75": rounded(quartiles[2], 1),
        "max": max(totals),
        "none_pct": rounded(100 * sum(1 for total in totals if total == 0) / len(totals), 1),
    } | {
        f"bucket_{key}": rounded(
            100 * sum(1 for t in totals if t >= low and (high is None or t <= high))
            / len(totals), 1)
        for key, low, high in BUCKETS
    } | {
        f"calls_{tool}": rounded(count / len(totals), 2) for tool, count in by_tool.items()
    } | {
        f"action_{action}": rounded(by_action[action] / len(totals), 2) for action in ACTIONS
    }


def main() -> None:
    rows = []
    for (model, condition), job in JOBS.items():
        job_dir = REPO_DIR / job
        if not (job_dir / "result.json").exists():
            print(f"skipping {model} / {condition}: {job} not present", file=sys.stderr)
            continue
        per_trial = trial_tool_calls(job_dir, model)
        # trial_tool_calls picks its log parser the same way trial_usages
        # picks its token parser -- by whether the model has published
        # rates -- so a claude-code job under a model name that isn't in
        # that table reads as zero trials rather than as a parse error.
        if not per_trial:
            print(f"skipping {model} / {condition}: no agent logs parsed under {job}", file=sys.stderr)
            continue
        rows.append(row_for(model, condition, job, per_trial))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUTPUT_PATH.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main()
