"""
Merge per-prompt JSON outputs into a single case file.

The split-prompt workflow produces three JSON files per case:

    <case_id>_part1.json   case_metadata, case_text, excluded_text
    <case_id>_part2.json   anchors, questions, coverage_report, audit_notes
    <case_id>_part3.json   filler_blocks, filler_constraints_used, audit_notes

This script merges them into a single <case_id>.json in the schema the
orchestration script (compression_experiment.py) consumes. It also
performs cross-prompt consistency checks that are not possible inside
any single prompt.

Usage:

    # Merge a single case given its three parts:
    python merge_case_outputs.py \
        --part1 cardiology_case_part1.json \
        --part2 cardiology_case_part2.json \
        --part3 cardiology_case_part3.json \
        --output cardiology_case.json

    # Or merge all cases in a directory (matched by case_id prefix):
    python merge_case_outputs.py --batch ./parts_dir --output-dir ./cases

    # Optionally run the contamination check on the merged result:
    python merge_case_outputs.py ... --check-contamination

Exits 0 on success, 1 if any merge had validation failures.

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PART_SUFFIXES = ("_part1.json", "_part2.json", "_part3.json")


@dataclass
class MergeIssue:
    severity: str          # ERROR / WARNING / INFO
    location: str
    message: str

    def __str__(self):
        return f"[{self.severity:7}] [{self.location}] {self.message}"


# ---------------------------------------------------------------------------
# Loaders & validators
# ---------------------------------------------------------------------------

def load_json(path: Path, issues: list[MergeIssue], label: str) -> dict | None:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        issues.append(MergeIssue("ERROR", label, f"JSON parse failed: {e}"))
    except OSError as e:
        issues.append(MergeIssue("ERROR", label, f"could not read file: {e}"))
    return None


def validate_part1(part1: dict, issues: list[MergeIssue]) -> None:
    if "case_metadata" not in part1:
        issues.append(MergeIssue("ERROR", "part1", "missing case_metadata"))
    if "case_text" not in part1 or not part1.get("case_text", "").strip():
        issues.append(MergeIssue("ERROR", "part1", "missing or empty case_text"))
    if "excluded_text" not in part1:
        issues.append(MergeIssue("WARNING", "part1", "missing excluded_text (not fatal)"))
    meta = part1.get("case_metadata", {})
    for required in ("title", "specialty"):
        if not meta.get(required):
            issues.append(MergeIssue(
                "WARNING", "part1.case_metadata",
                f"missing recommended field: {required}",
            ))
    if not meta.get("primary_condition_category"):
        issues.append(MergeIssue(
            "WARNING", "part1.case_metadata",
            "missing primary_condition_category — Prompt 3 may have lacked "
            "needed input. Verify filler was generated cleanly.",
        ))


def validate_part2(part2: dict, issues: list[MergeIssue]) -> None:
    if "anchors" not in part2 or not isinstance(part2["anchors"], list):
        issues.append(MergeIssue("ERROR", "part2", "missing or invalid anchors list"))
    if "questions" not in part2 or not isinstance(part2["questions"], list):
        issues.append(MergeIssue("ERROR", "part2", "missing or invalid questions list"))

    # Check anchor structure
    anchor_ids = set()
    for i, a in enumerate(part2.get("anchors", [])):
        if not isinstance(a, dict):
            issues.append(MergeIssue("ERROR", f"part2.anchors[{i}]", "not an object"))
            continue
        aid = a.get("id")
        if not aid:
            issues.append(MergeIssue("ERROR", f"part2.anchors[{i}]", "missing id"))
            continue
        if aid in anchor_ids:
            issues.append(MergeIssue("ERROR", f"part2.anchors", f"duplicate id: {aid}"))
        anchor_ids.add(aid)
        for required in ("category", "subtype", "text"):
            if required not in a:
                issues.append(MergeIssue(
                    "ERROR", f"part2.anchors[{aid}]",
                    f"missing required field: {required}",
                ))

    # Check question structure
    question_anchor_ids = set()
    for i, q in enumerate(part2.get("questions", [])):
        if not isinstance(q, dict):
            issues.append(MergeIssue("ERROR", f"part2.questions[{i}]", "not an object"))
            continue
        qaid = q.get("anchor_id")
        if not qaid:
            issues.append(MergeIssue("ERROR", f"part2.questions[{i}]", "missing anchor_id"))
            continue
        question_anchor_ids.add(qaid)
        if qaid not in anchor_ids:
            issues.append(MergeIssue(
                "ERROR", f"part2.questions[{qaid}]",
                f"references nonexistent anchor: {qaid}",
            ))

    # Warn on anchors without questions
    anchors_without_questions = anchor_ids - question_anchor_ids
    if anchors_without_questions:
        issues.append(MergeIssue(
            "WARNING", "part2",
            f"{len(anchors_without_questions)} anchor(s) have no question: "
            f"{sorted(anchors_without_questions)[:5]}...",
        ))


def validate_part3(part3: dict, issues: list[MergeIssue]) -> None:
    if "filler_blocks" not in part3 or not isinstance(part3["filler_blocks"], list):
        issues.append(MergeIssue("ERROR", "part3", "missing or invalid filler_blocks list"))
        return
    blocks = part3["filler_blocks"]
    if len(blocks) < 5:
        issues.append(MergeIssue(
            "WARNING", "part3",
            f"only {len(blocks)} filler blocks (recommended: 10). The "
            f"orchestrator will still recycle filler at long contexts.",
        ))
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            issues.append(MergeIssue("ERROR", f"part3.filler_blocks[{i}]", "not an object"))
            continue
        if "content" not in b or not b["content"].strip():
            issues.append(MergeIssue(
                "ERROR", f"part3.filler_blocks[{i}]", "missing or empty content",
            ))


def validate_paired_anchors(part2: dict, issues: list[MergeIssue]) -> None:
    """Check that all paired_anchors references point to real anchor IDs."""
    anchor_ids = {a.get("id") for a in part2.get("anchors", []) if a.get("id")}
    for a in part2.get("anchors", []):
        aid = a.get("id", "?")
        for paired in a.get("paired_anchors") or []:
            if paired not in anchor_ids:
                issues.append(MergeIssue(
                    "WARNING", f"part2.anchors[{aid}].paired_anchors",
                    f"references nonexistent anchor: {paired}",
                ))


def cross_validate_anchors_in_case_text(
    part1: dict, part2: dict, issues: list[MergeIssue]
) -> None:
    """Verify every anchor.text appears verbatim in case_text. This is the
    most important cross-prompt check — if it fails, the extraction
    hallucinated anchors that aren't traceable to source."""
    case_text = part1.get("case_text", "")
    if not case_text:
        return  # already flagged
    case_lower = case_text.lower()
    n_anchors = 0
    n_missing = 0
    for a in part2.get("anchors", []):
        n_anchors += 1
        text = (a.get("text") or "").strip()
        # Skip very short anchors (high false-positive rate on substring check)
        if len(text) < 5:
            continue
        if text.lower() not in case_lower:
            n_missing += 1
            aid = a.get("id", "?")
            issues.append(MergeIssue(
                "ERROR", f"cross.anchors[{aid}]",
                f"anchor text NOT found in case_text: \"{text[:60]}\"",
            ))
    if n_anchors > 0 and n_missing == 0:
        issues.append(MergeIssue(
            "INFO", "cross",
            f"all {n_anchors} anchor texts verified against case_text",
        ))


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_parts(part1: dict, part2: dict, part3: dict) -> dict:
    """Combine the three part-JSONs into a single case JSON in the
    schema expected by compression_experiment.py."""
    # Merge audit notes from part2 and part3 into a single field, preserving
    # provenance. Part1 typically has no separate audit_notes.
    audit_notes_parts: list[str] = []
    if part1.get("case_metadata", {}).get("truncation_notes"):
        audit_notes_parts.append(
            f"[part1] {part1['case_metadata']['truncation_notes']}"
        )
    if part2.get("audit_notes"):
        audit_notes_parts.append(f"[part2 anchors] {part2['audit_notes']}")
    if part3.get("audit_notes"):
        audit_notes_parts.append(f"[part3 filler] {part3['audit_notes']}")

    merged: dict = {
        "case_metadata": part1.get("case_metadata", {}),
        "case_text": part1.get("case_text", ""),
        "excluded_text": part1.get("excluded_text", ""),
        "anchors": part2.get("anchors", []),
        "questions": part2.get("questions", []),
        "filler_blocks": part3.get("filler_blocks", []),
        "coverage_report": part2.get("coverage_report", {}),
        "filler_constraints_used": part3.get("filler_constraints_used", []),
        "audit_notes": "\n\n".join(audit_notes_parts),
    }
    return merged


