# Fact Extraction Schema — Implementation Spec

## Instructions

Before writing code, outline your implementation plan: file structure, class hierarchy, validator logic, and any design decisions you'd make beyond what's specified. Then wait for my approval before implementing.

## Repo & Environment

```
Repo: clinical-compression (already cloned)
Python: 3.12
Dependencies: pydantic v2 (add to requirements.txt or pyproject.toml, whichever exists)
Use pytest for tests.
```

Target file structure:
```
src/schema/fact_schema.py              — the schema (enums, models, validators, helpers)
tests/fixtures/example_extraction.json — the example output from this spec
tests/test_schema.py                   — validation tests
```

## Overview

Build a Pydantic schema for extracting structured clinical facts from medical documents. This schema serves as the ground truth for evaluating context compression techniques on clinical text.

## Data Model

### Top-level: `FactFile`

A fact file contains document metadata and a list of extracted facts.

```
FactFile
├── metadata: DocumentMetadata
└── facts: list[Fact]
```

### DocumentMetadata

Header information about the source document. Lightweight — just enough for analysis by note type.

Fields:
- `document_id`: str — unique identifier for the source document
- `note_type`: NoteType enum — type of clinical note
- `date`: str | None — document date if available (ISO format YYYY-MM-DD)
- `author_role`: str | None — e.g. "attending physician", "resident", "nurse"
- `sections_present`: list[str] — section headers found in the document (e.g. ["HPI", "Medications", "Assessment/Plan"])
- `source_dataset`: str | None — e.g. "er-reason", "synthetic", "enriched"

NoteType enum values:
- `discharge_summary`
- `progress_note`
- `history_and_physical`
- `consult`
- `imaging_report`
- `procedure_note`
- `nursing_note`
- `er_provider_note`
- `echocardiography_report`
- `other`

### Fact

A single atomic clinical fact. Compound clinical statements are decomposed into multiple Fact entries linked by `group_id`.

Fields:
- `id`: str — unique fact identifier within the file (e.g. "f001", "f002")
- `category`: FactCategory enum — primary classification
- `subcategory`: str — specific subcategory within the category (see allowed values below)
- `content`: str — normalized, human-readable statement of the fact (e.g. "Patient denies history of chest pain")
- `span`: str | None — verbatim text from the source document that this fact was extracted from, preserving abbreviations and formatting
- `entities`: list[str] — clinical entities involved (drug names, conditions, lab names, devices)
- `values`: list[str] — quantitative values including units (e.g. ["500mg", "BID", "7.2%"])
- `tags`: list[str] — cross-cutting concerns from other categories, formatted as "category:detail" (e.g. "temporal:started_2024-03-15", "quantitative:500mg")
- `source`: FactSource enum — who asserted this fact
- `negated`: bool — whether this fact is a negation (e.g. "denies chest pain" = true). Default false.
- `group_id`: str | None — links atomic facts decomposed from the same compound clinical statement. Facts sharing a group_id originated from the same source text. None if the fact stands alone.

### FactCategory enum

```
categorical
temporal
quantitative
clinical_reasoning
```

Note: "Meta" from the taxonomy (source attribution, entity-value binding) is expressed through fields on each fact (`source` field) and through the scoring rubric, not as a separate category for extraction.

### Allowed subcategory values per category

Categorical:
- `previous_diagnosis`
- `reported_symptom`
- `patient_identifier`
- `family_history`
- `behavior`
- `code_status`
- `negated_fact`
- `allergy`
- `infection_precaution`
- `fall_risk`
- `drug_name`
- `device_type`

Temporal:
- `medication_timing`
- `event_sequence`
- `lab_trajectory`
- `dosage_change`
- `time_since_event`

Quantitative:
- `lab_value`
- `vital_sign`
- `medication_dosage`

Clinical Reasoning:
- `considered_rejected_diagnosis`
- `conditional_fact`
- `explanatory_link`
- `uncertainty_marker`
- `pending_planned_task`

### FactSource enum

