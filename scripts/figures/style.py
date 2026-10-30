"""
Shared setup for the paper's figures and tables: the data loaders
(data/figures/results.csv and tools.csv), model names, ordering and
grouping, the palette, page geometry and save().

Output goes to $PAPER_DIR/figures and $PAPER_DIR/tables (default: the
sibling ai-redlist-exam-paper checkout). Figures are vector PDF at the exact
width they occupy in the paper (`\\columnwidth` = 252pt, `\\textwidth` =
522pt), so LaTeX never rescales them; for the same reason nothing uses
`bbox_inches="tight"`, which changes the width. In every figure blue means
the guidelines were available and orange means closed-book.
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.transforms import Bbox  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent.parent
DATA_PATH = REPO_DIR / "data" / "figures" / "results.csv"
TOOLS_PATH = REPO_DIR / "data" / "figures" / "tools.csv"

# The paper lives in its own (Overleaf-synced) repo alongside this one.
PAPER_DIR = Path(os.environ.get("PAPER_DIR", REPO_DIR.parent / "ai-redlist-exam-paper"))
FIGURES_DIR = PAPER_DIR / "figures"
TABLES_DIR = PAPER_DIR / "tables"

# --- Page geometry ---------------------------------------------------------
PT_PER_INCH = 72.27
COLUMN_WIDTH_IN = 252 / PT_PER_INCH  # \columnwidth
TEXT_WIDTH_IN = 522 / PT_PER_INCH  # \textwidth (figure*, spans both columns)

# --- Palette ---------------------------------------------------------------
GUIDELINES_COLOR = "#2a78d6"  # categorical slot 1 (blue)
CLOSED_BOOK_COLOR = "#eb6834"  # categorical slot 2 (orange)
CONDITION_COLORS = {"Guidelines": GUIDELINES_COLOR, "Closed-book": CLOSED_BOOK_COLOR}
CONDITION_LABELS = {
    "Guidelines": "Guidelines available",
    "Closed-book": "Closed-book",
}

# The two knowledge conditions the paper contrasts, in the order the figures
# and the results table present them.
CONDITIONS = ["Guidelines", "Closed-book"]
TABLE_CONDITIONS = ["Guidelines", "Closed-book"]

# The appendix's breakdown tables (topics, errors, votes)
# are emitted once per condition rather than once in total. They used to give
# each model a guidelines/closed-book column pair, which at seven models ran
# to eighteen columns and left the guidelines numbers -- the ones the paper's
# argument rests on -- as something the reader had to pick out of a pair.
# One condition per panel halves the width, drops the G/CB subheading row
# entirely, and lets each table lead with the guidelines block. This order
# is the order the panels are stacked in.
#
# Each subject is one table with a panel per condition, (a) and (b), in one
# tabular so the columns align.
SPLIT_CONDITIONS = ["Guidelines", "Closed-book"]
CONDITION_SLUGS = {
    "Guidelines": "guidelines",
    "Closed-book": "closedbook",
}


def panel_heading(index: int, condition: str, width: int) -> str:
    """The row that opens a condition's panel: "(a) Guidelines available"."""
    label = f"({'abcdefgh'[index]}) {CONDITION_LABELS[condition]}"
    return rf"\multicolumn{{{width}}}{{l}}{{\textit{{{label}}}}} \\"


# Between two panels of one tabular: a gap, then a rule as heavy as the
# table's own top and bottom, so a panel reads as a table in its own right.
PANEL_RULE = r"\addlinespace[1.2em]\midrule[\heavyrulewidth]"
# Column headings for the long local model names; each table's caption gives
# them in full.
SHORT_NAMES = {
    "Qwen3.6:35b-a3b": "Qwen3.6",
}


# How a column heading breaks over two lines (see column_head). A model name
# splits at its last space -- "Sonnet 5.5" over "Sonnet" and "5.5" -- which
# covers every Claude and GPT heading. The Qwen short names have no space, so
# their break is given here.
HEAD_BREAKS = {
    "Qwen3.6": ("Qwen", "3.6"),
}


def column_head(name: str) -> str:
    """A model name as a two-line column heading, upright.

    The appendix breakdowns give every model a column of two- or three-digit
    numbers, so a heading set on one line is what fixes the column width, and
    four of the five tables ran past the page: 650pt of topics, 740pt of
    errors, 656pt of images and 616pt of categories against a 522pt text
    width. Breaking each heading over two lines takes them to 442, 506, 449
    and 408pt, because the widest line is then about as wide as the numbers
    underneath it.

    Upright, after trying both rotations. Ninety degrees is the narrowest
    (358 / 456 / 340 / 296pt) and the least readable: a reviewer has to turn
    the page to read a heading in a table they are consulting for one number.
    Forty-five degrees is no more readable and does not even fit -- it keeps
    most of a heading's length in the box's own width, reaching only 530pt on
    topics and 620pt on errors. Two lines costs about 9pt of header height
    and keeps every heading horizontal at full size.

    [b] aligns the inner tabular on its bottom line, so two-line headings and
    the one-line aggregate ones ("All", "Mean") share a baseline and sit
    together on the \\midrule."""
    short = SHORT_NAMES.get(name, name)
    parts = HEAD_BREAKS.get(short) or tuple(short.rsplit(" ", 1))
    if len(parts) < 2:
        return short
    return r"\begin{tabular}[b]{@{}c@{}}" + r"\\".join(parts) + r"\end{tabular}"