# ---------------------------------------------------------------------------
# Optional: invoke contamination check
# ---------------------------------------------------------------------------

def run_contamination_check(merged_path: Path, script_path: Path) -> int:
    """Invoke the contamination checker script as a subprocess. Returns the
    subprocess's exit code so the caller can propagate it.

    Fails loudly (exit code 2) if the script is missing — the user asked
    for a contamination check and we should not silently skip it.
    """
    if not script_path.exists():
        print(
            f"ERROR: --check-contamination requested but contamination "
            f"script not found at: {script_path}\n"
            f"       Either place the script there, or pass "
            f"--contamination-script <path> to point at the correct file.",
            file=sys.stderr,
        )
        return 2
    print(f"\nRunning contamination check on {merged_path}...")
    result = subprocess.run(
        [sys.executable, str(script_path), str(merged_path)],
        capture_output=False,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# Single-case driver
# ---------------------------------------------------------------------------

def merge_single_case(
    part1_path: Path,
    part2_path: Path,
    part3_path: Path,
    output_path: Path,
    check_contamination: bool,
    contamination_script: Path | None = None,
) -> int:
    issues: list[MergeIssue] = []

    part1 = load_json(part1_path, issues, "part1")
    part2 = load_json(part2_path, issues, "part2")
    part3 = load_json(part3_path, issues, "part3")

    # Stop if any file failed to load
    if any(i.severity == "ERROR" for i in issues):
        report_issues(output_path.name, issues)
        return 1
    assert part1 is not None and part2 is not None and part3 is not None

    validate_part1(part1, issues)
    validate_part2(part2, issues)
    validate_part3(part3, issues)
    validate_paired_anchors(part2, issues)
    cross_validate_anchors_in_case_text(part1, part2, issues)

    if any(i.severity == "ERROR" for i in issues):
        report_issues(output_path.name, issues)
        return 1

    merged = merge_parts(part1, part2, part3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False))

    n_anchors = len(merged.get("anchors", []))
    n_questions = len(merged.get("questions", []))
    n_filler = len(merged.get("filler_blocks", []))
    print(
        f"Wrote {output_path}: {n_anchors} anchors, {n_questions} questions, "
        f"{n_filler} filler blocks."
    )
    report_issues(output_path.name, issues)

    if check_contamination:
        # contamination_script must be supplied when check_contamination=True;
        # the CLI guarantees this via a default.
        assert contamination_script is not None
        cc_code = run_contamination_check(output_path, contamination_script)
        if cc_code == 1:
            print(
                "Contamination check flagged HIGH-severity issues. Review "
                "the merged case before running the experiment."
            )
            return 1
        elif cc_code != 0:
            print(
                "Contamination check could not run (script missing or "
                "failed to execute). Merged file was written but NOT "
                "verified for contamination."
            )
            return 1

    return 0


