#!/usr/bin/env -S uv run
"""
Classify every attempt as correct or by kind of error into
data/figures/outcomes.csv, for the paper's error-type table.

One row per (model, condition, task, outcome) with its attempt count, the
question name, its type and whether it has an image. Submitted answers are
not written, since the exam is confidential. Errored trials count as wrong
attempts (metrics.task_outcomes).

Question types: category (a Red List category, possibly with criteria),
multi (multiple select), calculation (a number), matching, other (free text).

Outcomes (correct, then errors):
  correct                 the grader accepted the answer
  category_one_step       category wrong, one step away on CR-EN-VU-NT-LC
  category_further        category wrong by more, a non-threat category where a
                          threat category was due, or no leading category
  code_extra_subcriteria  right category and criterion, every accepted
                          subcriterion plus more
  code_extra_criteria     criteria added where the bare category was accepted
  code_subcriteria        right category and criterion, subcriteria wrong
  code_formatting         right code, differing only in spacing
  code_criterion          right category, wrong criterion
  code_missing            right category, required criteria left out
  multi_extra             multiple select: the correct options plus others
  multi_missed            multiple select: a correct option left out only
  multi_wrong             multiple select: any other wrong set
  matching                at least one pair wrong
  numeric                 a calculation with the wrong number
  no_answer               no answer file written (errors and timeouts included)
  other                   any other wrong free-text answer

Usage:
    python3 scripts/analysis/build_outcome_data.py
"""
from __future__ import annotations

import ast
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_DIR / "scripts" / "analysis"))

from build_question_data import question_names  # noqa: E402
from metrics import JOBS, trial_names, trial_reward  # noqa: E402


OUTPUT_PATH = REPO_DIR / "data" / "figures" / "outcomes.csv"
TASKS_DIR = REPO_DIR / "tasks" / "en"
COLUMNS = ["model", "condition", "task", "question", "question_type", "has_image", "outcome", "attempts"]

CATEGORY = re.compile(r"^(CR|EN|VU|NT|LC|DD|NE|EX|EW|RE|NA)\b\s*(.*)$")
THREAT_SCALE = ["CR", "EN", "VU", "NT", "LC"]


def load_grader(task: str) -> tuple[str, object]:
    """("string", [accepted...]), ("multi", {options}) or ("match", {item: option})."""
    source = (TASKS_DIR / task / "tests" / "test_outputs.py").read_text()
    match = re.search(r"EXPECTED\s*=\s*set\((\[.*?\])\)", source, re.S)
    if match:
        options = set(ast.literal_eval(match.group(1)))
        return "multi", options
    match = re.search(r"EXPECTED\s*=\s*(\{.*?\})", source, re.S)
    if match:
        return "match", ast.literal_eval(match.group(1))
    match = re.search(r"ACCEPTED\s*=\s*(\[.*?\])", source, re.S)
    if match:
        return "string", ast.literal_eval(match.group(1))
    raise SystemExit(f"{task}: unrecognised grader")


def split_code(text: str) -> tuple[str | None, str]:
    """"VU B1ab(iii)" -> ("VU", "B1AB(III)"): category, criteria without spaces."""
    match = CATEGORY.match(re.sub(r"\s+", " ", text.strip()).upper())
    if not match:
        return None, ""
    return match.group(1), re.sub(r"\s+", "", match.group(2))


def without_subcriteria(criteria: str) -> str:
    """"A2ABD" -> "A2", "B1AB(III)+2AB(III)" -> "B1+2": criterion letters and numbers only."""
    return re.sub(r"(?<=\d)[A-E]+", "", re.sub(r"\([^)]*\)", "", criteria))


PIECE = re.compile(r"([A-E])?(\d)([A-E]*)(?:\(([IVX,]+)\))?")


def subcriteria_tokens(criteria: str) -> set[str]:
    """"B1AB(II,III)" -> {"B1", "B1A", "B1B", "B1B(II)", "B1B(III)"}.

    One token per criterion, subcriterion letter and roman numeral, so two
    codes compare as sets. A piece without its letter ("+2AB(III)") takes the
    previous one's, and numerals attach to the last subcriterion letter."""
    tokens: set[str] = set()
    letter = ""
    for piece in re.split(r"[;+]", criteria):
        for prefix, digit, subs, numerals in PIECE.findall(piece):
            letter = prefix or letter
            base = f"{letter}{digit}"
            tokens.add(base)
            tokens.update(base + s for s in subs)
            if numerals and subs:
                tokens.update(f"{base}{subs[-1]}({n})" for n in numerals.split(","))
    return tokens