_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                 7: "seven", 8: "eight", 9: "nine", 10: "ten"}

INK = "#0b0b0b"
MUTED = "#52514e"
HAIRLINE = "#d9d8d4"

PASS_MARK = 75.0  # the exam's own pass threshold

# The model headings of the results and tools tables, where a model is named
# in full. Only the names whose run label is not already the paper's form:
# Qwen3.6's is the Ollama tag.
FULL_NAMES = {"Qwen3.6:35b-a3b": "Qwen3.6-35B-A3B"}

# Run in full and reported in every table, but left off Figures 1 and 2
# (fig_generations.py keeps it).
# A second excluding rule, alongside PRIOR_GENERATION (a different
# question): these are complete current-generation runs held back for
# legibility alone. Figure 1 carries
# two bars and a direct label per model, and Figure 2 a labelled bar per
# model in each of its four panels, so each addition costs the reader more than
# it adds. Use load_figure_results() rather than load_results() to apply it;
# the tables deliberately do not.
#
# Sonnet 5 is held out in favour of Sonnet 5.5: the figures carry the
# argument about what a Red List assessor would actually deploy, and that is
# the current generation. Sonnet 5 stays in every table.
FIGURE_OMITTED_MODELS = {"Sonnet 5"}


def load_figure_results(**kwargs) -> list[dict]:
    """load_results() without FIGURE_OMITTED_MODELS -- what Figures 1 and 2
    draw. The tables call load_results() and so still report every model."""
    return [r for r in load_results(**kwargs) if r["model"] not in FIGURE_OMITTED_MODELS]


# The previous generation. Every figure and table now loads
# generation="all": the tables report these runs in their vendor groups,
# Figures 1 and 2 leave them out with their own omit sets, and Figure 3
# traces them. These are full 101x5 runs, excluded because
# the figures make a single current-generation argument and these answer a
# different question -- how much changed over a year.
PRIOR_GENERATION = {"Opus 4.5", "Sonnet 4.5"}

# Public release month of each reported model, shown in the results table's
# model headings, and the key the tables and Figure 3 order by. Fixed facts,
# so they never date the way "current" does. Sources: Anthropic model ID snapshot
# dates for the 4.5 models; TechCrunch launch coverage for Sonnet 5
# (2026-06-30) and Opus 5 (2026-07-24); Qwen3.8-Flash-Next's release on
# 2026-08-26; the Hugging Face release for Qwen3.6-35B-A3B (2026-04-16).
RELEASED = {
    "Opus 5": "Jul 2026",
    "Opus 5.5": "Sep 2026",
    "Sonnet 5": "Jun 2026",
    "Sonnet 5.5": "Sep 2026",
    "Qwen3.8 Flash": "Aug 2026",
    "Qwen3.6:35b-a3b": "Apr 2026",
    "GPT-6 Luna": "Sep 2026",
    "GPT-6 Sol": "Sep 2026",
    "Opus 4.5": "Nov 2025",
    "Sonnet 4.5": "Sep 2025",
}


def apply_style() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif"],
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.edgecolor": HAIRLINE,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "grid.color": HAIRLINE,
        "grid.linewidth": 0.5,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "pdf.fonttype": 42,  # embed TrueType, keep text selectable
        "savefig.facecolor": "white",
    })


def as_float(value: str) -> float | None:
    return float(value) if value else None


# The name the paper uses for a model, where it differs from the one the run
# data records. Applied by every loader, so all keys below use the paper's
# name; the data/figures CSVs and the scripts outside this directory keep
# the recorded one.
PAPER_NAMES = {
    "Qwen3.8-Flash-Next": "Qwen3.8 Flash",
}


def paper_name(row: dict) -> dict:
    """`row` with its model renamed to the paper's name for it."""
    return row | {"model": PAPER_NAMES.get(row["model"], row["model"])}


# Columns that are labels rather than measurements, and so are left as
# strings by every loader below.
TEXT_FIELDS = {"model", "harness", "condition", "job_dir"}


