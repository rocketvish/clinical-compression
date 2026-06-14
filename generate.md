You are assisting with a clinical NLP research project that tests
whether representation-level context compression preserves clinically
critical information in longitudinal patient records. Your task has
four parts: (1) extract the patient-specific case text verbatim,
(2) extract anchor facts following a strict four-category taxonomy,
(3) generate questions that test recovery of each anchor, and (4)
generate realistic clinical filler used to pad the case to various
context lengths.

Read the attached case report carefully before beginning. Identify
which portions are patient-specific (case presentation, hospital
course, medications, laboratory findings, disposition, and any
patient-specific clinical reasoning) versus non-patient-specific
(abstract, introduction, literature review, discussion, references,
acknowledgments, author affiliations, figure legends, tables of
trial data, generic background information). Only the
patient-specific portions are used for anchor extraction.

## PART 1: CASE TEXT EXTRACTION

Extract two fields:

  case_text: A VERBATIM transcription of the patient-specific case
    sections. Do not paraphrase, summarize, or edit. Preserve original
    punctuation, paragraph breaks, and clinical abbreviations. Do not
    include section headers from the journal article (e.g., do not
    include "2. Case Presentation" as a header), but DO preserve any
    internal clinical headers the authors used (e.g., "Hospital
    Course:", "Medications on Admission:"). Concatenate distinct
    patient-specific subsections with a blank line between them.

    The case_text is what the orchestration script will pad with
    clinical filler to create longer contexts. It MUST be verbatim
    because anchor 'text' fields will be quoted from it.

  excluded_text: A verbatim transcription of the non-patient-specific
    portions of the article (abstract, intro, discussion, etc.).
    Include this for auditing — a reviewer must be able to verify
    that anchor extraction stayed within case_text. May be truncated
    if exceptionally long, but flag truncation in audit_notes.

Both fields must be JSON-safe strings (escape newlines, quotes, etc.
properly).

## PART 2: ANCHOR FACT EXTRACTION

Extract anchor facts using exactly the four categories below. Anchors
must be drawn ONLY from case_text — not from excluded_text.

For each anchor, capture:
  - id (sequential A1, A2, A3...)
  - category (CAT / TEMP / QUANT / REAS)
  - subtype (see per-category subtypes below)
  - text (verbatim quote from case_text, ≤ 25 words)
  - location (presentation / hospital_course / labs / medications /
    disposition / other)
  - distinctiveness (low / medium / high — based on how unusual or
    specific the language is)
  - granularity (class / instance / qualifier / n/a)
  - paired_anchors (list of IDs of other anchors that form a
    granularity pair OR a quantitative-modifies-instance pair OR a
    trajectory-tracks-lab pair)
  - clinical_actionability (low / medium / high — would loss of this
    fact change clinical management?)
  - class_node_present (for CAT.instance anchors ONLY: true if
    case_text contains explicit class-level terminology for this
    instance, false if the class node is absent from case_text and
    must be inferred from clinical knowledge. For non-CAT.instance
    anchors, set to "n/a".)

### The four categories:

**CAT — Categorical facts.** Statements identifying entities, classes,
named diagnoses, named medications, organisms, anatomic locations,
critical alerts, allergies, and negated findings.

  Subtypes:
    CAT.class     — Class or category level (drug class, organism
                    class, anatomic region, diagnosis category).
    CAT.instance  — Specific named entity (drug agent, organism
                    species, named diagnosis, exact anatomy).
    CAT.qualifier — Modifier attached to an instance that changes
                    clinical management.
    CAT.alert     — Critical safety alert (allergy with severity,
                    code status, fall risk, precautions).
    CAT.negated   — Negated finding or status.

**TEMP — Temporal facts.** When, how long, in what order, or how
something changed over time.

  Subtypes:
    TEMP.date       — Absolute date or timepoint.
    TEMP.duration   — Length of time.
    TEMP.since      — Time elapsed since a referenced event.
    TEMP.status     — Status-change qualifier (recently discontinued,
                      previously refused, newly diagnosed).
    TEMP.sequence   — Ordering of events.
    TEMP.trajectory — Trend over time (Hgb trending down, INR rising).

**QUANT — Quantitative facts.** Numerical values with units.

  Subtypes:
    QUANT.dose     — Medication or intervention dose with unit.
    QUANT.freq     — Dosing frequency or interval.
    QUANT.lab      — Laboratory value with unit.
    QUANT.vital    — Vital sign.
    QUANT.anthro   — Anthropometric or dosing parameter (weight,
                     BMI, CrCl, BSA).

**REAS — Clinical reasoning facts.** Statements that document
diagnostic or therapeutic reasoning.

  Subtypes:
    REAS.considered  — Considered and rejected diagnoses or
                       therapies.
    REAS.conditional — Conditional fact with antecedent.
    REAS.causal      — Causal or explanatory link (FOR, DUE TO,
                       BECAUSE).
    REAS.uncertain   — Uncertainty marker (likely, concerning for,
                       cannot rule out).
    REAS.planned     — Pending or planned action.

### PAIRING RULES

The class-vs-instance distinction is the central methodological
mechanism. You must:

  1. For every CAT.instance anchor, populate paired_anchors with the
     corresponding CAT.class anchor IF present in case_text. Set
     class_node_present to true. If the case_text does NOT contain
     explicit class-level terminology for the instance, set
     class_node_present to false and leave paired_anchors empty (or
     link to a related CAT.class anchor and flag the loose pairing
     in audit_notes).

  2. For every QUANT.dose and QUANT.freq anchor, populate
     paired_anchors with the CAT.instance it modifies.

  3. For every QUANT.lab anchor, link to any TEMP.trajectory anchor
     that references the same lab over time.

  4. For every REAS.causal anchor, link to the entities it connects.

### EXTRACTION TARGETS

Aim for approximately:
  - CAT: 12-18 anchors total (stratified across subtypes)
  - TEMP: 6-10 anchors total
  - QUANT: 8-12 anchors total
  - REAS: 4-8 anchors total

If a subtype is genuinely absent from the case, extract zero anchors
for it rather than fabricating. Record absent subtypes in the
missing_subtypes field.

### DO NOT EXTRACT

  - Generic boilerplate
  - Information from excluded_text (discussion, intro, references)
  - Facts you cannot tie back to a specific verbatim quote in
    case_text
  - Doses, lab values, or vital signs that appear only in cited trial
    data or guideline references rather than in the patient narrative

## PART 3: QUESTION GENERATION

For each anchor, generate one question whose correct answer requires
recovering exactly that anchor from context. Format:

  - anchor_id
  - question (natural language, ≤ 30 words)
  - expected_answer (verbatim or near-verbatim match to anchor text)
  - scoring (exact_match / keyword_match / numeric_match_with_unit /
    semantic_match)
  - granularity_tested (class / instance / qualifier / n/a)

Questions must be answerable from case_text alone, with no need for
outside clinical knowledge. Avoid leading questions.

For paired anchors, generate questions at multiple granularity
levels (class question targeting CAT.class anchor, instance question
targeting CAT.instance anchor, dose question targeting QUANT.dose
anchor). This nested structure is what makes the experiment
interpretable.

For REAS anchors, questions must target the reasoning, not just the
entities involved. For TEMP.status anchors, questions must test
whether the status change was preserved.

## PART 4: CLINICAL FILLER GENERATION

Generate 10 filler blocks of approximately 1500 tokens each.
Total filler should be approximately 15,000 tokens.

The filler must be:
  - Realistic clinical documentation in voice, register, and structure
  - Topically RELATED but distinct from the target case
  - Free of any specific named medications, exact doses, specific
    organisms, exact lab values with units, specific dates, or
    specific clinical reasoning that mirrors the target case
  - Free of any content that contradicts or confuses case_text
    anchors

Block types to choose from (vary across the 10):
  - Physical therapy progress note
  - Nursing shift assessment
  - Nutrition consult note
  - Care coordination / social work note
  - Pain management note
  - Wound care nursing note
  - Respiratory therapy note
  - Pharmacy reconciliation note (generic drug CLASSES only)
  - Case management discharge planning note
  - Occupational therapy evaluation
  - Speech-language pathology note (if clinically plausible)

Each block should read as if written by a different clinician with
different stylistic habits. Use realistic clinical abbreviations
(BID, prn, AAO x3, etc.) and section headers (S:, O:, A:, P: or
SUBJECTIVE/OBJECTIVE/ASSESSMENT/PLAN). Vital signs and labs
referenced as "stable," "WNL," "unchanged from prior," "trending
down" — never with specific numbers.

The hypothetical patient profile for the filler should match the
target case's demographics and major comorbidities (age, sex,
primary condition category) but should not reference any of the
case's specific clinical events, named diagnoses, or named
medications.

