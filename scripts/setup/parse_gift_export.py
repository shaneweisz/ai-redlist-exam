#!/usr/bin/env python3
"""
Parse a Moodle GIFT export (.txt) of the exam's question bank into one JSON
file per question, grouping the English/French/Spanish/Portuguese variants
of each question together.

Usage:
    python3 scripts/setup/parse_gift_export.py <export.txt> [output_dir]

output_dir defaults to data/exam/parsed_questions/. Images the export
references are resolved from data/exam/images/.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "exam" / "raw_exports" / "default_export_20260604.txt"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "exam" / "parsed_questions"
IMAGES_DIR = REPO_ROOT / "data" / "exam" / "images"
PLUGINFILE_RE = re.compile(r"@@PLUGINFILE@@/([A-Za-z0-9_.-]+)")

# The French/Spanish exam uses separate, genuinely localized image files for
# the Criterion E PVA graphs (different filenames, translated titles baked
# into the image itself) -- we only recovered the English originals (see
# README, data/exam/images/). Falling back to the English image for these is
# a deliberate, accepted tradeoff (not a silent hack): the underlying
# curve/data is identical, only axis labels differ, and it's strictly better
# than the alternative -- without this fallback, the unresolved
# @@PLUGINFILE@@ reference is silently dropped entirely by the HTML-to-text
# conversion downstream, leaving the model no indication a graph was ever
# there at all. Mapping Standards diagrams don't need an equivalent fallback:
# they're referenced under the same shared filename regardless of language,
# no separate localized version exists.
CRITE_FR_GRAPH_RE = re.compile(r"^FR_CritE_CR_Graph_([A-E])\.png$")
CRITE_SP_GRAPH_RE = re.compile(r"^SP_CritE_Graph_([A-E])\.png$")

QUESTION_MARKER_RE = re.compile(r"^// question: (\d+)\s+name: (.*)$")
CATEGORY_RE = re.compile(r"^\$CATEGORY:\s*(.*)$")
FIRST_LINE_RE = re.compile(r"^::(.*?)::\[(html|moodle)\](.*)\{$")
LANG_SUFFIX_RE = re.compile(r"\s+(French|Spanish|Portuguese)$")
LANG_PREFIX_RE = re.compile(r"^(FR|SP|PT)_")
WEIGHTED_RE = re.compile(r"^(~|=)%(-?\d+(?:\.\d+)?)%(.*)$")
MATCHING_RE = re.compile(r"^=(.*)\s->\s(.*)$")
SIMPLE_RE = re.compile(r"^(~|=)(.*)$")
UNESCAPED_HASH_RE = re.compile(r"(?<!\\)#")

LANG_MAP = {"FR": "fr", "SP": "sp", "PT": "pt"}


def resolve_pluginfile_images(text):
    """Rewrite @@PLUGINFILE@@/<file> to a local images/<file> path when we
    actually have that file (a handful were recovered from a companion exam
    archive), falling back to the English CritE graph for its FR/SP
    localized equivalents (see CRITE_FR_GRAPH_RE/CRITE_SP_GRAPH_RE above);
    everything else is left as an unresolved placeholder."""

    def repl(m):
        filename = m.group(1)
        if (IMAGES_DIR / filename).exists():
            return f"images/{filename}"
        for pattern in (CRITE_FR_GRAPH_RE, CRITE_SP_GRAPH_RE):
            fm = pattern.match(filename)
            if fm:
                english_equivalent = f"CritE_Graph{fm.group(1)}.jpg"
                if (IMAGES_DIR / english_equivalent).exists():
                    return f"images/{english_equivalent}"
        return m.group(0)

    return PLUGINFILE_RE.sub(repl, text)


def gift_unescape(text):
    """Undo GIFT backslash-escaping; \\n becomes a real newline."""
    if text is None:
        return None

    def repl(m):
        c = m.group(1)
        return "\n" if c == "n" else c

    text = re.sub(r"\\(.)", repl, text).strip()
    return resolve_pluginfile_images(text)


def split_feedback(remainder):
    """Split '<answer text>#<feedback>' on the first unescaped '#'."""
    parts = UNESCAPED_HASH_RE.split(remainder, maxsplit=1)
    text = gift_unescape(parts[0])
    feedback = gift_unescape(parts[1]) if len(parts) > 1 else None
    return text, feedback


def parse_body(raw_body):
    """Parse a GIFT question block into a structured dict, or None if empty."""
    if not raw_body.strip():
        return None

    lines = raw_body.split("\n")
    first_line = lines[0]
    m = FIRST_LINE_RE.match(first_line)
    if not m:
        # Unparseable shape: preserve the raw text so nothing is silently lost.
        return {"prompt": None, "type": "unparsed", "answers": [], "feedback": None,
                "raw": raw_body}

    _name_in_body, _fmt, prompt_raw = m.groups()
    prompt = gift_unescape(prompt_raw)

    body_lines = lines[1:]
    if body_lines and body_lines[-1].strip() == "}":
        body_lines = body_lines[:-1]

    answers = []
    general_feedback = None
    qtype = None

    for line in body_lines:
        line = line.strip("\t").rstrip()
        if not line:
            continue
        if line.startswith("####"):
            general_feedback = gift_unescape(line[4:])
            continue

        wm = WEIGHTED_RE.match(line)
        if wm:
            _marker, weight, remainder = wm.groups()
            weight = float(weight) if "." in weight else int(weight)
            text, feedback = split_feedback(remainder)
            answers.append({
                "correct": weight > 0,
                "weight": weight,
                "text": text,
                "feedback": feedback,
            })
            qtype = qtype or "response"
            continue

        mm = MATCHING_RE.match(line)
        if mm and "%" not in line:
            left, right = mm.groups()
            answers.append({
                "left": gift_unescape(left),
                "right": gift_unescape(right),
            })
            qtype = qtype or "matching"
            continue

        sm = SIMPLE_RE.match(line)
        if sm:
            marker, remainder = sm.groups()
            text, feedback = split_feedback(remainder)
            answers.append({
                "correct": marker == "=",
                "weight": 100 if marker == "=" else 0,
                "text": text,
                "feedback": feedback,
            })
            qtype = qtype or "response"
            continue

        # Anything else: keep it rather than silently drop it.
        answers.append({"raw": line})
        qtype = qtype or "unknown"

    return {
        "prompt": prompt,
        "type": qtype,
        "answers": answers,
        "feedback": general_feedback,
    }


def parse_file(path):
    """Return a list of {id, name, category, raw_body} records for real questions."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    records = []
    current_category = None
    i = 0
    while i < len(lines):
        line = lines[i]
        cm = CATEGORY_RE.match(line)
        if cm:
            current_category = cm.group(1)
            i += 1
            continue

        qm = QUESTION_MARKER_RE.match(line)
        if qm:
            qid = int(qm.group(1))
            name = qm.group(2)
            if qid == 0:
                # Category-switch placeholder: the actual "$CATEGORY: ..."
                # line immediately follows and must be handled by the
                # CATEGORY_RE check above on the next iteration, not
                # swallowed as this placeholder's "body".
                i += 1
                continue

            j = i + 1
            body_lines = []
            while j < len(lines) and not QUESTION_MARKER_RE.match(lines[j]):
                body_lines.append(lines[j])
                j += 1
            records.append({
                "id": qid,
                "name": name,
                "category": current_category,
                "raw_body": "\n".join(body_lines).strip("\n"),
            })
            i = j
            continue

        i += 1

    return records