def reported(path: Path, generation: str) -> list[dict]:
    """The raw rows of one of the data/figures CSVs, narrowed to the runs the
    paper reports. Shared by every loader so the figures and tables can never
    drift into covering different sets of runs.

    `generation` selects which cohort: "current" (the default), "prior" (PRIOR_GENERATION
    only), or "all" (what every figure and table loads)."""
    if generation not in {"current", "prior", "all"}:
        raise ValueError(f"generation must be current/prior/all, got {generation!r}")
    with path.open() as handle:
        rows = [paper_name(row) for row in csv.DictReader(handle)]
    kept = []
    for row in rows:
        is_prior = row["model"] in PRIOR_GENERATION
        if generation == "current" and is_prior:
            continue
        if generation == "prior" and not is_prior:
            continue
        kept.append(row)
    return kept


def load_results(generation: str = "current") -> list[dict]:
    """Rows of data/figures/results.csv, numeric fields parsed, filtered by
    reported() to the runs the paper covers."""
    return [
        row
        | {key: as_float(value) for key, value in row.items() if key not in TEXT_FIELDS}
        | {"is_local": "local" in row["harness"]}
        for row in reported(DATA_PATH, generation)
    ]


def load_tools(generation: str = "current") -> list[dict]:
    """Rows of data/figures/tools.csv -- the tool-call distribution of each
    (model, condition) -- filtered exactly as load_results() filters the
    results rows, so the two tables report the same set of runs."""
    return [
        row
        | {key: as_float(value) for key, value in row.items() if key not in TEXT_FIELDS}
        | {"is_local": "local" in row["harness"]}
        for row in reported(TOOLS_PATH, generation)
    ]


def model_order(rows: list[dict]) -> list[str]:
    """Models sorted by guidelines-condition accuracy, best first -- derived
    from the data rather than hard-coded, so the ordering can't go stale.

    Ties break on the model name. GPT-6 Luna and Qwen3.8-Flash-Next both
    score 80.99% with the guidelines, an exact tie rather than a rounded one,
    and without a tie-break their order was whichever the CSV happened to
    list first -- so it could flip on any rebuild, silently reordering the
    bars in Figure 1 and the columns of every appendix table. The name is
    arbitrary but it is stable, which is the property that matters here."""
    accuracy = {row["model"]: row["accuracy_avg"] for row in rows if row["condition"] == "Guidelines"}
    return sorted(accuracy, key=lambda model: (-accuracy[model], model))


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def released_on(model: str) -> tuple[int, int]:
    """(year, month) for a RELEASED entry, for sorting. A model with no
    entry sorts oldest, so an unlabelled newcomer lands at the foot of the
    table rather than silently at its head."""
    stamp = RELEASED.get(model)
    if not stamp:
        return (0, 0)
    month, year = stamp.split()
    return (int(year), MONTHS.index(month) + 1)


def release_order(rows: list[dict]) -> list[str]:
    """Models newest first, by release month.

    The tables use this where the figures use model_order(): a table is read
    down a column rather than scanned for a ranking, and release order makes
    the one comparison the accuracy ordering hides -- that the table spans
    two generations, and what a year bought. Ties (four models released Sep
    2026) break on guidelines accuracy, best first, then on the name, so the
    ordering is total and cannot flip on a rebuild."""
    accuracy = {row["model"]: row["accuracy_avg"] for row in rows if row["condition"] == "Guidelines"}
    models = {row["model"] for row in rows}
    return sorted(
        models,
        key=lambda model: (
            tuple(-part for part in released_on(model)),
            -accuracy.get(model, float("-inf")),
            model,
        ),
    )


# The tables group their rows by who makes the model and how it was served,
# in this order, and sort by release date inside each group. Keyed on the
# harness, which partitions the models cleanly, rather than on the model name.
# Not split by generation, which would cut each vendor's own history in half
# -- the one comparison these tables are read for.
VENDOR_GROUPS = [
    ("Anthropic's Claude, Claude Code CLI", ("claude-code",)),
    ("OpenAI's GPT, Codex CLI", ("codex",)),
    ("Alibaba's Qwen, OpenCode (self-hosted)", ("opencode (local Mac Studio, M2 Ultra)",)),
]


def grouped_order(rows: list[dict]) -> list[tuple[str, list[str]]]:
    """[(group heading, models newest first)] over VENDOR_GROUPS.

    Empty groups are dropped, so a table that has no OpenAI run prints no
    OpenAI heading. A model whose harness is in no group would vanish
    silently, so it raises instead -- a new serving path has to be named
    here before its runs can reach a table."""
    harness_of = {row["model"]: row["harness"] for row in rows}
    known = {h for _, harnesses in VENDOR_GROUPS for h in harnesses}
    stray = sorted({h for h in harness_of.values() if h not in known})
    if stray:
        raise ValueError(f"harness not in style.VENDOR_GROUPS: {stray}")
    order = release_order(rows)
    groups = []
    for heading, harnesses in VENDOR_GROUPS:
        models = [m for m in order if harness_of[m] in harnesses]
        if models:
            groups.append((heading, models))
    return groups