## OUTPUT FORMAT

Return everything as a single JSON object with this structure:

{
  "case_metadata": {
    "title": "...",
    "source": "...",
    "specialty": "...",
    "patient_descriptor": "...",
    "case_section_token_count": <integer; approximate tokens in case_text>,
    "excluded_section_token_count": <integer; approximate tokens in excluded_text>,
    "total_article_token_count": <integer; approximate total>
  },
  "case_text": "...",
  "excluded_text": "...",
  "anchors": [
    {
      "id": "A1",
      "category": "CAT",
      "subtype": "CAT.instance",
      "text": "...",
      "location": "...",
      "distinctiveness": "...",
      "granularity": "instance",
      "paired_anchors": ["A5", "A12"],
      "clinical_actionability": "high",
      "class_node_present": true
    }
  ],
  "questions": [
    {
      "anchor_id": "A1",
      "question": "...",
      "expected_answer": "...",
      "scoring": "keyword_match",
      "granularity_tested": "instance"
    }
  ],
  "filler_blocks": [
    {
      "block_id": 1,
      "note_type": "...",
      "approximate_tokens": <integer>,
      "content": "..."
    }
  ],
  "coverage_report": {
    "missing_subtypes": ["QUANT.dose", "REAS.uncertain", "..."],
    "under_represented_subtypes": ["CAT.alert", "..."],
    "instances_without_class_node": ["A12", "A14", "..."],
    "deliberate_deviations_from_target_bands": "free text",
    "filler_constraints_used": ["no named medications", "no exact lab values", "no specific dates", "no specific organisms", "no mirrored reasoning"]
  },
  "audit_notes": "..."
}

