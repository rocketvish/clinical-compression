"""Tests for the local fact extraction toolkit (prompts, validate, merge)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.extraction.merge import merge_facts
from src.extraction.prompts import (
    WORKED_EXAMPLE_JSON,
    build_extraction_prompt,
    build_system_prompt,
    build_verification_prompt,
)
from src.extraction.validate import validate_response
from src.schema.fact_schema import (
    Fact,
    FactCategory,
    FactFile,
    FactSource,
    NoteType,
    SUBCATEGORY_MAP,
)

FIXTURE = Path(__file__).parent / "fixtures" / "example_extraction.json"


def _example_json() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def make_fact(id_: str, **overrides) -> Fact:
    base = dict(
        id=id_,
        category=FactCategory.CATEGORICAL,
        subcategory="patient_identifier",
        content="Patient is a 60-year-old male",
        entities=["patient"],
        source=FactSource.PHYSICIAN_ASSESSED,
    )
    base.update(overrides)
    return Fact(**base)


def existing_factfile() -> FactFile:
    meta = {"document_id": "d", "note_type": NoteType.PROGRESS_NOTE}
    return FactFile(metadata=meta, facts=[make_fact(f"f00{i}") for i in range(1, 6)])


# A single missing lab_value fact, as the verification pass would return it.
NEW_LAB_FACT = """[
  {
    "id": "f006",
    "category": "quantitative",
    "subcategory": "lab_value",
    "content": "Potassium 4.2 mEq/L",
    "span": "K+ 4.2",
    "entities": ["potassium"],
    "values": ["4.2 mEq/L"],
    "tags": [],
    "source": "physician_assessed",
    "negated": false,
    "group_id": null
  }
]"""


# ---------------------------------------------------------------------------
# 1. System prompt content
# ---------------------------------------------------------------------------


def test_system_prompt_has_role_and_output_format():
    sp = build_system_prompt()
    assert "You are a clinical fact extractor." in sp
    assert "Return ONLY valid JSON matching the FactFile structure" in sp
    # Hardened JSON-only constraint for the extraction (object) pass.
    assert "Start your response with { and end it with }" in sp


def test_system_prompt_lists_all_categories_and_subcategories():
    sp = build_system_prompt()
    for label in ["Categorical", "Temporal", "Quantitative", "Clinical Reasoning"]:
        assert label in sp
    for subs in SUBCATEGORY_MAP.values():
        for sub in subs:
            assert sub in sp, f"missing subcategory {sub}"


def test_system_prompt_lists_all_sources():
    sp = build_system_prompt()
    for source in FactSource:
        assert source.value in sp


def test_system_prompt_has_all_decomposition_rules():
    sp = build_system_prompt()
    markers = [
        "1. ONE ENTITY PER FACT",
        "2. ATOMIC FACTS",
        "3. GROUP_ID",
        "4. NEGATION",
        "5. VERBATIM SPAN",
        "6. SOURCE ATTRIBUTION",
        "7. MULTIPLE VALUES",
        "8. TAGS",
        "9. EXTRACT PATIENT-SPECIFIC FACTS ONLY",
        "10. PRESERVE DISEASE QUALIFIERS",
        "11. TREATMENT REGIMENS ARE NOT DRUGS",
        "12. DEDUPLICATE FACTS",
        "13. DIAGNOSIS HIERARCHY",
        "14. PROGRESSIVE CONDITIONS",
    ]
    for marker in markers:
        assert marker in sp, f"missing rule: {marker}"


def test_system_prompt_embeds_worked_example():
    sp = build_system_prompt()
    assert "example-001" in sp
    assert "Patient denies chest pain" in sp


# ---------------------------------------------------------------------------
# 2. Extraction prompt assembly
# ---------------------------------------------------------------------------


def test_extraction_prompt_includes_text_and_metadata():
    prompt = build_extraction_prompt(
        document_text="THE DOCUMENT BODY",
        document_id="case-7",
        note_type="case_report",
        date="2024-01-01",
        author_role="resident",
        source_dataset="manual",
    )
    assert "<SYSTEM>" in prompt and "<USER>" in prompt
    for token in ["THE DOCUMENT BODY", "case-7", "case_report",
                  "2024-01-01", "resident", "manual"]:
        assert token in prompt


def test_extraction_prompt_uses_unknown_for_missing_optionals():
    prompt = build_extraction_prompt("body", "id1")
    assert "date: unknown" in prompt
    assert "author_role: unknown" in prompt


# ---------------------------------------------------------------------------
# 3. Verification prompt assembly
# ---------------------------------------------------------------------------


def test_verification_prompt_includes_document_and_facts():
    prompt = build_verification_prompt("DOCBODY", '{"facts": []}')
    assert "DOCBODY" in prompt
    assert '{"facts": []}' in prompt
    assert "MISSING" in prompt
    assert "JSON array" in prompt
    # Hardened JSON-only constraint for the verification (array) pass.
    assert "Start your response with [ and end it with ]" in prompt


# ---------------------------------------------------------------------------
# 4. JSON cleaning in validate_response
# ---------------------------------------------------------------------------


def test_validate_clean_json():
    ff = validate_response(_example_json())
    assert len(ff.facts) == 13
    assert ff.metadata.document_id == "example-001"


def test_validate_strips_code_fences():
    fenced = "```json\n" + _example_json() + "\n```"
    ff = validate_response(fenced)
    assert len(ff.facts) == 13


def test_validate_strips_preamble_and_postamble():
    wrapped = (
        "Here are the extracted facts:\n"
        + _example_json()
        + "\nLet me know if you need anything else."
    )
    ff = validate_response(wrapped)
    assert len(ff.facts) == 13


def test_validate_invalid_json_raises():
    with pytest.raises(ValueError):
        validate_response("{ this is not valid json }")


def test_validate_no_json_raises():
    with pytest.raises(ValueError):
        validate_response("there is no json here at all")


def test_validate_schema_violation_raises():
    bad = (
        '{"metadata": {"document_id": "d", "note_type": "progress_note"}, '
        '"facts": [{"id": "f1", "category": "categorical", '
        '"subcategory": "lab_value", "content": "x", "entities": ["e"], '
        '"source": "unknown"}]}'
    )
    with pytest.raises(ValidationError):
        validate_response(bad)


# ---------------------------------------------------------------------------
# 5. Merge logic
# ---------------------------------------------------------------------------


def test_merge_appends_new_facts():
    existing = existing_factfile()
    merged = merge_facts(existing, NEW_LAB_FACT)
    assert len(merged.facts) == 6
    assert merged.facts[-1].id == "f006"
    assert merged.facts[-1].category is FactCategory.QUANTITATIVE


def test_merge_renumbers_id_collisions():
    existing = existing_factfile()
    colliding = NEW_LAB_FACT.replace('"id": "f006"', '"id": "f003"')
    merged = merge_facts(existing, colliding)
    assert len(merged.facts) == 6
    # The new fact collided with existing f003 and was renumbered past the max.
    assert merged.facts[-1].id == "f006"
    # The original f003 is untouched.
    assert {f.id for f in existing.facts} <= {f.id for f in merged.facts}


def test_merge_revalidates_and_counts():
    existing = existing_factfile()
    merged = merge_facts(existing, NEW_LAB_FACT)
    # Re-validation produced a valid FactFile with unique ids.
    assert len(set(f.id for f in merged.facts)) == len(merged.facts)
    added = merged.facts[len(existing.facts):]
    assert [f.category.value for f in added] == ["quantitative"]


def test_merge_handles_fenced_array():
    existing = existing_factfile()
    merged = merge_facts(existing, "```json\n" + NEW_LAB_FACT + "\n```")
    assert len(merged.facts) == 6


def test_merge_handles_prose_around_array():
    existing = existing_factfile()
    wrapped = "Here are the missing facts:\n" + NEW_LAB_FACT + "\nThat's everything."
    merged = merge_facts(existing, wrapped)
    assert len(merged.facts) == 6
    assert merged.facts[-1].subcategory == "lab_value"


def test_merge_empty_array_is_noop():
    existing = existing_factfile()
    merged = merge_facts(existing, "[]")
    assert merged == existing
    assert len(merged.facts) == 5


# ---------------------------------------------------------------------------
# Drift guard: the embedded worked example must match the schema fixture.
# ---------------------------------------------------------------------------


def test_embedded_worked_example_matches_fixture():
    embedded = validate_response(WORKED_EXAMPLE_JSON)
    assert embedded == FactFile.from_json(FIXTURE)
