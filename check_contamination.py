"""
Contamination check for compression-experiment case files.

Runs sanity checks on a case JSON to confirm the experiment will produce
interpretable results. Designed to be run BEFORE adding a case to your
experiment directory.

What it checks:

  1. Anchor leakage: does anchor 'text' appear verbatim inside any
     filler block? This is the central contamination risk — if it does,
     the answering model can recover the anchor from filler rather than
     from case_text, and the experiment isn't measuring what you think.

  2. Expected-answer leakage: does any question's expected_answer appear
     verbatim in filler? Same problem, even more direct.

  3. Anchor-in-case verification: does every anchor 'text' actually
     appear in case_text? If an anchor isn't traceable to the source,
     the extraction hallucinated it.

  4. N-gram overlap: do filler blocks share long n-grams with case_text?
     Suggests the filler generator copied content from the case rather
     than generating original material.

  5. Clinical-specificity leakage in filler: do filler blocks contain
     specific doses, INR values, lab values with units, drug names from
     a small high-confidence dictionary? The filler prompt explicitly
     forbids these.

  6. Anchor text in case_metadata: anchor content showing up in title or
     other metadata is informational only — the orchestration script
     does not currently put metadata into prompts, but it's worth
     flagging in case that ever changes.

Usage:

  python check_contamination.py path/to/case.json
  python check_contamination.py path/to/cases_dir/

Exits 0 if no HIGH-severity findings, 1 otherwise. MEDIUM and LOW
findings are printed but do not cause a non-zero exit.

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Tunables — adjust these if you find the checks are too strict or lenient.
# ---------------------------------------------------------------------------

NGRAM_SIZE = 8                  # word n-gram length for case↔filler overlap
NGRAM_OVERLAP_THRESHOLD = 3     # >=N shared distinctive n-grams = flag
MIN_ANCHOR_LEN_FOR_SUBSTRING = 5  # don't substring-check anchors shorter
                                  # than this (avoids false positives on
                                  # tokens like "MI" or "PE")

# Clinical specificity patterns that should NOT appear in filler.
# Conservative — these are unambiguous markers of specific clinical
# entities that the filler prompt forbids.
CLINICAL_SPECIFICITY_PATTERNS = [
    (r"\b\d+(?:\.\d+)?\s?mg(?:/kg|/dL|/mL|/L)?\b", "dose-like number with mg unit"),
    (r"\b\d+(?:\.\d+)?\s?mcg(?:/kg|/dL|/mL|/L)?\b", "dose-like number with mcg unit"),
    (r"\bINR\s+(?:of\s+)?[\d.]+\b", "specific INR value"),
    (r"\bH(?:emo)?g(?:lo)?b(?:in)?\s+[\d.]+\s?g/dL\b", "specific Hgb value with unit"),
    (r"\bC(?:reat)?(?:inine)?\s+[\d.]+\s?mg/dL\b", "specific creatinine value with unit"),
    (r"\bWBC\s+[\d,]+(?:/mm.?)?\b", "specific WBC value"),
    (r"\bBP\s+\d+/\d+\b", "specific blood pressure"),
    (r"\bHR\s+\d+\b", "specific heart rate value"),
    (r"\bO2?\s?sat\w*\s+\d+%?\b", "specific O2 sat value"),
    (r"\bRR\s+\d+\b", "specific respiratory rate"),
    (r"\bSBP\s+\d+\b", "specific systolic BP value"),
    (r"\bDBP\s+\d+\b", "specific diastolic BP value"),
    (r"\b\d+\s?mL/min\b", "specific renal clearance"),
    # Specific named drugs that commonly leak — small, high-confidence list.
    # Add more as needed for your case set.
    (r"\b(?:rivaroxaban|apixaban|dabigatran|edoxaban|warfarin|acenocoumarol)\b",
     "named direct oral / vitamin-K-antagonist anticoagulant"),
    (r"\b(?:aspirin|clopidogrel|prasugrel|ticagrelor)\b", "named antiplatelet"),
    (r"\b(?:vancomycin|daptomycin|linezolid|ceftriaxone|cefepime|piperacillin|tazobactam|"
     r"meropenem|ertapenem|ampicillin|gentamicin|tobramycin|amikacin)\b",
     "named antimicrobial"),
    (r"\b(?:metoprolol|atenolol|carvedilol|amlodipine|lisinopril|losartan|valsartan|"
     r"hydralazine|clonidine|furosemide)\b", "named cardiovascular agent"),
    (r"\b(?:atorvastatin|rosuvastatin|simvastatin|pravastatin)\b", "named statin"),
    (r"\b(?:metformin|glipizide|glyburide|insulin|empagliflozin|liraglutide|semaglutide)\b",
     "named diabetes agent"),
    (r"\bMRSA\b", "specific organism abbreviation (MRSA)"),
    (r"\bMSSA\b", "specific organism abbreviation (MSSA)"),
    (r"\bVRE\b", "specific organism abbreviation (VRE)"),
    (r"\b(?:Staph(?:ylococcus)?\.?\s+aureus|Enterococcus|Streptococcus|E\.?\s*coli|"
     r"Klebsiella|Pseudomonas)\b", "specific bacterial taxonomy"),
]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str  # HIGH / MEDIUM / LOW
    check: str
    target: str    # anchor_id, block_id, "metadata", etc.
    message: str

    def __str__(self):
        return f"[{self.severity:6}] [{self.check:25}] [{self.target:10}] {self.message}"


# ---------------------------------------------------------------------------
# Tokenization helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\b\w+\b")


def tokenize(text: str) -> list[str]:
    """Simple lowercase word tokenization for n-gram overlap."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def ngrams(tokens: list[str], n: int) -> Iterable[tuple[str, ...]]:
    if len(tokens) < n:
        return
    for i in range(len(tokens) - n + 1):
        yield tuple(tokens[i:i + n])


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_anchor_in_filler(case: dict, findings: list[Finding]) -> None:
    """Severity scales with anchor distinctiveness — a low-distinctiveness
    anchor like 'hypertension' may legitimately appear in scene-setting
    filler, but a high-distinctiveness anchor like 'rivaroxaban 15 mg daily'
    in filler is a hard contamination."""
    filler_combined = "\n".join(b.get("content", "") for b in case.get("filler_blocks", []))
    filler_lower = filler_combined.lower()
    for anchor in case.get("anchors", []):
        text = anchor.get("text", "").strip()
        if len(text) < MIN_ANCHOR_LEN_FOR_SUBSTRING:
            continue
        if text.lower() in filler_lower:
            dist = (anchor.get("distinctiveness") or "medium").lower()
            severity = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(dist, "MEDIUM")
            findings.append(Finding(
                severity=severity,
                check="anchor_in_filler",
                target=anchor.get("id", "?"),
                message=f"anchor text appears verbatim in filler "
                        f"(distinctiveness={dist}): \"{text[:60]}\"",
            ))