```
patient_reported
physician_assessed
outside_records
nursing_note
family_reported
unknown
```

## Validation Rules

1. `subcategory` must be valid for the given `category` — add a Pydantic model_validator that checks this
2. If `negated` is true, `content` should express the negation explicitly (e.g. "Patient denies chest pain", not just "chest pain")
3. `id` values must be unique within a FactFile — add a model_validator on FactFile
4. `entities` should not be empty — every fact involves at least one clinical entity
5. `values` can be empty (categorical facts like "patient is male" have no quantitative value)
6. `tags` format: each tag must match the pattern "category:detail" where category is one of the FactCategory values

## Example Output

Given this clinical text:

> "Patient is a 67-year-old male with history of Type 2 diabetes (diagnosed 2019), currently on metformin 500mg BID. Denies chest pain. HbA1c 7.2% on 2024-03-15, up from 6.8% in 2023-09. Allergic to penicillin (anaphylaxis). Metformin was increased from 250mg to 500mg on 2024-01-10 due to inadequate glycemic control. Concerning for early diabetic nephropathy — plan to order urine albumin."

Expected facts:

```json
{
  "metadata": {
    "document_id": "example-001",
    "note_type": "progress_note",
    "date": "2024-03-15",
    "author_role": "attending physician",
    "sections_present": ["HPI", "Assessment/Plan"],
    "source_dataset": "synthetic"
  },
  "facts": [
    {
      "id": "f001",
      "category": "categorical",
      "subcategory": "patient_identifier",
      "content": "Patient is a 67-year-old male",
      "span": "67-year-old male",
      "entities": ["patient"],
      "values": ["67"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": null
    },
    {
      "id": "f002",
      "category": "categorical",
      "subcategory": "previous_diagnosis",
      "content": "Patient has Type 2 diabetes",
      "span": "history of Type 2 diabetes (diagnosed 2019)",
      "entities": ["Type 2 diabetes"],
      "values": [],
      "tags": ["temporal:diagnosed_2019"],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g001"
    },
    {
      "id": "f003",
      "category": "temporal",
      "subcategory": "time_since_event",
      "content": "Type 2 diabetes diagnosed in 2019",
      "span": "diagnosed 2019",
      "entities": ["Type 2 diabetes"],
      "values": ["2019"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g001"
    },
    {
      "id": "f004",
      "category": "categorical",
      "subcategory": "drug_name",
      "content": "Patient is currently on metformin",
      "span": "currently on metformin 500mg BID",
      "entities": ["metformin"],
      "values": [],
      "tags": ["quantitative:500mg_BID"],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f005",
      "category": "quantitative",
      "subcategory": "medication_dosage",
      "content": "Metformin 500mg twice daily",
      "span": "metformin 500mg BID",
      "entities": ["metformin"],
      "values": ["500mg", "BID"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f006",
      "category": "categorical",
      "subcategory": "negated_fact",
      "content": "Patient denies chest pain",
      "span": "Denies chest pain",
      "entities": ["chest pain"],
      "values": [],
      "tags": [],
      "source": "patient_reported",
      "negated": true,
      "group_id": null
    },
    {
      "id": "f007",
      "category": "quantitative",
      "subcategory": "lab_value",
      "content": "HbA1c is 7.2%",
      "span": "HbA1c 7.2% on 2024-03-15",
      "entities": ["HbA1c"],
      "values": ["7.2%"],
      "tags": ["temporal:2024-03-15"],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g003"
    },
    {
      "id": "f008",
      "category": "temporal",
      "subcategory": "lab_trajectory",
      "content": "HbA1c increased from 6.8% to 7.2% between September 2023 and March 2024",
      "span": "HbA1c 7.2% on 2024-03-15, up from 6.8% in 2023-09",
      "entities": ["HbA1c"],
      "values": ["6.8%", "7.2%"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g003"
    },
    {
      "id": "f009",
      "category": "categorical",
      "subcategory": "allergy",
      "content": "Patient is allergic to penicillin with anaphylaxis reaction",
      "span": "Allergic to penicillin (anaphylaxis)",
      "entities": ["penicillin"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": null
    },
    {
      "id": "f010",
      "category": "temporal",
      "subcategory": "dosage_change",
      "content": "Metformin increased from 250mg to 500mg on 2024-01-10",
      "span": "Metformin was increased from 250mg to 500mg on 2024-01-10",
      "entities": ["metformin"],
      "values": ["250mg", "500mg", "2024-01-10"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f011",
      "category": "clinical_reasoning",
      "subcategory": "explanatory_link",
      "content": "Metformin was increased due to inadequate glycemic control",
      "span": "due to inadequate glycemic control",
      "entities": ["metformin", "glycemic control"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f012",
      "category": "clinical_reasoning",
      "subcategory": "uncertainty_marker",
      "content": "Concerning for early diabetic nephropathy",
      "span": "Concerning for early diabetic nephropathy",
      "entities": ["diabetic nephropathy"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g004"
    },
    {
      "id": "f013",
      "category": "clinical_reasoning",
      "subcategory": "pending_planned_task",
      "content": "Plan to order urine albumin test",
      "span": "plan to order urine albumin",
      "entities": ["urine albumin"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g004"
    }
  ]
}
```