## SELF-AUDIT BEFORE RETURNING

Before producing your final JSON, audit your output against these
checks:

  1. Is case_text a verbatim extraction of the patient-specific
     content (not paraphrased, not summarized)?
  2. Are all anchor 'text' fields actually present verbatim within
     case_text? (Run a substring check mentally on each anchor.)
  3. Does every CAT.instance anchor have class_node_present set
     correctly, and is paired_anchors consistent with that flag?
  4. Does every QUANT.dose and QUANT.freq anchor reference the
     CAT.instance it modifies?
  5. Are there at least two anchors in each high-priority subtype
     (CAT.instance, CAT.qualifier, QUANT.dose, QUANT.lab,
     TEMP.status, REAS.considered)? If not, are they listed in
     coverage_report.missing_subtypes or under_represented_subtypes?
  6. Are the filler blocks completely free of named medications,
     exact lab values, exact doses, specific organisms, specific
     dates, and clinical reasoning that mirrors the target case?
  7. Do the filler blocks read as plausible clinical documentation?
  8. For each question, is the answer truly only obtainable from
     case_text (not from general clinical knowledge or from
     excluded_text)?
  9. For REAS anchors, do the questions target the reasoning itself?
  10. For TEMP.status anchors, do the questions test whether the
      status change was preserved?

If any check fails, revise before returning. Note in audit_notes
which checks you ran, any revisions made, and any subtypes that
were absent from the case (rather than under-extracted).

Begin now. Read the attached PDF first, then return the JSON.