# Fact Extractor — Implementation Spec

## Instructions

Before writing code, outline your implementation plan: how you'll structure the modules, the prompt templates, the CLI tools, and any design decisions beyond what's specified. Then wait for my approval before implementing.

## Repo & Environment

```
Repo: clinical-compression (already cloned)
Python: 3.12
Existing code: src/schema/fact_schema.py (Pydantic schema — import and use it)
No new external dependencies needed — this is all local tooling.
```

Target file structure:
```
src/extraction/__init__.py                — re-exports
src/extraction/prompts.py                 — system prompt, user prompt builders, verification prompt builder
src/extraction/validate.py                — validate raw JSON against schema
src/extraction/merge.py                   — merge verification pass facts into existing FactFile
src/extraction/build_prompt.py            — CLI: generate extraction prompt to paste into claude.ai
src/extraction/build_verify_prompt.py     — CLI: generate verification prompt to paste into claude.ai
tests/test_extraction.py                  — tests
```

## Overview

Build a local fact extraction toolkit for use with a Claude Max subscription. No API calls — instead, generate prompts the user pastes into claude.ai and validate/merge the responses locally.

### Workflow

```
Step 1: Generate extraction prompt
  python -m src.extraction.build_prompt --input case.txt --note-type case_report
  → Prints full prompt (system + user) to terminal. User copies into claude.ai.

Step 2: Validate response
  User copies JSON response from claude.ai, saves to a file.
  python -m src.extraction.validate --input raw_response.json --output facts.json
  → Validates against FactFile schema. Prints summary. Writes clean FactFile.

Step 3: Generate verification prompt
  python -m src.extraction.build_verify_prompt --input case.txt --facts facts.json
  → Prints verification prompt to terminal. User copies into claude.ai.

Step 4: Merge verification results
  User copies JSON response (array of additional facts), saves to a file.
  python -m src.extraction.merge --existing facts.json --new verify_response.json --output facts_final.json
  → Merges new facts, re-validates, writes final FactFile. Prints what was added.
```

## Module: prompts.py

This module builds the prompt text. Three public functions:

### build_system_prompt() -> str

Returns the full system prompt. Static — doesn't depend on any input. Contains:

**1. Role definition:**

```
You are a clinical fact extractor. Given a medical document, you extract every clinically relevant patient-specific fact into a structured JSON format. You are exhaustive, precise, and follow strict decomposition rules.
```

**2. Full taxonomy listing:**

Include every category and its subcategories:

Categorical: previous_diagnosis, reported_symptom, patient_identifier, family_history, behavior, code_status, negated_fact, allergy, infection_precaution, fall_risk, drug_name, device_type

Temporal: medication_timing, event_sequence, lab_trajectory, dosage_change, time_since_event

Quantitative: lab_value, vital_sign, medication_dosage

Clinical Reasoning: considered_rejected_diagnosis, explanatory_link, conditional_fact, uncertainty_marker, pending_planned_task

**3. Source attribution values:** patient_reported, physician_assessed, outside_records, nursing_note, family_reported, unknown

**4. Decomposition rules (include verbatim):**

