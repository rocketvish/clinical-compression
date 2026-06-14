"""Validate a raw claude.ai JSON response against the FactFile schema.

The library function `validate_response` is pure (it raises on failure); the
CLI `main` is responsible for printing clear errors and setting exit codes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from src.schema.fact_schema import Fact, FactFile

# ---------------------------------------------------------------------------
# JSON extraction helpers (shared with merge.py)
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove a leading ``` / ```json fence and its trailing ``` if present."""
    t = text.strip()
    if t.startswith("```"):
        t = t[3:]
        newline = t.find("\n")
        # Drop an optional language id on the opening fence line (e.g. "json").
        if newline != -1 and t[:newline].strip().isalpha():
            t = t[newline + 1:]
        t = t.rstrip()
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _extract_between(text: str, open_ch: str, close_ch: str, what: str) -> str:
    """Slice from the first `open_ch` to the last `close_ch`, discarding any
    preamble/postamble the model may have added around the JSON."""
    t = _strip_code_fences(text)
    start = t.find(open_ch)
    end = t.rfind(close_ch)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON {what} found in response.")
    return t[start:end + 1]


def _extract_json_object(text: str) -> str:
    return _extract_between(text, "{", "}", "object")


def _extract_json_array(text: str) -> str:
    return _extract_between(text, "[", "]", "array")


def format_category_counts(facts: list[Fact]) -> str:
    """e.g. 'categorical: 5, temporal: 3'."""
    counts = Counter(f.category.value for f in facts)
    return ", ".join(f"{cat}: {n}" for cat, n in counts.items())


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


def validate_response(raw_json: str) -> FactFile:
    """Clean, parse, and validate a raw extraction response into a FactFile.

    Raises ValueError on missing/invalid JSON and pydantic.ValidationError on
    schema violations.
    """
    cleaned = _extract_json_object(raw_json)
    parsed = json.loads(cleaned)  # raises json.JSONDecodeError (a ValueError)
    return FactFile.model_validate(parsed)  # raises ValidationError


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_validation_errors(exc: ValidationError) -> None:
    print("Schema validation failed:", file=sys.stderr)
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        print(f"  {loc}: {err['msg']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Validate a raw claude.ai response against the FactFile schema."
    )
    parser.add_argument("--input", required=True, help="Path to raw JSON response file.")
    parser.add_argument("--output", required=True, help="Path to write validated FactFile.")
    args = parser.parse_args(argv)

    raw = Path(args.input).read_text(encoding="utf-8")
    try:
        fact_file = validate_response(raw)
    except ValidationError as exc:
        _print_validation_errors(exc)
        return 1
    except ValueError as exc:  # missing JSON or JSONDecodeError
        print(f"Could not parse JSON: {exc}", file=sys.stderr)
        return 1

    fact_file.to_json(args.output)
    print(
        f"Validated: {len(fact_file.facts)} facts "
        f"({format_category_counts(fact_file.facts)})"
    )
    print(f"Written to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