def report_issues(label: str, issues: list[MergeIssue]) -> None:
    if not issues:
        return
    print(f"\nValidation issues for {label}:")
    by_sev: dict[str, list[MergeIssue]] = defaultdict(list)
    for i in issues:
        by_sev[i.severity].append(i)
    for sev in ("ERROR", "WARNING", "INFO"):
        for i in by_sev.get(sev, []):
            print(f"  {i}")


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------

_PART_RE = re.compile(r"^(.+)_part([123])\.json$")


def discover_batch(parts_dir: Path) -> dict[str, dict[int, Path]]:
    """Group files in parts_dir by case_id prefix → {part_number: path}."""
    groups: dict[str, dict[int, Path]] = defaultdict(dict)
    for p in parts_dir.iterdir():
        if not p.is_file():
            continue
        m = _PART_RE.match(p.name)
        if not m:
            continue
        case_id, part_num = m.group(1), int(m.group(2))
        groups[case_id][part_num] = p
    return groups


def merge_batch(
    parts_dir: Path,
    output_dir: Path,
    check_contamination: bool,
    contamination_script: Path | None = None,
) -> int:
    groups = discover_batch(parts_dir)
    if not groups:
        print(f"ERROR: no *_partN.json files in {parts_dir}", file=sys.stderr)
        return 2

    exit_code = 0
    for case_id, parts in sorted(groups.items()):
        print(f"\n--- {case_id} ---")
        missing = [n for n in (1, 2, 3) if n not in parts]
        if missing:
            print(
                f"  SKIP: missing part(s): {missing}. Available: "
                f"{sorted(parts.keys())}"
            )
            exit_code = 1
            continue
        out = output_dir / f"{case_id}.json"
        rc = merge_single_case(
            parts[1], parts[2], parts[3], out,
            check_contamination, contamination_script,
        )
        if rc != 0:
            exit_code = 1
    return exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Merge per-prompt JSON outputs into a single case file."
    )
    p.add_argument("--part1", type=Path, help="Path to part1 JSON (case text).")
    p.add_argument("--part2", type=Path, help="Path to part2 JSON (anchors + questions).")
    p.add_argument("--part3", type=Path, help="Path to part3 JSON (filler).")
    p.add_argument("--output", type=Path,
                   help="Output path for merged case JSON (single-case mode).")
    p.add_argument("--batch", type=Path,
                   help="Directory containing per-case parts. Files must be "
                        "named <case_id>_part1.json, _part2.json, _part3.json.")
    p.add_argument("--output-dir", type=Path,
                   help="Output directory for merged cases (batch mode).")
    p.add_argument("--check-contamination", action="store_true",
                   help="After merging, invoke the contamination check script "
                        "on the merged file(s).")
    p.add_argument("--contamination-script", type=Path,
                   default=Path(__file__).parent / "check_contamination.py",
                   help="Path to the contamination check script. Default: "
                        "check_contamination.py in the same directory as this "
                        "script. Override if your script is named differently "
                        "(e.g., contamination_check.py).")
    args = p.parse_args()

    # Decide mode
    if args.batch is not None:
        if not args.output_dir:
            print("ERROR: --batch requires --output-dir", file=sys.stderr)
            return 2
        if not args.batch.is_dir():
            print(f"ERROR: --batch path is not a directory: {args.batch}",
                  file=sys.stderr)
            return 2
        return merge_batch(
            args.batch, args.output_dir,
            args.check_contamination, args.contamination_script,
        )

    # Single-case mode
    if not all([args.part1, args.part2, args.part3, args.output]):
        print(
            "ERROR: single-case mode requires --part1, --part2, --part3, "
            "and --output. For directory mode, use --batch and --output-dir.",
            file=sys.stderr,
        )
        return 2
    return merge_single_case(
        args.part1, args.part2, args.part3, args.output,
        args.check_contamination, args.contamination_script,
    )


if __name__ == "__main__":
    sys.exit(main())