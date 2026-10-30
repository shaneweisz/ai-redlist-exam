#!/usr/bin/env -S uv run
"""
Regenerate every figure and table in the paper from the committed CSVs in
data/figures/. This does not re-read runs/: if the runs have changed, run
the scripts/analysis/build_*_data.py scripts first.

Usage:
    python3 scripts/figures/build_all.py
    PAPER_DIR=/path/to/paper python3 scripts/figures/build_all.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fig_accuracy  # noqa: E402
import fig_generations  # noqa: E402
import fig_resources  # noqa: E402
import table_agreement  # noqa: E402
import table_errors  # noqa: E402
import table_results  # noqa: E402
import table_tools  # noqa: E402
import table_votes  # noqa: E402
import table_topics  # noqa: E402

if __name__ == "__main__":
    fig_accuracy.main()
    fig_resources.main()
    fig_generations.main()
    table_results.main()
    table_topics.main()
    table_errors.main()
    table_votes.main()
    table_agreement.main()
    table_tools.main()