def check_expected_answer_in_filler(case: dict, findings: list[Finding]) -> None:
    """Always HIGH if it triggers — expected_answer is what the judge
    scores against; if it's in filler, the answering model can lift it
    directly."""
    filler_combined = "\n".join(b.get("content", "") for b in case.get("filler_blocks", []))
    filler_lower = filler_combined.lower()
    for q in case.get("questions", []):
        ea = (q.get("expected_answer") or "").strip()
        if len(ea) < MIN_ANCHOR_LEN_FOR_SUBSTRING:
            continue
        if ea.lower() in filler_lower:
            findings.append(Finding(
                severity="HIGH",
                check="expected_answer_in_filler",
                target=q.get("anchor_id", "?"),
                message=f"expected_answer appears verbatim in filler: \"{ea[:60]}\"",
            ))


def check_anchor_in_case_text(case: dict, findings: list[Finding]) -> None:
    """Verifies that each anchor's text is actually present in case_text.
    Missing case_text is fatal — we cannot run without it. Anchors that
    don't appear in case_text suggest extraction hallucination."""
    case_text = case.get("case_text")
    if not case_text:
        # If case_text is not in the JSON, the orchestrator looks for a .txt
        # file next to it; we can't fully verify here but we flag it.
        findings.append(Finding(
            severity="HIGH",
            check="case_text_missing",
            target="case",
            message="case_text field is absent; orchestrator will require "
                    "a companion <case_id>.txt file. Add case_text to JSON "
                    "for full verification.",
        ))
        return
    case_lower = case_text.lower()
    for anchor in case.get("anchors", []):
        text = anchor.get("text", "").strip()
        if len(text) < MIN_ANCHOR_LEN_FOR_SUBSTRING:
            continue
        if text.lower() not in case_lower:
            findings.append(Finding(
                severity="HIGH",
                check="anchor_not_in_case_text",
                target=anchor.get("id", "?"),
                message=f"anchor text NOT found in case_text (extraction "
                        f"may have hallucinated): \"{text[:60]}\"",
            ))


