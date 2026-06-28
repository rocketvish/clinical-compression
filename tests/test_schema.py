"""Validation, helper, and reconstruction tests for the clinical fact schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema.fact_schema import (
    DocumentMetadata,
    Fact,
    FactCategory,
    FactFile,
    FactSource,
    NoteType,
)

FIXTURE = Path(__file__).parent / "fixtures" / "example_extraction.json"

EXPECTED_RECONSTRUCTION = (
    "PATIENT: 67-year-old male\n"
    "\n"
    "ALERTS: Allergic to penicillin (anaphylaxis).\n"
    "\n"
    "DIAGNOSES: Type 2 diabetes (diagnosed 2019).\n"
    "\n"
    "MEDICATIONS: Metformin 500mg BID, increased from 250mg on 2024-01-10 "
    "due to inadequate glycemic control.\n"
    "\n"
    "RESULTS: HbA1c 7.2% (2024-03-15), up from 6.8%.\n"
    "\n"
    "CLINICAL REASONING: Concerning for early diabetic nephropathy.\n"
    "\n"
    "PENDING: Plan to order urine albumin test.\n"
    "\n"
    "CONTEXT: Denies chest pain."
)


@pytest.fixture
def fact_file() -> FactFile:
    return FactFile.from_json(FIXTURE)


def make_fact(**overrides) -> Fact:
    """Build a minimal valid Fact, overriding fields as needed."""
    base = dict(
        id="f001",
        category=FactCategory.CATEGORICAL,
        subcategory="patient_identifier",
        content="Patient is a 67-year-old male",
        entities=["patient"],
        source=FactSource.PHYSICIAN_ASSESSED,
    )
    base.update(overrides)
    return Fact(**base)


# ---------------------------------------------------------------------------
# Loading & helpers
# ---------------------------------------------------------------------------


def test_fixture_loads_and_validates(fact_file: FactFile):
    assert fact_file.metadata.note_type is NoteType.PROGRESS_NOTE
    assert fact_file.metadata.document_id == "example-001"
    assert len(fact_file.facts) == 13


def test_summary(fact_file: FactFile):
    summary = fact_file.summary()
    assert summary["total"] == 13
    assert summary["by_category"] == {
        "categorical": 5,
        "temporal": 3,
        "quantitative": 2,
        "clinical_reasoning": 3,
    }
    assert summary["by_subcategory"]["medication_dosage"] == 1
    assert summary["by_subcategory"]["negated_fact"] == 1


def test_query_helpers(fact_file: FactFile):
    assert {f.id for f in fact_file.get_facts_by_group("g002")} == {
        "f004", "f005", "f010", "f011",
    }
    assert len(fact_file.get_facts_by_category(FactCategory.TEMPORAL)) == 3
    negated = fact_file.get_negated_facts()
    assert len(negated) == 1 and negated[0].id == "f006"


def test_json_roundtrip(fact_file: FactFile, tmp_path: Path):
    out = tmp_path / "roundtrip.json"
    fact_file.to_json(out)
    assert FactFile.from_json(out) == fact_file


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------


def test_subcategory_must_match_category():
    with pytest.raises(ValidationError, match="not valid for category"):
        make_fact(category=FactCategory.CATEGORICAL, subcategory="lab_value")


def test_duplicate_ids_rejected():
    meta = DocumentMetadata(document_id="d", note_type=NoteType.OTHER)
    with pytest.raises(ValidationError, match="Duplicate fact ids"):
        FactFile(metadata=meta, facts=[make_fact(id="x"), make_fact(id="x")])


def test_entities_must_be_non_empty():
    with pytest.raises(ValidationError):
        make_fact(entities=[])


def test_values_may_be_empty():
    assert make_fact(values=[]).values == []


def test_tag_format_enforced():
    with pytest.raises(ValidationError, match="Malformed tag"):
        make_fact(tags=["notacategory:detail"])
    # A well-formed tag is accepted.
    assert make_fact(tags=["temporal:diagnosed_2019"]).tags == ["temporal:diagnosed_2019"]


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        make_fact(unexpected="boom")


# ---------------------------------------------------------------------------
# Negation rule
# ---------------------------------------------------------------------------


def test_negated_without_cue_rejected():
    with pytest.raises(ValidationError, match="negation language"):
        make_fact(
            subcategory="reported_symptom",
            content="chest pain",
            entities=["chest pain"],
            negated=True,
        )


def test_negated_with_cue_accepted():
    f = make_fact(
        subcategory="negated_fact",
        content="Patient denies chest pain",
        entities=["chest pain"],
        source=FactSource.PATIENT_REPORTED,
        negated=True,
    )
    assert f.negated is True


def test_negated_with_medical_convention_cue_accepted():
    # Medical-convention negation: "afebrile" means "no fever" and counts as
    # explicit negation language without an English negation word.
    f = make_fact(
        subcategory="negated_fact",
        content="Patient is afebrile",
        entities=["fever"],
        negated=True,
    )
    assert f.negated is True


def test_negated_diagnosis_is_orthogonal_to_negated_fact():
    # "no history of seizures": a negated previous_diagnosis, NOT negated_fact.
    f = make_fact(
        subcategory="previous_diagnosis",
        content="No history of seizures",
        entities=["seizures"],
        negated=True,
    )
    assert f.subcategory == "previous_diagnosis" and f.negated is True


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


def test_reconstruct_golden(fact_file: FactFile):
    assert fact_file.reconstruct() == EXPECTED_RECONSTRUCTION


def test_reconstruct_sections_in_order(fact_file: FactFile):
    out = fact_file.reconstruct()
    labels = ["PATIENT", "ALERTS", "DIAGNOSES", "MEDICATIONS", "RESULTS",
              "CLINICAL REASONING", "PENDING", "CONTEXT"]
    positions = [out.index(f"{label}:") for label in labels]
    assert positions == sorted(positions)


def test_reconstruct_no_double_render(fact_file: FactFile):
    out = fact_file.reconstruct()
    # The explanatory_link is folded into MEDICATIONS and must not also appear
    # under CLINICAL REASONING.
    assert out.count("due to inadequate glycemic control") == 1
    assert out.count("Concerning for early diabetic nephropathy") == 1


def test_reconstruct_negation_language_preserved(fact_file: FactFile):
    context_line = [
        line for line in fact_file.reconstruct().splitlines()
        if line.startswith("CONTEXT:")
    ][0]
    assert "Denies" in context_line


def test_reconstruct_omits_empty_sections():
    meta = DocumentMetadata(document_id="d", note_type=NoteType.OTHER)
    ff = FactFile(metadata=meta, facts=[
        make_fact(id="f001", subcategory="patient_identifier",
                  content="Patient is a 40-year-old female", entities=["patient"]),
    ])
    out = ff.reconstruct()
    assert out == "PATIENT: 40-year-old female"
    for absent in ["ALERTS", "DIAGNOSES", "MEDICATIONS", "RESULTS", "PENDING", "CONTEXT"]:
        assert absent not in out


def test_reconstruct_orphan_dosage_renders_drug_and_dose():
    # A medication_dosage with no associated drug_name fact must still render
    # as "drug + dose" in MEDICATIONS, not be dropped or stranded.
    meta = DocumentMetadata(document_id="d", note_type=NoteType.OTHER)
    ff = FactFile(metadata=meta, facts=[
        Fact(id="f001", category=FactCategory.QUANTITATIVE,
             subcategory="medication_dosage", content="Metformin 500mg twice daily",
             entities=["metformin"], values=["500mg", "BID"],
             source=FactSource.PHYSICIAN_ASSESSED),
    ])
    assert ff.reconstruct() == "MEDICATIONS: Metformin 500mg BID."
