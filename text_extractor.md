# PROMPT 1 — Case Text Extractor (verbatim)

**Input:** A case report PDF, attached to the chat.

**Output:** A JSON file you save as `<case_id>_part1.json`. This file
will be consumed by Prompt 2 (anchor extraction) and Prompt 3 (filler
generation) as well as by the orchestration script.

---

You are extracting a clinical case report into two verbatim text sections
for a downstream NLP research project. Your only job is faithful
transcription — no analysis, no summarization, no editorial choices
beyond identifying which portions of the article are patient-specific
versus background material.

## What to extract

Read the attached PDF and partition its content into two regions:

**CASE TEXT (case_text field).** The patient-specific clinical content.
This typically includes:
  - Case presentation (HPI, ROS, examination findings on arrival)
  - Past medical history specific to this patient
  - Hospital course (events during the admission, day-by-day narrative)
  - Labs, imaging, procedures performed on this patient
  - Medications administered to this patient
  - Diagnostic reasoning specific to this case
  - Disposition / discharge planning for this patient

**EXCLUDED TEXT (excluded_text field).** Everything that is NOT
patient-specific narrative:
  - Abstract
  - Introduction / background / literature review
  - Discussion section (including pathophysiology overviews and
    references to other studies)
  - References / bibliography
  - Author affiliations, acknowledgments
  - Figure legends and table captions for non-patient-specific tables
  - Trial data cited from external studies (even if numerically
    specific — e.g., "rivaroxaban 20 mg daily in ROCKET-AF" is excluded
    because it refers to a trial, not to this patient)
  - Any commentary on guidelines or recommendations not implemented
    in THIS patient

## Critical rules for case_text

  1. **VERBATIM transcription.** Do not paraphrase. Do not summarize.
     Do not "clean up" awkward phrasing. Preserve original punctuation,
     capitalization, abbreviations, and paragraph breaks.

  2. **Preserve clinical headers used by the authors** (e.g.,
     "Hospital Course:", "Medications on Admission:", "Physical
     Examination:"). Do NOT include journal-article section
     headers (e.g., do not include "2. Case Presentation" as a
     heading — that's article structure, not clinical content).

  3. **Concatenate distinct patient-specific subsections** with a
     blank line between them.

  4. **Preserve numeric values exactly** (lab values, doses if stated
     for this patient, dates, durations). These are anchor candidates
     in downstream prompts.

  5. **If the article includes a patient-specific table** (e.g., a
     medication list), transcribe its contents as plain text. Use
     line breaks rather than table formatting. Example:
     "Home medications: aspirin 81 mg daily, prasugrel 10 mg daily, ..."

  6. **Do NOT extract trial doses or guideline doses.** If a paragraph
     mixes patient-specific narrative with cited trial data, include
     only the patient-specific sentences.

## Critical rules for excluded_text

Same verbatim rule applies — transcribe exactly. This field exists
so reviewers can audit that anchor extraction stayed within case_text.

If excluded_text would exceed ~8,000 tokens, you may truncate by
omitting the references section, but note this in audit_notes.

## Output schema

Return a single JSON object with this exact structure:

```json
{
  "case_metadata": {
    "title": "<full article title>",
    "source": "<citation: authors, journal, year, identifier>",
    "specialty": "<primary clinical specialty>",
    "patient_descriptor": "<e.g., '55-year-old male with atrial fibrillation'>",
    "primary_condition_category": "<one or two words: 'cardiology', 'infectious_disease', 'oncology', etc.>",
    "comorbidity_categories": ["<list of comorbidity category words, e.g., 'cardiovascular', 'renal', 'endocrine'>"],
    "case_text_token_count_estimate": <integer; rough word count of case_text>,
    "excluded_text_token_count_estimate": <integer>,
    "truncation_notes": "<empty string OR description of what was truncated>"
  },
  "case_text": "<the verbatim patient-specific content>",
  "excluded_text": "<the verbatim non-patient-specific content>"
}
```

The `primary_condition_category` and `comorbidity_categories` fields
are important for Prompt 3 (filler generation) — they let the filler
prompt match the patient profile in broad terms without naming
specific diagnoses. Examples:

  - A case about MRONJ in a breast cancer patient on bisphosphonates:
    primary_condition_category="oral_maxillofacial_surgery",
    comorbidity_categories=["oncology", "bone_metabolism"]

  - A case about anticoagulation bleeding in an AF patient:
    primary_condition_category="cardiology",
    comorbidity_categories=["cardiovascular", "renal", "endocrine",
                             "musculoskeletal"]

Use clinical-system-level abstractions, not specific diagnoses. Do
NOT include "atrial fibrillation" or "hypertension" or "diabetes" in
comorbidity_categories — those are diagnoses, and they will leak into
filler if listed here. Use the system-level category instead.

## Self-audit before returning

Before returning the JSON, verify:

  1. case_text is verbatim from the patient-specific sections (no
     paraphrase).
  2. excluded_text is verbatim from the non-patient-specific sections.
  3. The two together cover essentially all the article's prose
     content (the partition is exhaustive).
  4. No content appears in both — each sentence is in one or the
     other, not both.
  5. comorbidity_categories contains only system-level abstractions,
     NOT named diagnoses.
  6. JSON is well-formed (no unescaped quotes, no trailing commas).

If any check fails, revise before returning.

Begin now. Read the attached PDF and return only the JSON object.