def normalize_category(category):
    if category is None:
        return None
    return LANG_SUFFIX_RE.sub("", category).strip()


def split_lang(name):
    m = LANG_PREFIX_RE.match(name)
    if m:
        return LANG_MAP[m.group(1)], name[len(m.group(0)):]
    return "en", name


def sanitize_filename(name):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return safe or "question"


LEAF_CATEGORY_RE = re.compile(r"^(\d+(?:\.\d+)?):\s*(?:M\d+\s*-\s*)?(.*)$")


CATEGORY_PATH_SPLIT_RE = re.compile(r"/(?=\d+(?:\.\d+)?:)")


def parse_leaf_category(category):
    """Split the last segment of a category path into (number, name).

    Splits only at '/' characters that precede a "N:" or "N.M:" category
    label -- some category names legitimately contain a literal "//" (e.g.
    "7.1: Topic // Subtopic"), so a naive rsplit("/") would cut the
    label itself instead of the path separator.

    e.g. ".../4: Module/4.1: Topic" -> ("4.1", "Topic")
         ".../1: Module"            -> ("1", "Module")
    """
    if not category:
        return None, None
    leaf = CATEGORY_PATH_SPLIT_RE.split(category)[-1]
    m = LEAF_CATEGORY_RE.match(leaf)
    if not m:
        return None, leaf
    return m.group(1), m.group(2).strip()


