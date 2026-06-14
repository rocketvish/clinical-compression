"""CLI: generate an extraction prompt to paste into claude.ai."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.extraction.prompts import build_extraction_prompt
from src.schema.fact_schema import NoteType


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Generate a clinical fact extraction prompt for claude.ai."
    )
    parser.add_argument("--input", required=True, help="Path to document text file.")
    parser.add_argument("--document-id", help="Document ID (default: input filename stem).")
    parser.add_argument("--note-type", default="other", help="NoteType enum value.")
    parser.add_argument("--date", help="Document date (ISO YYYY-MM-DD).")
    parser.add_argument("--author-role", help="Author role.")
    parser.add_argument("--source-dataset", default="manual", help="Source dataset name.")
    parser.add_argument("--output", help="Write prompt to file instead of stdout.")
    args = parser.parse_args(argv)

    # Validate note_type at the boundary so a typo fails here rather than at the
    # validate step (the library builder accepts any string).
    try:
        NoteType(args.note_type)
    except ValueError:
        allowed = ", ".join(n.value for n in NoteType)
        print(
            f"Invalid --note-type {args.note_type!r}. Allowed: {allowed}",
            file=sys.stderr,
        )
        return 1

    document_text = Path(args.input).read_text(encoding="utf-8")
    document_id = args.document_id or Path(args.input).stem

    prompt = build_extraction_prompt(
        document_text=document_text,
        document_id=document_id,
        note_type=args.note_type,
        date=args.date,
        author_role=args.author_role,
        source_dataset=args.source_dataset,
    )

    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"Written to: {args.output}")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
