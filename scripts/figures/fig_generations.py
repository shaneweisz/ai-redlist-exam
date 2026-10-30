#!/usr/bin/env -S uv run
"""
Figure 3 (fig:generations): the Opus and Sonnet families over three
releases each (4.5, 5, 5.5), in Figure 2's four panels (accuracy, dollars,
seconds, tokens) plotted against release date, for the guidelines runs.
Reads data/figures/results.csv and writes
$PAPER_DIR/figures/fig_generations.pdf.

The x axis uses real dates, because the spacing between releases is part
of the result. The axes are linear, as in Figure 2.

Usage:
    python3 scripts/figures/fig_generations.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patheffects as patheffects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

import style  # noqa: E402

CONDITION = "Guidelines"
# (family, models oldest first, line style, marker, label side). The last
# field is unused: draw_panel picks each point label's side by which family
# is on top at that point.
FAMILIES = [
    ("Opus", ["Opus 4.5", "Opus 5", "Opus 5.5"], "-", "o", +1),
    ("Sonnet", ["Sonnet 4.5", "Sonnet 5", "Sonnet 5.5"], (0, (3, 1.6)), "s", -1),
]
COLOR = style.GUIDELINES_COLOR

# (title, value, point label, axis maximum). The maxima are fixed rather than
# autoscaled so that every panel's zero is on the axis and the labels above
# the tallest point have room; autoscale clips them.
PANELS = [
    ("Mean accuracy (%)", lambda row: row["accuracy_avg"],
     lambda v: f"{v:.0f}", 112.0),
    ("Mean API cost per question", lambda row: row["mean_usd_per_task"],
     lambda v: f"${v:.3f}".rstrip("0") if v < 0.01 else f"${v:.2f}", 0.70),
    ("Mean time per question (s)", lambda row: row["mean_seconds_per_task"],
     lambda v: f"{v:.0f}", 128.0),
    ("Mean tokens per question", lambda row: row["total_tokens_per_task"],
     lambda v: f"{v / 1000:.0f}k", 355_000.0),
]
THOUSANDS_TICKS = {"Mean tokens per question"}


def released(model: str) -> date:
    """style.RELEASED's "Nov 2025" as a date, at the middle of the month --
    the day is not recorded and the first of the month would imply it was."""
    month, year = style.RELEASED[model].split()
    return date(int(year), style.MONTHS.index(month) + 1, 15)


def draw_panel(ax, rows, panel) -> None:
    title, value_of, label_of, top = panel

    series = [[value_of(rows[model]) for model in models]
              for _, models, _, _, _ in FAMILIES]

    for family_index, (_, models, linestyle, marker, _) in enumerate(FAMILIES):
        dates = [released(model) for model in models]
        values = series[family_index]
        ax.plot(dates, values, linestyle=linestyle, marker=marker,
                markersize=3.2, linewidth=1.0, color=COLOR,
                markeredgecolor="white", markeredgewidth=0.6, zorder=3)
        for step, (when, value) in enumerate(zip(dates, values)):
            # Which side a label sits on is decided per point by which family
            # is on top there, not per family: Opus is dearer in every panel
            # but Sonnet writes more tokens, so a fixed side per family put
            # the lower line's labels straight through the upper line.
            other = series[1 - family_index][step]
            side = 1 if value >= other else -1
            ax.annotate(label_of(value), xy=(when, value),
                        xytext=(0, side * 5), textcoords="offset points",
                        ha="center", va="bottom" if side > 0 else "top",
                        fontsize=6, color=style.MUTED, zorder=5,
                        path_effects=[patheffects.withStroke(linewidth=2.6,
                                                             foreground="white")])

    # The accuracy panel is the one with a threshold on it, and that
    # threshold is why its axis runs past 100.
    if title.startswith("Mean accuracy"):
        ax.axhline(style.PASS_MARK, color=style.INK, linewidth=0.7,
                   linestyle=(0, (3, 2)), zorder=4)

    ax.set_ylim(-top * 0.09, top)
    if title in THOUSANDS_TICKS:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    elif title.startswith("Mean API cost"):
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:.2f}"))

    ax.set_title(title, loc="left", fontsize=7.5, pad=4)
    # Ticks on the span the data actually covers: Sep 2025 (Sonnet 4.5) to
    # Sep 2026 (both 5.5s), with Mar 2026 between them. Half-year steps
    # because a tick per release would print five labels in a panel that
    # fits three, and Jan/Jul ticks put the two endpoints between labels.
    ax.set_xlim(date(2025, 7, 20), date(2026, 10, 25))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(3, 9)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.yaxis.grid(True, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def main() -> None:
    style.apply_style()
    # load_results, not load_figure_results: Opus 5 and Sonnet 5 are in
    # FIGURE_OMITTED_MODELS, and they are the middle term of both series --
    # without them each family is two points and no trajectory.
    rows = {
        row["model"]: row
        for row in style.load_results(generation="all")
        if row["condition"] == CONDITION
    }

    # 2x2 at column width, so the figure sits in one column beside the text
    # that discusses it. The panels share the time axis, so its dates are
    # printed on the bottom row only.
    fig, axes = plt.subplots(
        2, 2, figsize=(style.COLUMN_WIDTH_IN, 3.7),
        sharex=True, constrained_layout=True,
    )
    for ax, panel in zip(axes.flat, PANELS):
        draw_panel(ax, rows, panel)

    handles = [
        Line2D([0], [0], color=COLOR, linestyle=linestyle, marker=marker,
               markersize=3.2, linewidth=1.0, markeredgecolor="white",
               markeredgewidth=0.6)
        for _, _, linestyle, marker, _ in FAMILIES
    ] + [
        Line2D([0], [0], color=style.INK, linewidth=0.7, linestyle=(0, (3, 2))),
    ]
    labels = [f"{family} 4.5 → 5 → 5.5" for family, _, _, _, _ in FAMILIES]
    labels += ["75% pass mark"]
    fig.legend(handles, labels, loc="outside lower center", ncol=2,
               handlelength=2.2, columnspacing=1.5, borderpad=0)

    style.save(fig, "fig_generations")


if __name__ == "__main__":
    main()
