#!/usr/bin/env -S uv run
"""
Figure 1 (fig:exam-results): exam accuracy by model, with and without the
guidelines, against the exam's 75% pass mark. Reads data/figures/results.csv
and writes $PAPER_DIR/figures/fig_accuracy.pdf.

Shows the latest release of each model plus Qwen3.6, ordered by accuracy.
Whiskers are the 95% run-to-run interval (metrics.run_to_run_ci): how much
a score moves on a rerun, not a test of whether two models differ.

Usage:
    python3 scripts/figures/fig_accuracy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.patheffects as patheffects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.transforms as mtransforms  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import style  # noqa: E402

BAR_HEIGHT = 0.34
GROUP_OFFSET = 0.18
LABEL_GAP = 1.5       # accuracy points between a whisker cap and its value label
PASS_DASH = (0, (3, 2))
NAME_PAD_PT = 4       # gap between the axes' left edge and the model names
NAME_RAISE = 0.13     # data units the name sits above the row centre
DATE_DROP = 0.19      # data units the release month sits below it
BRACKET_X = 1.03      # axes fraction; just right of the axes
BRACKET_TICK = 0.025  # length of the bracket's end ticks, in axes fraction

# Earlier releases this chart leaves out, on top of
# style.FIGURE_OMITTED_MODELS (Sonnet 5): the prior Claude generation,
# which Figure 3 traces. Qwen3.6 stays in as a second self-hosted point
# beside Qwen3.8 Flash.
BARS_OMITTED = {"Opus 4.5", "Sonnet 4.5"}

# Names for this figure only, on top of style.SHORT_NAMES. The full
# Qwen3.6-35B-A3B name keeps what the short name drops: 35B total, 3B
# active parameters.
FIGURE_NAMES = {"Qwen3.6:35b-a3b": "Qwen3.6-35B-A3B"}


def tick_label(model: str) -> str:
    return FIGURE_NAMES.get(model, style.SHORT_NAMES.get(model, model))


def label_models(ax, models: list[str], y_of: dict[str, float]) -> None:
    """Each model's name in the gutter with its release month beneath, in
    smaller muted type -- drawn as text rather than as a two-line tick
    label, which can only set one size and colour for both lines."""
    # x in axes fraction, nudged left a fixed number of points; y in data.
    transform = ax.get_yaxis_transform() + mtransforms.ScaledTranslation(
        -NAME_PAD_PT / 72, 0, ax.figure.dpi_scale_trans)
    for model in models:
        y = y_of[model]
        ax.text(0, y + NAME_RAISE, tick_label(model), transform=transform,
                ha="right", va="center", fontsize=plt.rcParams["ytick.labelsize"],
                clip_on=False)
        ax.text(0, y - DATE_DROP, style.RELEASED[model], transform=transform,
                ha="right", va="center", fontsize=6, color=style.MUTED,
                clip_on=False)


def bracket_self_hosted(ax, rows: list[float]) -> None:
    """A bracket beside the self-hosted rows, labelled once, in place of
    "(self-hosted)" after each name -- which read as part of the model's
    name."""
    if not rows:
        return
    if rows != [rows[0] - step for step in range(len(rows))]:
        raise ValueError(f"self-hosted rows are not adjacent: {rows}")
    # x in axes fraction, y in data units, so the bracket sits a fixed
    # distance right of the axes whatever the accuracy range.
    transform = ax.get_yaxis_transform()
    top, bottom = rows[0] + 0.42, rows[-1] - 0.42
    ax.plot([BRACKET_X - BRACKET_TICK, BRACKET_X, BRACKET_X, BRACKET_X - BRACKET_TICK],
            [top, top, bottom, bottom],
            transform=transform, color=style.MUTED, linewidth=0.7, clip_on=False)
    ax.text(BRACKET_X + 0.02, (top + bottom) / 2, "self-hosted",
            transform=transform, rotation=270, ha="center", va="bottom",
            rotation_mode="anchor", fontsize=7, color=style.MUTED)


def main() -> None:
    style.apply_style()
    # The latest release of each model plus Qwen3.6, ordered by guidelines
    # accuracy, best at the top.
    rows = [row for row in style.load_figure_results(generation="all")
            if row["model"] not in BARS_OMITTED]
    by_key = {(row["model"], row["condition"]): row for row in rows}
    models = style.model_order(rows)
    y_of = {model: -index for index, model in enumerate(models)}

    fig, ax = plt.subplots(figsize=(style.COLUMN_WIDTH_IN, 3.0), constrained_layout=True)

    for model in models:
        # Guidelines above closed-book within each pair, matching the legend.
        for condition, offset in zip(style.CONDITIONS, (GROUP_OFFSET, -GROUP_OFFSET)):
            row = by_key.get((model, condition))
            if row is None:
                continue
            y = y_of[model] + offset
            # 95% run-to-run interval (see metrics.run_to_run_ci):
            # how far the score moves when the same 101 questions are rerun.
            # Drawn on top of the bar in ink rather than in the bar colour,
            # so it reads as an annotation on the estimate and not as more
            # bar. Absent for a single-attempt job, which has no rerun
            # spread -- barh simply gets no xerr rather than a zero-width
            # whisker, which would look like a measured zero.
            half_width = 1.96 * row["accuracy_se"] if row["accuracy_se"] else None
            ax.barh(
                y,
                row["accuracy_avg"],
                height=BAR_HEIGHT,
                color=style.CONDITION_COLORS[condition],
                zorder=3,
                xerr=half_width,
                error_kw=dict(ecolor=style.INK, elinewidth=0.7, capsize=1.6,
                              capthick=0.7, zorder=4),
            )
            ax.text(
                (row["accuracy_ci_hi"] or row["accuracy_avg"]) + LABEL_GAP,
                y,
                f"{row['accuracy_avg']:.0f}",
                va="center",
                ha="left",
                fontsize=6,
                color=style.MUTED,
                # Above the pass-mark rule (zorder 4) with a white halo, so
                # a label that lands on the rule breaks it cleanly rather
                # than sitting astride the dashes.
                zorder=5,
                path_effects=[patheffects.withStroke(linewidth=1.8, foreground="white")],
            )

    # The rule is named in the legend: every row has a bar crossing 75,
    # so there is no clear space beside the rule for a label of its own.
    ax.axvline(style.PASS_MARK, color=style.INK, linewidth=0.7, linestyle=PASS_DASH, zorder=4)

    ax.set_yticks([y_of[model] for model in models])
    ax.set_yticklabels([])
    label_models(ax, models, y_of)
    bracket_self_hosted(ax, [y_of[model] for model in models
                             if by_key[(model, "Guidelines")]["is_local"]])
    ax.set_ylim(y_of[models[-1]] - 0.55, 0.55)
    ax.set_xlim(0, 104)
    ax.set_xticks(range(0, 101, 25))
    ax.set_xlabel("Exam accuracy (\\%)" if plt.rcParams["text.usetex"] else "Exam accuracy (%)")
    ax.xaxis.grid(True, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(axis="y", length=0)

    # The whisker gets a legend entry of its own: it is the one mark on the
    # figure a reader cannot name by looking at it, and "run-to-run" is the
    # load-bearing word -- it is rerun spread, not a test that two models
    # differ. The number of runs is read off the data rather than written
    # in, so the legend cannot claim a count the interval was not computed
    # from.
    rounds = {row["n_rounds"] for row in rows if row["n_rounds"]}
    runs = f", {int(rounds.pop())} runs" if len(rounds) == 1 else ""
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=style.CONDITION_COLORS[condition])
        for condition in style.CONDITIONS
    ] + [
        Line2D([0], [0], color=style.INK, linewidth=0.7, marker="|",
               markersize=3.2, markeredgewidth=0.7),
        Line2D([0], [0], color=style.INK, linewidth=0.7, linestyle=PASS_DASH),
    ]
    labels = [style.CONDITION_LABELS[condition] for condition in style.CONDITIONS]
    labels += [f"95% CI (run-to-run{runs})", "75% pass mark"]
    # Anchored to the figure, not the axes. All three entries fit one row in
    # 251pt of column, but the axes are only ~180pt of that -- the rest is
    # the gutter the model names sit in -- so a legend centred on the axes
    # overhangs the right edge and clips the last entry. Centring on the
    # figure lets it use the name gutter too.
    fig.legend(
        handles,
        labels,
        loc="outside lower center",
        ncol=2,
        handlelength=1.1,
        handleheight=0.9,
        columnspacing=1.2,
        borderpad=0,
    )

    style.save(fig, "fig_accuracy")


if __name__ == "__main__":
    main()
