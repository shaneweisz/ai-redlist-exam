#!/usr/bin/env -S uv run
"""
The appendix tool-use table (tab:tools): tool calls per attempt for every
model in every condition, in the results table's row order. Reads
data/figures/tools.csv and writes $PAPER_DIR/tables/tools.tex.

The left block is the distribution of call counts over attempts. The right
block splits the mean by what each call did (search, read, list, compute,
answer, other; metrics.call_action) rather than by tool, because some
models search and read through bash and others through dedicated tools.
"answer" counts calls, so it can exceed 1: a separate `mkdir` before the
write, or a rewritten answer. Emits the `tabular` block only. Requires
`booktabs`.

Usage:
    python3 scripts/figures/table_tools.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "misc"))

import hub_jobs  # noqa: E402
import style  # noqa: E402
from table_results import CONDITION_NAMES, SERVING, escape  # noqa: E402

# The label column plus every number: both the model headings and the block
# headings span the whole table and read the count from here.
N_COLUMNS = 15

# Bands of the per-attempt call count (scripts/analysis/build_tool_data.BUCKETS), as
# (csv key, heading).
BUCKET_COLUMNS = [
    ("bucket_0", "0"),
    ("bucket_1", "1"),
    ("bucket_2", "2"),
    ("bucket_3_5", "3--5"),
    ("bucket_6_10", "6--10"),
    ("bucket_11plus", "11+"),
]

# Column key -> heading, plus the concrete calls that land in it, in order:
# the work the exam actually asks for. Find the relevant passage, read it,
# see what documents exist, do the arithmetic a criterion needs, write the
# answer file.
#
# The exemplars are bracketed on a second header line rather than inline as
# "search (grep)", which would take the six headings from ~32 characters to
# ~83 and overflow \textwidth. The brackets mark them as a gloss on the
# heading above rather than a sub-column of their own. Capitalised is the agent's dedicated tool, lowercase a shell
# command, which is the whole point of the column: both land in it. They are
# the modal calls, not the definition, and each
# pair covers the large majority of its column across the corpus: grep 98.8%
# of search, Read+sed 98.2% of read, ls+find 79.9% of list, python 99.9% of
# compute. "answer" is led by `mkdir -p /output` (45.7%, the directory the
# answer goes in) with the Write tool just behind (45.3%); naming mkdir would
# be accurate and useless, so the exemplar is what the column is for.
ACTION_COLUMNS = [
    ("action_search", "search", r"\texttt{grep}"),
    ("action_read", "read", r"\texttt{Read}, \texttt{sed}"),
    ("action_list", "list", r"\texttt{ls}, \texttt{find}"),
    ("action_compute", "compute", r"\texttt{python}"),
    ("action_answer", "answer", r"\texttt{Write}"),
    # A residual, and naming one of the 45 stray calls would imply it is
    # typical of anything.
    ("action_other", "other", ""),
]

# Notes on the table, kept out of the generated .tex:
# Wrapped in its float, captioned and labelled by main.tex.
# The unit is the ATTEMPT, not the question: each row's statistics are over
# that job's 505 attempts (101 questions x 5), each one an independent agent
# rollout.
# The six middle columns are a DISTRIBUTION, not a summary: the share of
# that row's attempts making 0, 1, 2, 3-5, 6-10 and 11+ calls, so they add
# to 100 across each row. They replaced an SD, a median and an IQR, which
# described a small right-skewed count badly and hid the shape -- Opus 5.5
# with the guidelines is bimodal, 62% answering on one call and another 27%
# at 3-5, which "1.90, med 1, IQR 1-3" gives no hint of.
# "--" is exactly no attempt in that band; "<1" is at least one. The
# distinction is real: no Sonnet 4.5 guidelines attempt made fewer than
# three calls, while one Qwen3.6 attempt made two.
# The "0" column is the share that called no tool at all -- a real
# behaviour, not a parse failure. An agent that never calls write leaves
# /output/answer.txt empty and scores zero however good its prose was.
# max is kept beside the bands because the top band cannot show a tail:
# Qwen3.8's guidelines row has a median of 11 and a maximum of 108.
# The right block is means over the same attempts and sums to the mean in
# the left block, up to rounding.
# It splits by what each call DID, not by which tool was called, and that is
# the point: a by-tool split is not comparable across models, because Opus 5
# and Sonnet 5 run their searching and reading through bash where Opus 4.5
# calls the dedicated grep/read tools. Each bash command is
# classified by its own leading utility (metrics.shell_action) and
# counted alongside the dedicated tool that does the same job, so every
# column here compares like with like.
# "answer" counts CALLS, not answers written, and exceeds 1 for two quite
# different reasons, so 1.55 does not mean "wrote its answer 1.55 times":
# - A separate `mkdir -p /output` before the write. The Write tool does
# not create the directory, so Opus 4.5 and Sonnet 4.5 spend a bash call
# on it (+0.55 and +0.58 per attempt on their guidelines rows). Both
# still write exactly once: 1.00 and 1.06 writes per attempt.
# - Genuine rewriting. Qwen3.6 writes the answer file 1.48 times per
# attempt on its guidelines row (up to 11 times on one attempt),
# answering, reconsidering and overwriting.
# Every other row writes 1.00-1.10 times per attempt. Where the column falls
# below 1 the agent often wrote no answer at all (see the "0" column).
# "compute" is shelling out to python3 or bc for the reduction-rate
# arithmetic. A by-tool count cannot see it: it is just "bash".
# It measures whether a model had to LEAVE its reasoning to calculate, not
# whether it calculated. Extended thinking is on for the claude-code models
# and its blocks come back with the text stripped to a signature, so ~78% of
# Opus 5's and ~88% of Sonnet 5's billed output tokens never appear in the
# log at all -- that is where their arithmetic happens. Closed-book on the
# 32 rate/threshold questions: Opus 5 makes 0.06 compute calls per attempt
# and scores 94%, Qwen3.8 makes 0.73 and scores 58%. So compute ~ 0 does
# not mean "did no calculation".
# The second header line names the typical call in each column, capitalised
# for the agent's dedicated tool and lowercase for a shell command, so a
# reader can see at a glance that both land in the same column. They are
# examples, not the definition.
# "other" is under 0.04 calls per attempt everywhere: 23 shell commands in
# 26,252 fall outside the five actions, nearly all of them curl probes,
# plus the odd `true`, `cd` and `which`.
HEADER = r"""%% GENERATED by scripts/figures/table_tools.py -- do not edit by hand.
\footnotesize
\setlength{\tabcolsep}{4.6pt}
\begin{tabular}{lrrrrrrrrrrrrrr}
\toprule
 & \multicolumn{8}{c}{Tool calls per attempt} & \multicolumn{6}{c}{Mean calls per attempt, by what the call did} \\