## Implementation Notes

- Use Pydantic v2 (BaseModel with model_validator)
- Use StrEnum for all enums (Python 3.11+ or backport)
- Include a `SUBCATEGORY_MAP: dict[FactCategory, list[str]]` constant that maps each category to its allowed subcategories — used in the validator and useful downstream as reference
- Include helper methods on FactFile:
  - `get_facts_by_category(category: FactCategory) -> list[Fact]`
  - `get_facts_by_group(group_id: str) -> list[Fact]`
  - `get_negated_facts() -> list[Fact]`
  - `summary() -> dict` — returns counts by category and subcategory
- Include a `to_json(path: Path)` and `from_json(path: Path)` on FactFile for serialization
- Put the example JSON above in a separate file `tests/fixtures/example_extraction.json` for validation testing
- Write a basic test that loads the example fixture and validates it against the schema

## Structural Conventions

### One entity per fact preserves binding

The most dangerous extraction failure is cross-wiring: "tylenol 200mg, metformin 10mg" stored as `entities: ["tylenol", "metformin"]` with `values: ["200mg", "10mg"]` and hoping positional order is enough. It's not — downstream consumers can't reliably reconstruct which value belongs to which entity.

**Rule: each fact entry binds one entity to its values.** "Patient takes tylenol 200mg and metformin 10mg" becomes two facts, each with a single entity and its associated values. They share a `group_id` because they originated from the same statement, but each fact is self-contained. If you read any single fact entry in isolation, the entity-value relationship is unambiguous.

### Multiple values on one entity

When a single entity has multiple values, order matters. Conventions:

- **Dosage changes:** `values` lists in chronological order — old value first, new value second. `values: ["250mg", "500mg"]` means 250mg → 500mg. The `content` field must state the direction explicitly ("increased from 250mg to 500mg").
- **Lab trajectories:** same convention — earliest value first, most recent last. `values: ["6.8%", "7.2%"]` means 6.8% → 7.2%.
- **Current state facts:** single value, no ordering ambiguity. `values: ["500mg", "BID"]` are co-equal descriptors of the current dosage.

### group_id links related facts, not dependent facts

Facts sharing a `group_id` were decomposed from the same clinical statement. Each fact in the group is independently meaningful. Deleting one fact from a group does not invalidate the others — "metformin increased from 250mg to 500mg due to inadequate glycemic control" produces a temporal fact (dosage change), a quantitative fact (current dosage), and a clinical reasoning fact (explanatory link), all in one group. Each stands alone.

The `group_id` exists for traceability (finding all facts from one source statement) and for reconstruction (reassembling the narrative). It is not a dependency relationship.

### Negated facts are positive entries with a flag