```
DECOMPOSITION RULES:

1. ONE ENTITY PER FACT. "Patient takes tylenol 200mg and metformin 10mg" becomes TWO facts, each with a single entity and its associated values. Never put multiple unrelated entities in one fact entry.

2. ATOMIC FACTS. Compound clinical statements are decomposed into separate facts by category. "Metformin increased from 250mg to 500mg on 2024-01-10 due to inadequate glycemic control" becomes:
   - categorical/drug_name: "Patient takes metformin"
   - quantitative/medication_dosage: "Metformin 500mg" (current dose)
   - temporal/dosage_change: "Metformin increased from 250mg to 500mg on 2024-01-10"
   - clinical_reasoning/explanatory_link: "Metformin increased due to inadequate glycemic control"
   All share the same group_id.

3. GROUP_ID links facts decomposed from the same clinical statement. Each fact in a group is independently meaningful. Use format "g001", "g002", etc. Facts that stand alone have group_id: null.

4. NEGATION. Any negated clinical fact (denies, no history of, ruled out, absent, etc.) MUST have negated: true. The content field MUST include the negation word. "Denies chest pain" → content: "Patient denies chest pain", negated: true. The entities field contains the concept being negated: ["chest pain"].

5. VERBATIM SPAN. The span field captures the original text from the document, preserving abbreviations and formatting. If the fact comes from multiple non-contiguous spans, capture the most informative one.

6. SOURCE ATTRIBUTION. Set the source field based on who asserted the fact:
   - patient_reported: patient's own statements
   - physician_assessed: physician's clinical judgment or documentation
   - outside_records: from external records or prior documentation
   - nursing_note: nursing documentation
   - family_reported: family member statements
   - unknown: cannot determine source

7. MULTIPLE VALUES on one entity follow chronological order for changes (old first, new second) and co-equal listing for current state. Content must state direction explicitly for changes.

8. TAGS for cross-cutting concerns use format "category:detail" (e.g. "temporal:started_2024-03-15"). Use tags when a fact has a secondary category relationship but its primary category is something else.

9. EXTRACT PATIENT-SPECIFIC FACTS ONLY. Do not extract general medical knowledge, literature findings, study results, or guideline recommendations. Extract only facts about the specific patient in the case.
```

**5. Worked example:**

Include the full worked example from the schema spec — the synthetic clinical paragraph and its 13-fact extraction. This is the few-shot that constrains output format. Embed the complete JSON example from tests/fixtures/example_extraction.json.

**6. Output format:**

```
Return ONLY valid JSON matching the FactFile structure. No markdown fencing, no explanation, no preamble, no postamble. Just the JSON object with "metadata" and "facts" keys.
```

Include the FactFile structure showing all field names and types as a reference.

### build_extraction_prompt(document_text: str, document_id: str, note_type: str = "other", date: str | None = None, author_role: str | None = None, source_dataset: str = "manual") -> str

Returns the combined prompt to paste into claude.ai. Format:

```
<SYSTEM>
{system_prompt}
</SYSTEM>

<USER>
Extract all patient-specific clinical facts from this document.

Document metadata:
- document_id: {document_id}
- note_type: {note_type}
- date: {date or "unknown"}
- author_role: {author_role or "unknown"}
- source_dataset: {source_dataset}

Document text:
---
{document_text}
---

Return the complete FactFile JSON with metadata and all extracted facts.
</USER>
```

### build_verification_prompt(document_text: str, existing_facts_json: str) -> str

Returns the verification prompt to paste into claude.ai. Format:

```
<SYSTEM>
{system_prompt}
</SYSTEM>

<USER>
Review this clinical document against the facts already extracted. Identify any clinically relevant patient-specific facts that are MISSING from the extraction.

Focus especially on:
- Negated facts (things the patient denies or does not have)
- Temporal relationships (when things started, stopped, changed)
- Clinical reasoning (why decisions were made, what was considered and rejected)
- Conditional instructions (if X then Y)
- Source attributions that may be wrong
- Quantitative values (lab numbers, vitals, dosages) that were missed
- Drug interactions or risk factors mentioned specifically about this patient

Document text:
---
{document_text}
---

Already extracted facts:
---
{existing_facts_json}
---

Return ONLY a JSON array of additional Fact objects that are missing. Use fact IDs continuing from the highest existing ID. Use group_ids continuing from the highest existing group. If no facts are missing, return an empty array: []

No markdown fencing, no explanation. Just the JSON array.
</USER>
```

## Module: validate.py

### validate_response(raw_json: str) -> FactFile

