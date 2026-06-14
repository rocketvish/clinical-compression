# PROMPT 2 — Anchor & Question Extractor

**Input:**
  - The `<case_id>_part1.json` produced by Prompt 1 (attach as file)
  - Optionally, the original PDF (helpful for context but case_text
    from part1.json is authoritative)

**Output:** A JSON file you save as `<case_id>_part2.json`. The merger
script combines part1 + part2 + part3 into the final case file.

---

You are extracting anchor facts and questions from a clinical case for a
context-compression research project. The case has been pre-extracted
into verbatim case_text by Prompt 1; you must work strictly within
that text.

Your task has two parts: (1) extract anchor facts following a strict
four-category taxonomy with class-instance pairing, (2) generate
questions that test recovery of each anchor.

## Working from the attached part1.json

Use the `case_text` field as the AUTHORITATIVE source of patient
content. Every anchor's `text` field must appear verbatim within
case_text — this is enforced downstream by a contamination check.

The `excluded_text` field is provided for context only — DO NOT extract
anchors from it. Even if it contains specific doses, lab values, or
clinical reasoning, those are not patient-specific.

The `case_metadata` field is provided to help orient you (specialty,
patient descriptor). Do NOT extract anchors from metadata text.

## PART 1: Anchor Fact Extraction

Extract anchor facts using exactly the four categories below. For each
anchor, capture:
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

### The four categories

**CAT — Categorical facts.** Statements identifying entities, classes,
named diagnoses, named medications, organisms, anatomic locations,
critical alerts, allergies, and negated findings.

  Subtypes:
    CAT.class     — Class or category level (drug class, organism
                    class, anatomic region, diagnosis category).
                    Example: "patient on anticoagulation",
                    "gram-positive bacteremia".
    CAT.instance  — Specific named entity (drug agent, organism
                    species, named diagnosis, exact anatomy).
                    Example: "apixaban", "Enterococcus durans",
                    "left anterior descending artery".
    CAT.qualifier — Modifier attached to an instance that changes
                    clinical management. Example: "reduced-dose
                    apixaban", "methicillin-susceptible S. aureus
                    with reduced vancomycin susceptibility",
                    "type 2 NSTEMI".
    CAT.alert     — Critical safety alert (allergy with severity,
                    code status, fall risk, precautions).
    CAT.negated   — Negated finding or status. Example: "denies
                    chest pain", "ruled out PE", "non-smoker".

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
    QUANT.dose   — Medication or intervention dose with unit.
    QUANT.freq   — Dosing frequency or interval.
    QUANT.lab    — Laboratory value with unit.
    QUANT.vital  — Vital sign.
    QUANT.anthro — Anthropometric or dosing parameter (weight, BMI,
                   CrCl, BSA).

**REAS — Clinical reasoning facts.** Statements that document
diagnostic or therapeutic reasoning.

  Subtypes:
    REAS.considered   — Considered and rejected diagnoses or
                        therapies.
    REAS.conditional  — Conditional fact with antecedent ("if/then").
    REAS.causal       — Causal or explanatory link (FOR, DUE TO,
                        BECAUSE).
    REAS.uncertain    — Uncertainty marker (likely, concerning for,
                        cannot rule out).
    REAS.planned      — Pending or planned action.

### Pairing rules

The class-vs-instance distinction is the central methodological
mechanism for this experiment. You must:

  1. For every CAT.instance anchor, populate paired_anchors with the
     corresponding CAT.class anchor IF present in case_text, and set
     class_node_present to true. If case_text does NOT contain
     explicit class-level terminology for the instance, set
     class_node_present to false and leave paired_anchors empty for
     the class pair (you may still link to other related anchors,
     but note the loose pairing in audit_notes).

  2. For every QUANT.dose and QUANT.freq anchor, populate
     paired_anchors with the CAT.instance it modifies.

  3. For every QUANT.lab anchor, link to any TEMP.trajectory anchor
     that references the same lab over time.

  4. For every REAS.causal anchor, link to the entities it connects.

### Extraction targets