A negated fact is stored as a complete statement with `negated: true`. The `content` field must include the negation word ("Patient denies chest pain", not "chest pain"). The `entities` field contains the clinical concept being negated ("chest pain"). This means an entity appearing in the fact file does NOT imply the patient has that condition — always check the `negated` flag before interpreting.

## Reconstruction Guide

### How to read a fact file back into a clinical summary

A fact file is a bag of atomic facts. To reconstruct a readable clinical picture, group and layer them in this order:

**Step 1: Patient identity.** Filter `category: categorical, subcategory: patient_identifier`. This gives demographics and identifiers. Render as an opening line: "67-year-old male..."

**Step 2: Critical alerts.** Filter subcategories `allergy`, `infection_precaution`, `fall_risk`. These are safety-critical and go at the top, rendered prominently.

**Step 3: Active problem list.** Gather `previous_diagnosis` facts, cross-reference with related temporal facts (via `group_id` or matching entities) for onset dates. Render as: "Type 2 diabetes (diagnosed 2019), Hypertension (diagnosed 2021)."

**Step 4: Medications.** For each `drug_name` fact, find its associated `medication_dosage` fact (same `group_id` or matching entity). If a `dosage_change` or `medication_timing` fact exists for the same entity, include the trajectory. Render as: "Metformin 500mg BID (increased from 250mg on 2024-01-10)."

**Step 5: Recent results.** Gather `lab_value` and `vital_sign` facts. For labs with `lab_trajectory` facts (same entity), include the trend. Render as: "HbA1c 7.2% (2024-03-15), up from 6.8%."

**Step 6: Clinical reasoning.** Render `uncertainty_marker`, `considered_rejected_diagnosis`, `explanatory_link`, and `conditional_fact` entries. These preserve the physician's thinking. Render as: "Concerning for early diabetic nephropathy. Metformin increased due to inadequate glycemic control. If INR > 4, hold anticoagulation."

**Step 7: Pending actions.** Render `pending_planned_task` facts. These are forward-looking: "Plan to order urine albumin."

**Step 8: Context.** Render `behavior`, `family_history`, `code_status`, `negated_fact` entries as supporting context. Negated facts render with explicit negation: "Denies chest pain. Denies smoking."

### Reconstruction by group_id

An alternative reconstruction path: iterate over unique `group_id` values and render each group as a coherent statement by combining its atomic facts. For the metformin group (g002 in the example):

- drug_name: "Patient is currently on metformin"
- medication_dosage: "Metformin 500mg twice daily"
- dosage_change: "Metformin increased from 250mg to 500mg on 2024-01-10"
- explanatory_link: "Metformin was increased due to inadequate glycemic control"

Reconstructs to: "Patient is currently on metformin 500mg BID, increased from 250mg on 2024-01-10 due to inadequate glycemic control."

Ungrouped facts (group_id: null) are standalone and render individually.

### Programmatic reconstruction

Include a helper method `FactFile.reconstruct() -> str` that implements the step-by-step reconstruction above. This serves two purposes: verifying that the fact file is complete enough to reproduce the clinical picture, and generating readable summaries from the structured store for the verification layer (Layer 3 of the architecture).

**Output format:** Plain text with minimal section labels, no markdown or bullet points. Must be readable by clinicians and usable as context input to the verification layer. Example output for the worked example in this spec:

```
PATIENT: 67-year-old male

ALERTS: Allergic to penicillin (anaphylaxis).

DIAGNOSES: Type 2 diabetes (diagnosed 2019).

MEDICATIONS: Metformin 500mg BID, increased from 250mg on 2024-01-10 due to inadequate glycemic control.

RESULTS: HbA1c 7.2% (2024-03-15), up from 6.8%.

CLINICAL REASONING: Concerning for early diabetic nephropathy.

PENDING: Plan to order urine albumin test.

CONTEXT: Denies chest pain.
```

Section labels are uppercase single words. Facts within a section are separated by spaces. Omit sections with no facts. Grouped facts (shared group_id) are merged into single statements where possible.
