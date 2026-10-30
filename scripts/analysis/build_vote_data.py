#!/usr/bin/env -S uv run
"""
Count how the five attempts at each question split into distinct answers,
into data/figures/votes.csv: the shape of the vote behind maj@5.

One row per (model, condition, vote shape), largest count first ("5"
unanimous, "4-1", "2-2-1" ...), with the number of questions of that shape
and how many the plurality answer got right. `tied` marks shapes whose top
count is shared; metrics.plurality_score scores those as the share of tied
answers that are correct, so `plurality_correct` can be fractional. Votes
compare exact answer text, and a missing answer votes as "no answer".

Usage:
    python3 scripts/analysis/build_vote_data.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_DIR / "scripts" / "analysis"))

from metrics import JOBS, answers_by_round, plurality_score  # noqa: E402

OUTPUT_PATH = REPO_DIR / "data" / "figures" / "votes.csv"
COLUMNS = ["model", "condition", "shape", "tied", "attempts", "questions", "plurality_correct"]


def shape_of(pairs: list[tuple[str, int]]) -> tuple[str, bool]:
    """("4-1", False): the vote counts largest first, and whether the top
    count is shared."""
    counts = sorted(Counter(answer for answer, _ in pairs).values(), reverse=True)
    return "-".join(str(count) for count in counts), counts.count(counts[0]) > 1


def main() -> None:
    questions: dict[tuple, int] = defaultdict(int)
    correct: dict[tuple, float] = defaultdict(float)
    attempts: dict[tuple[str, str], int] = {}
    for (model, condition), job in JOBS.items():
        job_dir = REPO_DIR / job
        if not (job_dir / "result.json").exists():
            print(f"skipping {model} / {condition}: {job} not present", file=sys.stderr)
            continue
        by_task = answers_by_round(job_dir)
        if not by_task:
            continue
        attempts[(model, condition)] = len(next(iter(by_task.values())))
        for pairs in by_task.values():
            shape, tied = shape_of(pairs)
            questions[(model, condition, shape, tied)] += 1
            correct[(model, condition, shape, tied)] += plurality_score(pairs)

    rows = [
        {"model": model, "condition": condition, "shape": shape, "tied": int(tied),
         "attempts": attempts[(model, condition)], "questions": n,
         "plurality_correct": f"{correct[(model, condition, shape, tied)]:.1f}"}
        for (model, condition, shape, tied), n in sorted(questions.items())
    ]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUTPUT_PATH.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main()
