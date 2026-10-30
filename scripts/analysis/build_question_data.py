#!/usr/bin/env -S uv run
"""
Flatten the eval runs into data/figures/per_question.csv, for the paper's
topic-level table.

One row per (model, condition, question): attempts, correct attempts, the
question name and its category path in the exam's question bank, recorded
verbatim. Errored trials count as failed attempts (metrics.task_outcomes).

Usage:
    python3 scripts/analysis/build_question_data.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_DIR / "scripts" / "analysis"))

from metrics import JOBS, task_outcomes  # noqa: E402

OUTPUT_PATH = REPO_DIR / "data" / "figures" / "per_question.csv"
TASKS_DIR = REPO_DIR / "tasks" / "en"
QUESTIONS_DIR = REPO_DIR / "data" / "exam" / "parsed_questions"

COLUMNS = ["model", "condition", "task", "question", "category", "n_attempts", "n_correct"]

# The course's question bank nests every category under this prefix, so it
# says nothing about the question and is stripped.
CATEGORY_PREFIX = "$course$/top/Default for Final IUCN/"


def question_names() -> dict[str, str]:
    """Task id -> exam question name, from each task's task.toml description
    (generate_harbor_tasks.py writes "IUCN Red List Exam question: <name>")."""
    names = {}
    for toml in TASKS_DIR.glob("*/task.toml"):
        match = re.search(r'^description = "IUCN Red List Exam question: (.*)"$', toml.read_text(), re.M)
        if match:
            names[toml.parent.name] = match.group(1)
    return names


def categories() -> dict[str, str]:
    """Exam question name -> category path, prefix stripped."""
    paths = {}
    for path in QUESTIONS_DIR.glob("*.json"):
        question = json.loads(path.read_text())
        paths[question["name"]] = question.get("category", "").removeprefix(CATEGORY_PREFIX)
    return paths


def main() -> None:
    names = question_names()
    category_of = categories()

    # Same tolerance as build_figure_data.py: runs/ is gitignored and archived
    # to Harbor Hub, so summarize what this machine has and say what was skipped.
    rows = []
    for (model, condition), job in JOBS.items():
        job_dir = REPO_DIR / job
        if not (job_dir / "result.json").exists():
            print(f"skipping {model} / {condition}: {job} not present", file=sys.stderr)
            continue
        for task, outcomes in sorted(task_outcomes(job_dir).items()):
            question = names.get(task, "")
            rows.append({
                "model": model,
                "condition": condition,
                "task": task,
                "question": question,
                "category": category_of.get(question, ""),
                "n_attempts": len(outcomes),
                "n_correct": sum(outcomes),
            })

    missing = sorted({row["task"] for row in rows if not row["category"]})
    if missing:
        print(f"warning: no category for {len(missing)} task(s): {', '.join(missing)}", file=sys.stderr)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUTPUT_PATH.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main()