\cmidrule(lr){2-9} \cmidrule(lr){10-15}
Model and condition & mean & \multicolumn{6}{c}{attempts making $n$ calls (\%)} & max & """ + " & ".join(
    name for _, name, _ in ACTION_COLUMNS
) + r""" \\
\cmidrule(lr){3-8}
 & & """ + " & ".join(heading for _, heading in BUCKET_COLUMNS) + r""" & & """ + " & ".join(
    rf"\scriptsize ({example})" if example else "" for _, _, example in ACTION_COLUMNS
) + r""" \\
\midrule"""

FOOTER = r"""\bottomrule
\end{tabular}"""


def share(value: float) -> str:
    """One of the bucket percentages.

    Whole numbers, because a band of a 505-attempt distribution does not
    support a decimal that a reader would act on. "--" is exactly no
    attempt, distinct from "<1", which is at least one -- the same
    distinction the vote table draws, and it matters here because a band
    can be genuinely empty (no Sonnet 4.5 guidelines attempt made fewer
    than three calls) or merely rare (one Qwen3.6 attempt made two)."""
    if value == 0:
        return "--"
    return "$<$1" if value < 0.5 else f"{value:.0f}"


def body_rows(rows: list[dict], models: list[str]) -> list[str]:
    by_key = {(row["model"], row["condition"]): row for row in rows}
    lines: list[str] = []
    for index, model in enumerate(models):
        # A model only lists the conditions it actually ran.
        model_rows = [by_key[(model, c)] for c in style.TABLE_CONDITIONS if (model, c) in by_key]
        # A model can be absent from this table while present in the results
        # table: tool counts come from the agent's own log, and not every
        # harness writes one this script can parse (the codex agent does not,
        # so the GPT-6 rows have no tool data). Skip rather than crash --
        # the model order is derived from results.csv, which is a superset.
        if not model_rows:
            continue
        if index:
            lines.append(r"\addlinespace")
        # The group heading names the vendor and the serving path, so the
        # per-model note is the release month alone. SERVING covers a
        # harness with no group of its own.
        details = f"released {style.RELEASED[model]}" if model in style.RELEASED \
            else SERVING.get(model_rows[0]["harness"], "--")
        lines.append(rf"\multicolumn{{{N_COLUMNS}}}{{l}}{{\textbf{{{escape(style.FULL_NAMES.get(model, model))}}} \enspace \textit{{{details}}}}} \\")
        for row in model_rows:
            lines.append(
                " & ".join([
                    r"\quad " + hub_jobs.link(CONDITION_NAMES[row["condition"]], row["job_dir"]),
                    f"{row['mean']:.2f}",
                    *[share(row[key]) for key, _ in BUCKET_COLUMNS],
                    f"{row['max']:.0f}",
                    *[f"{row[key]:.2f}" for key, _, _ in ACTION_COLUMNS],
                ])
                + r" \\"
            )
    return lines


def main() -> None:
    style.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    # Grouped exactly as the results table is -- vendor and serving path,
    # newest model first inside each group -- so a reader can put the two
    # side by side.
    rows = style.load_tools(generation="all")
    body: list[str] = []
    for heading, models in style.grouped_order(style.load_results(generation="all")):
        if body:
            body.append(r"\addlinespace")
        body.append(rf"\multicolumn{{{N_COLUMNS}}}{{l}}{{\textsc{{{heading}}}}} \\")
        body.append(r"\addlinespace")
        body.extend(body_rows(rows, models))
    latex = "\n".join([HEADER, *body, FOOTER, ""])
    path = style.TABLES_DIR / "tools.tex"
    path.write_text(latex)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