1. Strip markdown code fences if present (```json ... ```, or just ```)
2. Strip any text before the first `{` and after the last `}`  (catches preamble/postamble the model might add)
3. Parse JSON
4. Validate against FactFile schema via `FactFile.model_validate(parsed)`
5. Return the validated FactFile

If validation fails, print the specific Pydantic validation errors clearly so the user knows what to fix (or can ask claude.ai to fix it).

### CLI: python -m src.extraction.validate

```
Arguments:
  --input   Path to raw JSON response file (required)
  --output  Path to write validated FactFile (required)
```

On success, print:
```
Validated: {n} facts ({by_category_counts})
Written to: {output_path}
```

On failure, print validation errors and exit with code 1.

## Module: merge.py

### merge_facts(existing: FactFile, new_facts_json: str) -> FactFile

1. Strip markdown fences and parse the new facts JSON (expected: a JSON array of Fact objects)
2. Validate each new fact individually against the Fact schema
3. Check for ID collisions with existing facts — if any, re-number the new facts
4. Append new facts to existing FactFile
5. Re-validate the complete FactFile (catches any issues the merge introduced)
6. Return the merged FactFile

### CLI: python -m src.extraction.merge

```
Arguments:
  --existing  Path to existing FactFile JSON (required)
  --new       Path to raw verification response JSON (required)
  --output    Path to write merged FactFile (required)
```

On success, print:
```
Merged: {n_new} new facts added ({by_category_counts})
Total: {n_total} facts
Written to: {output_path}
```

## Module: build_prompt.py (CLI)

```
Arguments:
  --input          Path to document text file (required)
  --document-id    Document ID (default: derived from input filename)
  --note-type      Note type enum value (default: "other")
  --date           Document date (optional)
  --author-role    Author role (optional)
  --source-dataset Source dataset name (default: "manual")
  --output         Write prompt to file instead of printing (optional)
```

Reads the document text, calls `build_extraction_prompt()`, prints to stdout (or writes to file if --output given). The user copies the output and pastes into claude.ai.

## Module: build_verify_prompt.py (CLI)

```
Arguments:
  --input   Path to document text file (required)
  --facts   Path to existing FactFile JSON (required)
  --output  Write prompt to file instead of printing (optional)
```

Reads the document and the existing facts, calls `build_verification_prompt()`, prints to stdout. The user copies and pastes into claude.ai.

## NoteType addition

Add `case_report` to the NoteType enum in fact_schema.py.

## Tests

### test_extraction.py

1. **System prompt content:** Verify `build_system_prompt()` output contains all required sections: role definition, all 4 categories, all subcategories, all 9 decomposition rules, the worked example JSON, output format instructions.

2. **Extraction prompt assembly:** Call `build_extraction_prompt()` with test inputs, verify document text and all metadata fields appear in output.

3. **Verification prompt assembly:** Call `build_verification_prompt()` with test inputs, verify both document text and existing facts JSON appear in output.

4. **JSON cleaning in validate:** Test `validate_response()` with:
   - Clean JSON (passes)
   - JSON wrapped in ```json ... ``` fences (passes after stripping)
   - JSON with preamble text like "Here are the extracted facts:" (passes after stripping)
   - Invalid JSON (fails with clear error)
   - Valid JSON that fails schema validation (fails with Pydantic errors)

5. **Merge logic:** Create a FactFile with facts f001-f005, merge new facts, verify:
   - New facts appended correctly
   - ID collisions detected and re-numbered
   - Combined FactFile validates
   - Category counts are correct

6. **Merge with empty array:** Verify merging an empty array returns the original FactFile unchanged.

## Notes

- The prompts will be long when printed (~3000-4000 tokens for the system prompt with the worked example). That's fine — claude.ai handles this easily within Max plan limits.
- When pasting into claude.ai, the user can paste the entire output (system + user sections) as a single message. The model will understand the structure from the XML-style tags.
- For the proof of concept, we're processing 5-10 cases manually. When we scale to ER-REASON (hundreds of cases), we'll add an API runner module that reuses the same prompts from prompts.py. The prompts are the investment — the delivery mechanism is swappable.
- PDF-to-text conversion is out of scope. The user provides plain text files.