def category_sort_key(category):
    number, _name = parse_leaf_category(category)
    if not number:
        return (999, 999)
    parts = number.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return (major, minor)


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "misc"


_NATURAL_CHUNK_RE = re.compile(r"(\d+)")


def natural_sort_key(text):
    chunks = _NATURAL_CHUNK_RE.split(text.lower())
    return [int(c) if c.isdigit() else c for c in chunks]


def build_groups(records):
    groups = {}  # base_name -> {"en": entry, "fr": entry, "sp": entry, "pt": entry, "category": ...}

    for rec in records:
        lang, base_name = split_lang(rec["name"])
        content = parse_body(rec["raw_body"])
        category = normalize_category(rec["category"])

        group = groups.setdefault(base_name, {"name": base_name, "_category_by_lang": {}})
        # A few source category labels have language-specific typos (e.g. a
        # missing colon in the FR/SP-only "7.1 Topic//Subtopic"
        # variant), so keep one per language and pick canonically below
        # rather than just taking whichever record happened to come first.
        if category is not None and lang not in group["_category_by_lang"]:
            group["_category_by_lang"][lang] = category

        entry = {"id": rec["id"], "content": content}

        existing = group.get(lang)
        if existing is None:
            group[lang] = entry
        else:
            # True duplicate export (same name seen twice). Keep the first,
            # just record the extra id unless the content actually differs.
            if existing["content"] == content:
                existing.setdefault("duplicate_ids", []).append(rec["id"])
            else:
                # Genuinely different content under the same name: don't
                # silently drop it -- stash it in an "other" bucket.
                group.setdefault("other_" + lang, []).append(entry)

    for group in groups.values():
        by_lang = group.pop("_category_by_lang")
        group["category"] = next(
            (by_lang[lang] for lang in ("en", "fr", "sp", "pt") if lang in by_lang),
            None,
        )

    return groups


def pick_memo(group):
    for lang in ("en", "fr", "sp", "pt"):
        entry = group.get(lang)
        if entry and entry["content"] and entry["content"].get("feedback"):
            return entry["content"]["feedback"]
    return None


def write_groups(groups, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.json"):
        stale.unlink()

    ordered = sorted(
        groups.items(),
        key=lambda kv: (category_sort_key(kv[1]["category"]), natural_sort_key(kv[0])),
    )

    used_filenames = {}
    cat_counters = {}

    for seq, (base_name, group) in enumerate(ordered, start=1):
        cat_number, cat_name = parse_leaf_category(group["category"])
        cat_number_slug = (cat_number or "x").replace(".", "-")
        cat_name_slug = slugify(cat_name) if cat_name else "misc"
        cat_counters[cat_number_slug] = cat_counters.get(cat_number_slug, 0) + 1
        cat_seq = cat_counters[cat_number_slug]

        record = {
            "seq": seq,
            "name": group["name"],
            "category": group["category"],
            "en": group.get("en"),
            "fr": group.get("fr"),
            "sp": group.get("sp"),
            "memo": pick_memo(group),
        }
        if "pt" in group:
            record["pt"] = group["pt"]
        for key in group:
            if key.startswith("other_"):
                record[key] = group[key]

        filename = f"c{cat_number_slug}_{cat_seq:02d}_{cat_name_slug}_{sanitize_filename(base_name)}"
        count = used_filenames.get(filename, 0)
        used_filenames[filename] = count + 1
        if count:
            filename = f"{filename}_{count + 1}"

        out_path = output_dir / f"{filename}.json"
        out_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return len(groups)


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_INPUT)
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(DEFAULT_OUTPUT)

    records = parse_file(input_path)
    groups = build_groups(records)
    n = write_groups(groups, output_dir)

    missing_en = sum(1 for g in groups.values() if g.get("en") is None)
    missing_fr = sum(1 for g in groups.values() if g.get("fr") is None)
    missing_sp = sum(1 for g in groups.values() if g.get("sp") is None)
    no_content = sum(
        1 for g in groups.values()
        for lang in ("en", "fr", "sp")
        if g.get(lang) and g[lang]["content"] is None
    )

    print(f"Parsed {len(records)} question records into {n} question files -> {output_dir}/")
    print(f"Missing EN: {missing_en}, missing FR: {missing_fr}, missing SP: {missing_sp}")
    print(f"Language entries with no exportable content (blank GIFT body): {no_content}")


if __name__ == "__main__":
    main()