def check_ngram_overlap(case: dict, findings: list[Finding]) -> None:
    """Distinctive n-grams shared between case_text and filler suggest
    the filler generator copied content from the case rather than
    generating original prose."""
    case_text = case.get("case_text", "")
    if not case_text:
        return
    case_tokens = tokenize(case_text)
    case_ngrams = set(ngrams(case_tokens, NGRAM_SIZE))
    if not case_ngrams:
        return

    for block in case.get("filler_blocks", []):
        block_tokens = tokenize(block.get("content", ""))
        block_ngrams = set(ngrams(block_tokens, NGRAM_SIZE))
        shared = case_ngrams & block_ngrams
        if len(shared) >= NGRAM_OVERLAP_THRESHOLD:
            sample = list(shared)[:3]
            sample_text = "; ".join(" ".join(ng) for ng in sample)
            findings.append(Finding(
                severity="MEDIUM",
                check="ngram_overlap",
                target=f"block_{block.get('block_id', '?')}",
                message=f"{len(shared)} {NGRAM_SIZE}-grams shared with "
                        f"case_text (filler may have copied case content). "
                        f"Examples: {sample_text}",
            ))


def check_filler_specificity(case: dict, findings: list[Finding]) -> None:
    """Filler should not contain specific doses, lab values, drug names,
    organisms, etc. Uses a conservative pattern list — false positives
    are possible but each finding is worth a manual look."""
    for block in case.get("filler_blocks", []):
        content = block.get("content", "")
        block_id = f"block_{block.get('block_id', '?')}"
        hits_by_pattern: dict[str, list[str]] = {}
        for pattern, label in CLINICAL_SPECIFICITY_PATTERNS:
            matches = re.findall(pattern, content, flags=re.IGNORECASE)
            if matches:
                hits_by_pattern.setdefault(label, []).extend(matches[:3])
        for label, examples in hits_by_pattern.items():
            findings.append(Finding(
                severity="HIGH",
                check="filler_specificity",
                target=block_id,
                message=f"filler contains forbidden specific clinical content "
                        f"({label}): {examples[:3]}",
            ))


def check_anchor_in_metadata(case: dict, findings: list[Finding]) -> None:
    """Informational — script does not currently put metadata in prompts,
    but worth flagging for awareness."""
    meta = case.get("case_metadata", {})
    meta_blob = " ".join(
        str(v) for k, v in meta.items()
        if k in ("title", "patient_descriptor", "source") and isinstance(v, str)
    ).lower()
    for anchor in case.get("anchors", []):
        text = anchor.get("text", "").strip()
        if len(text) < MIN_ANCHOR_LEN_FOR_SUBSTRING:
            continue
        if (anchor.get("distinctiveness") or "").lower() == "high" and text.lower() in meta_blob:
            findings.append(Finding(
                severity="LOW",
                check="anchor_in_metadata",
                target=anchor.get("id", "?"),
                message=f"high-distinctiveness anchor text appears in "
                        f"case_metadata: \"{text[:60]}\" (informational only)",
            ))


