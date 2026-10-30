#!/usr/bin/env python3
"""
Pick the deduplicated core set from data/exam/parsed_questions/*.json and
write its question names, one per line, to data/exam/dedup_keep_list.txt.
generate_harbor_tasks.py numbers these questions first (q001-q101).

Usage:
    python3 scripts/setup/dedup_questions.py [questions_dir]

Questions sharing a name family (`<name>_<N>`) are reduced to one per
distinct prompt "skeleton" (the prompt with numbers normalised away), and
population time-series are further split by whether they fit exponential
or linear decline (`population_trend_fit`). The result was corrected by a
manual audit (AUDIT_EXCLUDE): if the question set changes, re-audit rather
than trusting a re-run.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS_DIR = REPO_ROOT / "data" / "exam" / "parsed_questions"
OUTPUT_FILE = REPO_ROOT / "data" / "exam" / "dedup_keep_list.txt"

NUMBER_WORDS = (
    "one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty "
    "fifty sixty seventy eighty ninety hundred thousand".split()
)
NUM_WORD_RE = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
FAMILY_RE = re.compile(r"^(.*)_(\d+)$")
POP_SERIES_RE = re.compile(r"([\d,]+)\s+in\s+((?:19|20)\d{2})")

# Known false-positive splits found by the independent audit: these
# family members are pure-template duplicates of an already-kept
# representative, but differ in incidental phrasing the skeleton
# normalization doesn't catch (e.g. a grammar variant tied to the
# substituted count, not a substantive difference). Excluding them
# explicitly rather than generalizing the normalizer further, since fuzzy
# phrasing-invariant matching risks new, unvalidated false negatives
# elsewhere.
AUDIT_EXCLUDE = {"Loc_2", "Loc_3", "SevFrag_N_4", "SevFrag_N_7"}


def html_to_plain(html_text):
    return re.sub(r"<[^>]+>", " ", html_text)


def skeleton(prompt):
    p = html_to_plain(prompt)
    p = re.sub(r"[\d,]*\d(\.\d+)?\s*%?", "#", p)
    p = NUM_WORD_RE.sub("#", p)
    p = re.sub(r"#(\s*#)+", "#", p)
    p = re.sub(r"\s+", " ", p).strip().lower()
    p = re.sub(r"(#\s*\w+?)s\b", r"\1", p)
    p = re.sub(r"\s+", "", p)  # ignore all whitespace for grouping
    return p


def population_trend_fit(prompt):
    """Fit exponential vs. linear decline to a '<N> in <year>' population
    series embedded in the prompt. Returns 'exponential', 'linear', or
    None if fewer than 3 data points are found. A family whose members
    otherwise skeleton-match identically but split by fit-type here are
    testing a genuinely different calculation, not just substituted
    values (e.g. one variant per category)."""
    plain = re.sub(r"\s+", " ", html_to_plain(prompt))
    pairs = POP_SERIES_RE.findall(plain)
    if len(pairs) < 3:
        return None
    series = sorted((int(year), int(pop.replace(",", ""))) for pop, year in pairs)
    ratios, diffs = [], []
    for (y0, p0), (y1, p1) in zip(series, series[1:]):
        dt = y1 - y0
        if dt <= 0 or p0 <= 0:
            return None
        ratios.append((p1 / p0) ** (1 / dt))
        diffs.append((p0 - p1) / dt)
    if not diffs or max(diffs) == 0:
        return None
    ratio_spread = (max(ratios) - min(ratios)) / (sum(ratios) / len(ratios))
    diff_spread = (max(diffs) - min(diffs)) / (sum(diffs) / len(diffs))
    return "linear" if diff_spread < ratio_spread else "exponential"


def load_usable_questions(questions_dir):
    usable = []
    for path in sorted(questions_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        en = record.get("en", {})
        if en and en.get("content"):
            usable.append(record)
    return usable


def build_families(usable):
    families = defaultdict(list)
    order = [r["name"] for r in usable]
    for record in usable:
        name = record["name"]
        m = FAMILY_RE.match(name)
        family, idx = (m.group(1), int(m.group(2))) if m else (name, 1)
        families[family].append((idx, name, record))
    return families, order


def dedup(questions_dir):
    usable = load_usable_questions(questions_dir)
    families, order = build_families(usable)

    keep = []
    for family, members in families.items():
        members = sorted(members)  # by idx
        if len(members) == 1:
            keep.append(members[0][1])
            continue

        groups = defaultdict(list)
        for idx, name, record in members:
            prompt = record["en"]["content"]["prompt"]
            key = skeleton(prompt)
            trend = population_trend_fit(prompt)
            if trend:
                key = (key, trend)  # split same-skeleton members by fit-type
            groups[key].append((idx, name))

        for names in groups.values():
            keep.append(min(names)[1])  # lowest-index member is the representative

    keep = [name for name in keep if name not in AUDIT_EXCLUDE]

    # preserve original file order for readability/determinism
    keep_set = set(keep)
    return [name for name in order if name in keep_set]


def main():
    questions_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_QUESTIONS_DIR)
    keep_ordered = dedup(questions_dir)
    OUTPUT_FILE.write_text("\n".join(keep_ordered) + "\n", encoding="utf-8")
    print(f"{len(keep_ordered)} questions kept -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
