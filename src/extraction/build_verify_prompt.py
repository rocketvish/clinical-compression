"""CLI: generate a verification prompt to paste into claude.ai."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.extraction.prompts import build_verification_prompt
from src.schema.fact_schema import FactFile


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Generate a verification (missing-fact) prompt for claude.ai."
    )
    parser.add_argument("--input", required=True, help="Path to document text file.")
    parser.add_argument("--facts", required=True, help="Path to existing FactFile JSON.")
    parser.add_argument("--output", help="Write prompt to file instead of stdout.")
    args = parser.parse_args(argv)

    document_text = Path(args.input).read_text(encoding="utf-8")
    # Load + re-serialize so the embedded facts are normalized and known-valid.
    existing = FactFile.from_json(args.facts)
    existing_facts_json = existing.model_dump_json(indent=2)

    prompt = build_verification_prompt(document_text, existing_facts_json)

    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"Written to: {args.output}")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