def check_filler_block_count(case: dict, findings: list[Finding]) -> None:
    """The v2 extraction prompt asks for 10 blocks; older cases may have
    5. This is informational only — the script will recycle filler as
    needed — but it's useful to know."""
    n = len(case.get("filler_blocks", []))
    if n < 10:
        findings.append(Finding(
            severity="LOW",
            check="filler_block_count",
            target="case",
            message=f"only {n} filler blocks present (v2 prompt asks for "
                    f"10); script will recycle filler at long contexts.",
        ))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_anchor_in_case_text,
    check_anchor_in_filler,
    check_expected_answer_in_filler,
    check_ngram_overlap,
    check_filler_specificity,
    check_anchor_in_metadata,
    check_filler_block_count,
]


def check_case(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        case = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        findings.append(Finding(
            severity="HIGH",
            check="json_parse",
            target="file",
            message=f"could not parse JSON: {e}",
        ))
        return findings
    except OSError as e:
        findings.append(Finding(
            severity="HIGH",
            check="file_read",
            target="file",
            message=f"could not read file: {e}",
        ))
        return findings

    for check in ALL_CHECKS:
        try:
            check(case, findings)
        except Exception as e:  # noqa: BLE001
            findings.append(Finding(
                severity="HIGH",
                check=check.__name__,
                target="check",
                message=f"check raised exception: {e}",
            ))
    return findings


def report(path: Path, findings: list[Finding], verbose: bool) -> int:
    """Print findings, return 1 if any HIGH severity findings, else 0."""
    print(f"\n=== {path} ===")
    if not findings:
        print("  No contamination findings. Case is clean.")
        return 0

    counts = Counter(f.severity for f in findings)
    print(
        f"  Findings: {counts.get('HIGH', 0)} HIGH, "
        f"{counts.get('MEDIUM', 0)} MEDIUM, {counts.get('LOW', 0)} LOW"
    )

    # Sort by severity (HIGH first), then check name
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda f: (severity_order.get(f.severity, 99), f.check, f.target))

    for f in findings:
        if f.severity == "LOW" and not verbose:
            continue
        print(f"  {f}")

    if not verbose and counts.get("LOW"):
        print(f"  ({counts['LOW']} LOW-severity findings hidden; use --verbose to see them)")

    return 1 if counts.get("HIGH", 0) > 0 else 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Check case JSON files for experimental contamination."
    )
    p.add_argument("path", type=Path,
                   help="Path to a case JSON file, or a directory of them.")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show LOW-severity findings as well.")
    p.add_argument("--glob", default="*.json",
                   help="Glob pattern when path is a directory (default: *.json).")
    args = p.parse_args()

    if not args.path.exists():
        print(f"ERROR: path does not exist: {args.path}", file=sys.stderr)
        return 2

    if args.path.is_dir():
        files = sorted(args.path.glob(args.glob))
        if not files:
            print(f"ERROR: no files matched {args.glob} in {args.path}", file=sys.stderr)
            return 2
    else:
        files = [args.path]

    exit_code = 0
    total_findings = Counter()
    for f in files:
        findings = check_case(f)
        total_findings.update(x.severity for x in findings)
        if report(f, findings, verbose=args.verbose):
            exit_code = 1

    if len(files) > 1:
        print(
            f"\n=== TOTAL across {len(files)} case(s): "
            f"{total_findings.get('HIGH', 0)} HIGH, "
            f"{total_findings.get('MEDIUM', 0)} MEDIUM, "
            f"{total_findings.get('LOW', 0)} LOW ==="
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())