Aim for approximately:
  - CAT: 12-18 anchors total (stratified across subtypes; at least
    3 CAT.class, 4 CAT.instance, 2 CAT.qualifier, 2 CAT.negated,
    1 CAT.alert if present)
  - TEMP: 6-10 anchors total (aim for at least 1 of each subtype
    if present in the case)
  - QUANT: 8-12 anchors total
  - REAS: 4-8 anchors total

If a subtype is genuinely absent from case_text, extract zero anchors
for it. Record absent subtypes in coverage_report.missing_subtypes.
Do not fabricate to meet targets.

### Do not extract

  - Generic boilerplate ("the patient was seen today")
  - Information from excluded_text
  - Facts you cannot tie back to a specific verbatim quote in
    case_text
  - Doses or values that appear only in cited trial or guideline
    references rather than in the patient narrative
  - Demographic facts unless directly clinically relevant
  - Facts that appear only in the abstract or discussion

## PART 2: Question Generation

For each anchor, generate one question whose correct answer requires
recovering exactly that anchor from context.

Format:
  - anchor_id (must match Part 1)
  - question (natural language, ≤ 30 words)
  - expected_answer (verbatim or near-verbatim match to anchor text)
  - scoring (exact_match / keyword_match / numeric_match_with_unit /
    semantic_match)
  - granularity_tested (class / instance / qualifier / n/a)

Questions must be answerable from case_text alone, with no need for
outside clinical knowledge. Avoid leading questions ("Was the patient
on apixaban?" is leading; "What anticoagulant was the patient
receiving?" is not).

For paired anchors, generate questions at multiple granularity levels
so the experiment can stratify by what the model recovered:
  - class question targeting CAT.class anchor
  - instance question targeting CAT.instance anchor
  - dose question targeting QUANT.dose anchor
  - frequency question targeting QUANT.freq anchor

For REAS anchors, questions must target the reasoning itself, not
just the entities involved. Example for "ICH was considered but
ruled out based on negative CT":
  - Bad: "Did the patient have ICH?" (tests outcome only)
  - Good: "Was intracranial hemorrhage considered in the workup,
    and what evidence ruled it out?"

For TEMP.status anchors, questions must test whether the status
change was preserved, not just the underlying entity. Example for
"anticoagulation recently discontinued":
  - Bad: "Is the patient on anticoagulation?"
  - Good: "What is the patient's current anticoagulation status,
    and what changed?"

## Output schema

Return a single JSON object with this exact structure:

```json
{
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
  "coverage_report": {
    "missing_subtypes": ["QUANT.dose", "REAS.uncertain"],
    "under_represented_subtypes": ["CAT.alert"],
    "instances_without_class_node": ["A12", "A14"],
    "deliberate_deviations_from_target_bands": "free text"
  },
  "audit_notes": "..."
}
```

Note: DO NOT include `case_metadata`, `case_text`, `excluded_text`, or
`filler_blocks` in this output. The merger script combines them from
Prompt 1's part1.json and Prompt 3's part3.json. Including duplicates
here will cause merge conflicts.

## Self-audit before returning

Before producing your final JSON, audit your output against these
checks:

  1. Is every anchor's `text` field actually present verbatim within
     case_text? (Mental substring check on each.)
  2. Does every CAT.instance anchor have class_node_present set
     correctly?
  3. Does every QUANT.dose and QUANT.freq anchor reference its
     CAT.instance in paired_anchors?
  4. Are at least two anchors present in each high-priority subtype
     (CAT.instance, CAT.qualifier, QUANT.dose, QUANT.lab,
     TEMP.status, REAS.considered) — or are they listed in
     coverage_report.missing_subtypes?
  5. For each question, is the answer truly only obtainable from
     case_text (not from general clinical knowledge or
     excluded_text)?
  6. For REAS anchors, do questions target the reasoning itself?
  7. For TEMP.status anchors, do questions test the status change?

If any check fails, revise before returning. Document checks run and
revisions made in audit_notes.

Begin now. Read the attached part1.json and return only the JSON
object for Part 2 (anchors + questions + coverage_report +
audit_notes).