def models_in(rows: list[dict], condition: str) -> list[str]:
    """The models that ran in `condition`, in grouped_order()'s order.

    Per-condition rather than "ran in every condition": a model missing one
    condition should drop out of that table alone, not out of all of them.
    The ordering is grouped_order() flattened -- vendor group, then release
    date inside it -- so a model sits in the same position in every table,
    and these tables' columns run in the same sequence as the results
    table's row groups."""
    ran = {(row["model"], row["condition"]) for row in rows}
    order = [model for _, models in grouped_order(rows) for model in models]
    return [m for m in order if (m, condition) in ran]


def count_word(n: int) -> str:
    """"seven" for 7. Table prose says "all seven models", and spelling it
    from the data stops it going stale as models are added -- it read "all
    five models" for two models longer than it was true."""
    return _NUMBER_WORDS.get(n, str(n))


def display_name(model: str, is_local: bool) -> str:
    """"(self-hosted)", not "(local)": the same word the paper uses, and the one the paper's argument turns on --
    that these models can be run on the Red List's own hardware."""
    return f"{model} (self-hosted)" if is_local else model


def declutter(fig, entries, pad_pt: float = 1.6, step_pt: float = 1.1, max_steps: int = 60,
              avoid_y: list[float] | None = None) -> None:
    """Nudge direct labels vertically until none sits on a data marker or on
    another label.

    Direct labels beat a legend here, but a fixed offset from each point only
    works while the points stay spread out. Adding the 4.5 generation put
    Opus 4.5's closed-book marker straight through the "Sonnet 5" label, and
    the offset that avoids it at one set of numbers collides at the next. So
    the placement is measured rather than guessed: matplotlib is asked for the
    rendered text boxes and the labels are stepped away from whatever they
    overlap, which keeps working as models are added.

    `entries` is one (axes, texts, points) triple per panel, where `points`
    are the (x, y) data coordinates of every marker drawn on that axes.
    Labels move only in y, so each one stays beside the point it names.

    `avoid_y` adds horizontal rules as obstacles, spanning the full axes
    width -- the pass-mark line, which is not a marker and so was invisible
    to this. With the 5.5 models in the token panel, "Opus 5.5" and "GPT-6
    Luna" both settled onto the 75% rule and onto each other, with the
    dashed line struck through the text.

    Call after the figure's layout is final -- the caller freezes the layout
    engine first, since constrained_layout would otherwise move the axes
    underneath these measurements when the figure is saved.
    """
    renderer = fig.canvas.get_renderer()
    dpi_scale = fig.dpi / 72.0
    pad, step = pad_pt * dpi_scale, step_pt * dpi_scale

    for ax, texts, points in entries:
        marker_boxes = [
            Bbox.from_bounds(x - pad, y - pad, 2 * pad, 2 * pad)
            for x, y in (ax.transData.transform(points) if len(points) else [])
        ]
        for y_data in avoid_y or []:
            x0, x1 = ax.get_xlim()
            (px0, py), (px1, _) = ax.transData.transform([(x0, y_data), (x1, y_data)])
            marker_boxes.append(Bbox.from_bounds(px0, py - pad, px1 - px0, 2 * pad))
        settled: list[Bbox] = []
        # Topmost first, so a label that has to move has somewhere settled to
        # move away from rather than chasing one that is still unplaced.
        for text in sorted(texts, key=lambda t: -t.get_position()[1]):
            box = text.get_window_extent(renderer=renderer)
            direction = 1.0
            for attempt in range(max_steps):
                blockers = [b for b in marker_boxes + settled if box.overlaps(b)]
                if not blockers:
                    break
                # Alternate up/down, widening each time, so a label boxed in
                # on one side escapes to the other instead of marching off.
                direction = -direction
                shift = direction * step * ((attempt // 2) + 1)
                box = Bbox(box.get_points() + [[0, shift], [0, shift]])
            else:
                continue  # give up rather than place it somewhere worse
            x_data, _ = text.get_position()
            _, y_data = ax.transData.inverted().transform(
                (box.x0, (box.y0 + box.y1) / 2)
            )
            text.set_position((x_data, y_data))
            settled.append(box)


def save(fig, name: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / f"{name}.pdf"
    # Omit the embedded creation timestamp: without this every rebuild
    # produces a byte-different PDF, so `git status` can no longer tell a
    # real change in the numbers from a no-op re-run.
    fig.savefig(path, metadata={"CreationDate": None})
    plt.close(fig)
    print(f"wrote {path}")
    return path
