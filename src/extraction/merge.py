"""Merge verification-pass facts into an existing FactFile.

The verification prompt returns a JSON *array* of additional Fact objects. We
validate each, resolve any fact-id collisions, append, and re-validate the whole
FactFile.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from src.extraction.validate import _extract_json_array, format_category_counts
from src.schema.fact_schema import Fact, FactFile


def _max_fact_number(facts: list[Fact]) -> int:
    """Highest integer found in existing fact ids (e.g. 'f013' -> 13)."""
    nums = [int(m.group()) for f in facts if (m := re.search(r"\d+", f.id))]
    return max(nums) if nums else len(facts)


def merge_facts(existing: FactFile, new_facts_json: str) -> FactFile:
    """Validate and append the verification-pass facts to `existing`.

    Only colliding fact *ids* are renumbered (ids are not cross-referenced, so
    renumbering them is safe). `group_id`s are intentionally left untouched —
    they link facts, and safely remapping them would require rewriting
    intra-group references; we rely on the verification prompt instructing the
    model to continue group ids from the highest existing one.
    """
    cleaned = _extract_json_array(new_facts_json)
    raw_list = json.loads(cleaned)
    if not isinstance(raw_list, list):
        raise ValueError("Verification response must be a JSON array of Fact objects.")
    if not raw_list:
        return existing  # empty array -> no-op

    new_facts: list[Fact] = []
    for i, item in enumerate(raw_list):
        try:
            new_facts.append(Fact.model_validate(item))
        except ValidationError as exc:
            raise ValueError(f"New fact at index {i} failed validation:\n{exc}") from exc

    # Resolve id collisions against existing ids and amongst the new facts.
    taken = {f.id for f in existing.facts}
    next_n = _max_fact_number(existing.facts)
    for nf in new_facts:
        if nf.id in taken:
            next_n += 1
            new_id = f"f{next_n:03d}"
            while new_id in taken:
                next_n += 1
                new_id = f"f{next_n:03d}"
            nf.id = new_id
        taken.add(nf.id)

    # Rebuild to re-run FactFile-level validation (e.g. unique-id check).
    return FactFile(metadata=existing.metadata, facts=list(existing.facts) + new_facts)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Merge verification-pass facts into an existing FactFile."
    )
    parser.add_argument("--existing", required=True, help="Path to existing FactFile JSON.")
    parser.add_argument("--new", required=True, help="Path to raw verification response JSON.")
    parser.add_argument("--output", required=True, help="Path to write merged FactFile.")
    args = parser.parse_args(argv)

    existing = FactFile.from_json(args.existing)
    raw = Path(args.new).read_text(encoding="utf-8")
    try:
        merged = merge_facts(existing, raw)
    except ValidationError as exc:
        print(f"Merged FactFile failed validation: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Could not merge: {exc}", file=sys.stderr)
        return 1

    added = merged.facts[len(existing.facts):]
    merged.to_json(args.output)
    print(f"Merged: {len(added)} new facts added ({format_category_counts(added)})")
    print(f"Total: {len(merged.facts)} facts")
    print(f"Written to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
