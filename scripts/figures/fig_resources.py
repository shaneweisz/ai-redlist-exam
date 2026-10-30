#!/usr/bin/env -S uv run
"""
Figure 2 (fig:resources): what one question costs. Four stacked panels
share one model order: accuracy, dollars, wall-clock seconds and tokens,
for the guidelines runs only. Reads data/figures/results.csv and writes
$PAPER_DIR/figures/fig_resources.pdf.

Every panel is a mean per question with a 95% run-to-run interval
(metrics.run_to_run_ci for accuracy, metrics.round_se for the rest). The
axes are linear on purpose, so bar lengths compare as ratios. The
self-hosted model has no API price and shows "n/a" rather than $0, and its
seconds come from one Mac Studio under Ollama, unbatched, so time compares
deployments rather than models.

Usage:
    python3 scripts/figures/fig_resources.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

import style  # noqa: E402

CONDITION = "Guidelines"
# Earlier releases, on top of style.FIGURE_OMITTED_MODELS. The prior Claude
# generation has a figure of its own (fig_generations.py); the earlier
# Qwen release is in Figure 1, which carries the self-hosted progression.
# These panels compare what one would deploy today, so each family is
# represented by its current release only.
OMITTED = {"Opus 4.5", "Sonnet 4.5", "Qwen3.6:35b-a3b"}
BAR_WIDTH = 0.62
LABEL_PAD = 0.05    # gap between a bar's tip and its value label, in axis fractions
HEADROOM = 1.02     # axis maximum as a multiple of the longest bar, before labels


def usd(value: float | None) -> str:
    """A price with just enough decimals to be a price: the column runs from
    a fifth of a cent to 57 cents, and two fixed decimals would print three
    of the nine models as "$0.00". No price at all (a self-hosted model) is
    "n/a" rather than "$0" -- see the module docstring."""
    if not value:
        return "n/a"
    return f"${value:.2f}" if value >= 0.01 else f"${value:.4f}".rstrip("0")


# (title, value, label, run-to-run SE). An SE of None draws no whisker --
# a self-hosted run's cost, or a single-attempt job -- rather than a
# zero-width one that would read as a measured zero.
PANELS = [
    ("Mean accuracy (%)", lambda row: row["accuracy_avg"], lambda v: f"{v:.0f}",
     lambda row: row["accuracy_se"]),
    ("Mean API cost per question (USD)", lambda row: row["mean_usd_per_task"] or 0.0, usd,
     lambda row: row["usd_se"]),
    ("Mean time per question (s)", lambda row: row["mean_seconds_per_task"], lambda v: f"{v:.0f}",
     lambda row: row["mean_seconds_se"]),
    ("Mean tokens per question", lambda row: row["total_tokens_per_task"],
     lambda v: f"{v / 1000:.0f}k", lambda row: row["total_tokens_se"]),
]

# Panels whose x ticks are counts large enough that the raw numbers are wider
# than the space between them.
THOUSANDS_TICKS = {"Mean tokens per question"}


def draw_panel(ax, models, rows, title, value_of, label_of, se_of, is_accuracy) -> None:
    values = [value_of(rows[model]) for model in models]
    half_widths = [1.96 * se_of(rows[model]) if se_of(rows[model]) else 0.0 for model in models]
    positions = range(len(models))
    ax.bar(positions, values, width=BAR_WIDTH, color=style.GUIDELINES_COLOR, zorder=3)
    for position, value, half_width in zip(positions, values, half_widths):
        if half_width:
            ax.errorbar(position, value, yerr=half_width, fmt="none", ecolor=style.INK,
                        elinewidth=0.7, capsize=1.6, capthick=0.7, zorder=4)

    # Headroom for the labels, which sit above their bars and whiskers.
    # Taken as a fraction of the axis rather than of each bar, so the gap is
    # the same height in every panel however different the units are.
    top = max(v + h for v, h in zip(values, half_widths)) * HEADROOM
    span = 100.0 if is_accuracy else top
    ax.set_ylim(0, 112 if is_accuracy else top * 1.30)
    for position, value, half_width in zip(positions, values, half_widths):
        ax.text(
            position,
            value + half_width + span * LABEL_PAD,
            label_of(value),
            va="bottom",
            ha="center",
            fontsize=6,
            color=style.MUTED,
            zorder=5,
        )

    if is_accuracy:
        ax.axhline(style.PASS_MARK, color=style.INK, linewidth=0.7,
                   linestyle=(0, (3, 2)), zorder=4)
        ax.set_yticks(range(0, 101, 25))

    if not is_accuracy:
        ax.yaxis.set_major_locator(plt.MaxNLocator(3))
    if title in THOUSANDS_TICKS:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    elif title.startswith("Mean API cost"):
        # Ticks on whole cents: MaxNLocator put one at $0.025, which two
        # decimals print as "$0.03".
        ax.yaxis.set_major_locator(MultipleLocator(0.02))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:.2f}"))
    ax.set_title(title, loc="left", fontsize=7.5, pad=3)
    ax.set_xlim(-0.5, len(models) - 0.5)
    ax.yaxis.grid(True, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", length=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def main() -> None:
    style.apply_style()
    # Figure 1's model set: FIGURE_OMITTED_MODELS drops Sonnet 5,
    # and OMITTED drops the earlier releases on top of that: "last year's
    # model cost 15x this year's" is a claim about one family over time,
    # which is fig_generations.py's job and not what these panels compare.
    rows = {
        row["model"]: row
        for row in style.load_figure_results(generation="all")
        if row["condition"] == CONDITION and row["model"] not in OMITTED
    }
    models = [m for m in style.model_order(list(rows.values())) if m in rows]

    fig, axes = plt.subplots(
        len(PANELS), 1, figsize=(style.COLUMN_WIDTH_IN, 4.6),
        sharex=True, constrained_layout=True,
    )

    for index, (ax, (title, value_of, label_of, se_of)) in enumerate(zip(axes, PANELS)):
        draw_panel(ax, models, rows, title, value_of, label_of, se_of, is_accuracy=index == 0)

    axes[-1].set_xticks(range(len(models)))
    # Qwen3.8 Flash's name breaks too: with Opus 5 back in, six bars share
    # the column, and on one line it ran into GPT-6 Luna's.
    axes[-1].set_xticklabels([
        style.display_name(model, rows[model]["is_local"])
        .replace(" (self-hosted)", "\n(self-hosted)")
        .replace("Qwen3.8 Flash\n", "Qwen3.8\nFlash\n")
        for model in models
    ])

    # The pass mark is the one rule on the figure, and it is in one panel
    # only, so it is named in that panel's title: every bar crosses it, so
    # there is no clear space beside the rule for a label of its own.
    axes[0].set_title("Mean accuracy (%), dashed: 75% pass mark", loc="left", fontsize=7.5, pad=3)

    style.save(fig, "fig_resources")


if __name__ == "__main__":
    main()
