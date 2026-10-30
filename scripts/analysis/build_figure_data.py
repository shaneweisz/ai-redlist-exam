#!/usr/bin/env -S uv run
"""
Flatten the eval runs in runs/ into data/figures/results.csv, the small
committed CSV that the paper's figure and table scripts read.

One row per (model, condition) run: accuracy, pass@k / pass^k / majority
vote, agreement between attempts, latency, tokens and cost. All measurement
logic comes from metrics.py.

Usage:
    python3 scripts/analysis/build_figure_data.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_DIR / "scripts" / "analysis"))

from metrics import (  # noqa: E402
    HARNESS,
    JOBS,
    K_VALUES,
    answer_agreement,
    cost_and_tokens,
    dollar_rates,
    majority_vote_accuracy,
    majority_vote_at_k,
    pass_hat_summary,
    run_to_run_ci,
    seconds_run_to_run_se,
    token_run_to_run_se,
    usd_run_to_run_se,
    summarize,
    timing,
)

OUTPUT_PATH = REPO_DIR / "data" / "figures" / "results.csv"

COLUMNS = [
    "model",
    "harness",
    "condition",
    "job_dir",
    "n_tasks",
    "n_attempts",
    "accuracy_avg",
    # 95% run-to-run interval on accuracy_avg (Terminal-Bench / DeepSWE
    # convention): blank for single-attempt jobs, which have no rerun
    # spread. n_rounds is what the SE was computed over, and is not always
    # n_attempts -- see metrics.run_to_run_ci on ragged jobs.
    "n_rounds",
    "accuracy_se",
    "accuracy_ci_lo",
    "accuracy_ci_hi",
    *[f"pass_at_{k}" for k in K_VALUES],
    *[f"pass_hat_{k}" for k in K_VALUES],
    "majority_accuracy",
    # Majority vote over 3 of the 5 rounds, averaged over all 10 ways of
    # choosing them, with the spread across those choices (NOT a standard
    # error -- the subsets overlap; see metrics.majority_vote_at_k).
    "majority_accuracy_3",
    "majority_sd_3",
    "unanimous_pct",
    "mean_distinct_answers",
    "thin_plurality_pct",
    "tokens_per_sec",
    "mean_seconds_per_task",
    "median_seconds_per_task",
    # Run-to-run SE of mean_seconds_per_task (seconds_run_to_run_se),
    # Figure 2's time whiskers.
    "mean_seconds_se",
    # input and cache_write are separate because cache writes are billed at
    # a premium over the input rate (1.25x for the 5-minute TTL, 2x for 1h;
    # see metrics.PUBLISHED_RATES). They are
    # non-overlapping and sum, with cache_read and output, to
    # total_tokens_per_task.
    "input_tokens_per_task",
    "cache_write_tokens_per_task",
    "cache_read_tokens_per_task",
    "output_tokens_per_task",
    "total_tokens_per_task",
    # Run-to-run SE of total_tokens_per_task (token_run_to_run_se): the width
    # of Figure 2's token-saving whiskers. Blank for single-attempt jobs.
    "total_tokens_se",
    "mean_usd_per_task",
    # Run-to-run SE of mean_usd_per_task (usd_run_to_run_se), Figure 2's cost
    # whiskers. Blank for self-hosted runs, which have no price.
    "usd_se",
    "median_usd_per_task",
    "usd_per_mtok_input",
    "usd_per_mtok_cache_write",
    "usd_per_mtok_cache_read",
    "usd_per_mtok_output",
]


def rounded(value: float | None, digits: int) -> str:
    """Blank rather than 0 for genuinely absent measurements, so downstream
    scripts can tell "not measured" from "measured as zero" (local models
    really do cost $0; they don't have an unknown cost)."""
    return "" if value is None else f"{value:.{digits}f}"


def row_for(model: str, condition: str, job: str, rates: dict | None) -> dict:
    job_dir = REPO_DIR / job
    accuracy = summarize(job_dir)
    ci = run_to_run_ci(job_dir)
    pass_hat = pass_hat_summary(job_dir)
    agreement = answer_agreement(job_dir) or {}
    latency = timing(job_dir) or {}
    usage = cost_and_tokens(job_dir, model) or {}
    majority_3 = majority_vote_at_k(job_dir, 3) or {}
    cost = usage.get("cost") or {}
    is_local = "local" in HARNESS.get(model, "")

    row = {
        "model": model,
        "harness": HARNESS.get(model, ""),
        "condition": condition,
        "job_dir": job,
        "n_tasks": accuracy["n_tasks"],
        "n_attempts": accuracy["n"],
        "n_rounds": ci["rounds"] if ci else "",
        "accuracy_se": rounded(ci["se"] if ci else None, 3),
        "accuracy_ci_lo": rounded(ci["lo"] if ci else None, 2),
        "accuracy_ci_hi": rounded(ci["hi"] if ci else None, 2),
        "accuracy_avg": rounded(accuracy["avg"], 2),
        # Majority vote needs at least two attempts to mean anything; a
        # single-attempt job would otherwise report its own accuracy as a
        # "vote" and look identical to every other strategy.
        "majority_accuracy": rounded(majority_vote_accuracy(job_dir) if accuracy["n"] > 1 else None, 2),
        "majority_accuracy_3": rounded(majority_3.get("mean"), 2),
        "majority_sd_3": rounded(majority_3.get("sd"), 2),
        "unanimous_pct": rounded(agreement.get("unanimous"), 2),
        "mean_distinct_answers": rounded(agreement.get("mean_distinct"), 3),
        "thin_plurality_pct": rounded(agreement.get("thin_plurality"), 2),
        "tokens_per_sec": rounded(latency.get("tok_s"), 2),
        "mean_seconds_per_task": rounded(latency.get("mean_seconds"), 1),
        "median_seconds_per_task": rounded(latency.get("median_seconds"), 1),
        "mean_seconds_se": rounded(seconds_run_to_run_se(job_dir), 1),
        "input_tokens_per_task": rounded(usage.get("input"), 1),
        "cache_write_tokens_per_task": rounded(usage.get("cache_write"), 1),
        "cache_read_tokens_per_task": rounded(usage.get("cache_read"), 1),
        "output_tokens_per_task": rounded(usage.get("output"), 1),
        "total_tokens_per_task": rounded(
            sum(usage[k] for k in ("input", "cache_write", "cache_read", "output")) if usage else None, 1
        ),
        "total_tokens_se": rounded(token_run_to_run_se(job_dir, model), 1),
        # Local models are free by construction, not unmeasured -- record the
        # real 0.0 so the figures can plot them on the tokens axis while
        # correctly leaving them off the dollar axis.
        "mean_usd_per_task": rounded(cost.get("mean", 0.0 if is_local else None), 6),
        "usd_se": rounded(usd_run_to_run_se(job_dir, model), 6),
        "median_usd_per_task": rounded(cost.get("median", 0.0 if is_local else None), 6),
        "usd_per_mtok_input": rounded((rates or {}).get("input", 0.0 if is_local else None), 4),
        # Blank, not zero, when a harness wrote no cache tokens at all: there
        # is no rate to identify, which is not the same as a rate of zero.
        "usd_per_mtok_cache_write": rounded((rates or {}).get("cache_write", 0.0 if is_local else None), 4),
        "usd_per_mtok_cache_read": rounded((rates or {}).get("cache_read", 0.0 if is_local else None), 4),
        "usd_per_mtok_output": rounded((rates or {}).get("output", 0.0 if is_local else None), 4),
    }
    row |= {f"pass_at_{k}": rounded(accuracy["pass_at"].get(k), 2) for k in K_VALUES}
    row |= {f"pass_hat_{k}": rounded(pass_hat.get(k), 2) for k in K_VALUES}
    return row


def main() -> None:
    # runs/ is gitignored and archived to Harbor Hub, so any given machine may hold
    # only some of the jobs JOBS names. Summarize what is actually here and
    # say what was skipped, rather than failing outright -- the alternative
    # makes regenerating the CSV impossible until every run is downloaded.
    available = {key: job for key, job in JOBS.items() if (REPO_DIR / job / "result.json").exists()}
    for model, condition in JOBS.keys() - available.keys():
        print(f"skipping {model} / {condition}: {JOBS[(model, condition)]} not present", file=sys.stderr)

    # dollar_rates() re-parses every trial for a model, so resolve it once per
    # model rather than once per (model, condition).
    rates_by_model = {model: dollar_rates(model) for model in dict.fromkeys(m for m, _ in available)}

    rows = [row_for(model, condition, job, rates_by_model[model]) for (model, condition), job in available.items()]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUTPUT_PATH.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main()
