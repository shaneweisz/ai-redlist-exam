#!/usr/bin/env -S uv run
"""
Harbor Hub job ids, which the paper's tables use to link each run to its
Hub job (link()). Read from the committed snapshot data/hub_jobs.csv, or
live from `harbor hub job list`; without the snapshot, tables get plain
labels instead of links.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_DIR / "data" / "hub_jobs.csv"

# harbor/constants.py: HARBOR_VIEWER_JOBS_URL. A citation can name a run and
# nothing finer -- `harbor hub trial show` prints a trial's uuid but builds
# no link for it.
HUB_JOBS_URL = "https://hub.harborframework.com/jobs"


def job_url(hub_job_id: str) -> str:
    """The Hub's comparison view for one job, rather than /jobs/<id>.

    It is the same run either way, but the compare tab opens on the
    per-task breakdown -- which questions the run got right -- where the
    plain job page opens on the run's summary. The breakdown is what a
    reader following a citation out of this paper's tables is after. The
    view takes a list, so the same URL shape extends to citing several runs
    side by side."""
    return f"{HUB_JOBS_URL}/selected?jobs={hub_job_id}&tab=compare"


def latex_url(hub_job_id: str) -> str:
    r"""job_url() with the query separator escaped for \href.

    A bare & inside a tabular cell is an alignment tab and would silently
    split the row; hyperref reads \& back as a literal ampersand."""
    return job_url(hub_job_id).replace("&", r"\&")


def from_hub() -> dict[str, str]:
    """{job name: hub job id}, live from `harbor hub job list`. Needs Hub
    auth; raises SystemExit with the CLI's own message if it is missing."""
    result = subprocess.run(
        ["harbor", "hub", "job", "list"],
        capture_output=True, text=True, cwd=REPO_DIR, timeout=180,
    )
    if result.returncode != 0:
        sys.exit(f"harbor hub job list failed (exit {result.returncode}):\n{result.stderr.strip()}")
    lines = result.stdout.splitlines()
    if not lines or not lines[0].startswith("ID\t"):
        sys.exit(f"unexpected `harbor hub job list` output:\n{result.stdout[:400]}")
    jobs = {}
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0]:
            jobs[fields[1]] = fields[0]
    return jobs


def snapshot() -> dict[str, str]:
    """{job name: hub job id} from the committed CSV. Empty if it is absent,
    so a fresh clone builds the tables without Hub links rather than
    failing."""
    if not SNAPSHOT_PATH.exists():
        return {}
    with SNAPSHOT_PATH.open() as handle:
        return {row["job_name"]: row["hub_job_id"] for row in csv.DictReader(handle)}


_SNAPSHOT: dict[str, str] | None = None


def link(label: str, job_dir: str | Path) -> str:
    r"""`label` linked to the run's Harbor Hub page, when the run has been
    uploaded and snapshotted (scripts/misc/build_hub_ids.py).

    Every table links its model labels this way -- a condition row, a model
    row or a model column heading -- so any number in the paper is one click
    from the run it came from. hyperref is loaded with `hidelinks`, so this adds
    no visible mark; the captions say the labels are clickable. A run with
    no id (not uploaded, or a fresh clone with no data/hub_jobs.csv) falls
    back to plain text, so the tables always build."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = snapshot()
    hub_job_id = _SNAPSHOT.get(Path(job_dir).name)
    if not hub_job_id:
        return label
    return rf"\href{{{latex_url(hub_job_id)}}}{{{label}}}"


def job_dirs(rows: list[dict], condition: str) -> dict[str, str]:
    """{model: job_dir} for one condition's runs, for the per-condition
    tables whose model labels carry no row of their own."""
    return {row["model"]: row["job_dir"] for row in rows if row["condition"] == condition}


def write_snapshot(jobs: dict[str, str]) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["job_name", "hub_job_id"])
        for name in sorted(jobs):
            writer.writerow([name, jobs[name]])
