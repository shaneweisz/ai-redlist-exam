# ai-redlist-exam

Code for the paper *Evaluating AI agents on the IUCN Red List assessor exam:
Tradeoffs and opportunities for AI assistants in extinction risk assessments*.

> **Exam data not included.** The exam is used for official assessor
> certification, so its questions and answer keys are kept confidential at the
> request of the IUCN Red List Unit. Researchers wishing to reproduce the
> evaluation can request access from the IUCN Red List Unit.

## Setup

Requires [uv](https://docs.astral.sh/uv/), Docker and the
[Harbor](https://www.harborframework.com/) CLI. Copy `.env.example` to `.env`
and fill in the credentials for the agents you want to run.

## Reproducing the figures and tables

The aggregated results are in `data/figures/`, so the paper's figures and
tables can be rebuilt without the exam data:

```
PAPER_DIR=out uv run scripts/figures/build_all.py
```

## Running the evaluation (requires the exam data)

With the exam's question bank exported from Moodle in GIFT format (.txt) in
`data/exam/raw_exports/`, and the images it references in `data/exam/images/`:

```
uv run scripts/setup/parse_gift_export.py data/exam/raw_exports/<export.txt>  # -> data/exam/parsed_questions/
uv run scripts/setup/dedup_questions.py           # the 101-question core set
uv run scripts/setup/generate_harbor_tasks.py     # one Harbor task per question -> tasks/en/
# run an agent (see --help), e.g. Opus 5.5 with the guidelines, 5 attempts per question:
./run_eval.py --model opus-5-5 --guidelines opus55 -- -k 5
uv run scripts/analysis/build_figure_data.py         # runs/ -> data/figures/ (and the other build_*_data.py)
```

## Layout

```
data/iucn-guidelines/   official IUCN guideline documents, as given to agents in the guidelines condition
data/figures/           aggregated results behind the paper's figures and tables
instructions/           prompt templates for each question type and condition
scripts/setup/          parsing the exam export and generating one Harbor task per question
scripts/analysis/       runs/ -> data/figures/*.csv; metrics.py holds the reported runs and every measurement
scripts/figures/        the paper's figures and tables
run_eval.py             runs the task suite via Harbor's claude-code, codex or opencode agents
```

The IUCN guideline documents are reproduced for non-commercial use with
acknowledgement, as their copyright notices permit.