def extra_subcriteria(criteria: str, accepted: str) -> bool:
    """Same criterion as an accepted form, its subcriteria a strict superset."""
    if without_subcriteria(criteria) != without_subcriteria(accepted):
        return False
    given, wanted = subcriteria_tokens(criteria), subcriteria_tokens(accepted)
    return bool(wanted) and wanted < given


def classify_code(answer: str, accepted: list[str]) -> str:
    codes = [split_code(a) for a in accepted]
    category, criteria = split_code(answer)
    wanted = {c for c, _ in codes if c}
    if category is None:
        return "category_further"
    if category not in wanted:
        if category in THREAT_SCALE and wanted <= set(THREAT_SCALE):
            steps = min(abs(THREAT_SCALE.index(category) - THREAT_SCALE.index(w)) for w in wanted)
            return "category_one_step" if steps == 1 else "category_further"
        return "category_further"
    forms = [k for c, k in codes if c == category]
    if criteria in forms:
        return "code_formatting"
    if not criteria:
        return "code_missing"
    # Before the bare-category check: a code with an extra subcriterion, where
    # the key also accepts the bare category, has every subcriterion asked for
    # and more, which
    # is a different thing from criteria added to a bare category.
    if any(k and extra_subcriteria(criteria, k) for k in forms):
        return "code_extra_subcriteria"
    if "" in forms:
        # The bare category was an accepted answer; the criteria added are
        # not an accepted form, so the answer was over-specified.
        return "code_extra_criteria"
    if any(without_subcriteria(criteria) == without_subcriteria(k) for k in forms):
        return "code_subcriteria"
    return "code_criterion"


def question_type(task: str) -> str:
    kind, accepted = load_grader(task)
    if kind != "string":
        return {"multi": "multi", "match": "matching"}[kind]
    if any(split_code(a)[0] for a in accepted):
        return "category"
    if all(re.search(r"\d", a) for a in accepted):
        return "calculation"
    return "other"


def has_image(task: str) -> bool:
    return "/images/" in (TASKS_DIR / task / "instruction.md").read_text()


def key_category(task: str) -> str:
    """The correct category of a category question ("VU"), or "/"-joined if
    the accepted answers allow more than one."""
    _, accepted = load_grader(task)
    return "/".join(sorted({split_code(a)[0] for a in accepted if split_code(a)[0]}))


def answer_category(answer: str | None) -> str:
    if answer is None or not answer.strip():
        return "none"
    return split_code(answer)[0] or "other"


def classify(task: str, answer: str | None) -> str:
    kind, accepted = load_grader(task)
    if answer is None or not answer.strip():
        return "no_answer"
    if kind == "multi":
        given = {line.strip().upper() for line in answer.splitlines() if line.strip()}
        if accepted < given:
            return "multi_extra"
        if given < accepted:
            return "multi_missed"
        return "multi_wrong"
    if kind == "match":
        return "matching"
    if any(split_code(a)[0] for a in accepted):
        return classify_code(answer, accepted)
    if all(re.search(r"\d", a) for a in accepted):
        return "numeric"
    return "other"


def main() -> None:
    names = question_names()
    counts: dict[tuple, int] = defaultdict(int)
    types: dict[str, str] = {}
    images: dict[str, bool] = {}
    for (model, condition), job in JOBS.items():
        job_dir = REPO_DIR / job
        if not (job_dir / "result.json").exists():
            print(f"skipping {model} / {condition}: {job} not present", file=sys.stderr)
            continue
        for trial in sorted(trial_names(job_dir)):
            trial_dir = job_dir / trial
            task = trial.split("__")[0]
            if task not in types:
                types[task] = question_type(task)
                images[task] = has_image(task)
            answer_path = trial_dir / "artifacts" / "output" / "answer.txt"
            answer = answer_path.read_text() if answer_path.exists() else None
            correct = bool(trial_reward(trial_dir))
            outcome = "correct" if correct else classify(task, answer)
            counts[(model, condition, task, outcome)] += 1

    rows = [
        {"model": m, "condition": c, "task": t, "question": names.get(t, ""),
         "question_type": types[t], "has_image": int(images[t]), "outcome": o, "attempts": n}
        for (m, c, t, o), n in counts.items()
    ]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows ({sum(counts.values())} attempts) to {OUTPUT_PATH.relative_to(REPO_DIR)}")



if __name__ == "__main__":
    main()
