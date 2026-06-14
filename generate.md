You are assisting with a clinical NLP research project that tests
whether representation-level context compression preserves clinically
critical information in longitudinal patient records. Your task has
three parts: (1) extract anchor facts from an attached case report
PDF following a strict four-category taxonomy, (2) generate questions
that test recovery of each anchor, and (3) generate realistic clinical
filler that will be used to pad the case to various context lengths.

Read the attached case report carefully before beginning. Pay
particular attention to the case presentation, hospital course,
medications, laboratory findings, and clinical reasoning sections.
Ignore the abstract, introduction, discussion, and references for
anchor extraction — focus only on the patient-specific clinical
content.

## PART 1: ANCHOR FACT EXTRACTION

Extract anchor facts using exactly the four categories below. For each
anchor fact, capture:
  - id (sequential A1, A2, A3...)
  - category (one of CAT / TEMP / QUANT / REAS)
  - subtype (see per-category subtypes below)
  - text (verbatim quote from the case, ≤ 25 words)
  - location (approximate section: presentation / hospital_course /
    labs / medications / disposition / other)
  - distinctiveness (low / medium / high — based on how unusual or
    specific the language is; "anticoagulation" is low, "warfarin" is
    medium, "acenocoumarol 3 mg daily" is high)
  - granularity (class / instance / qualifier — see pairing rules
    below; applies primarily to CAT anchors)
  - paired_anchors (list of IDs of other anchors at different
    granularity levels for the same underlying clinical concept)
  - clinical_actionability (low / medium / high — would loss of this
    fact change clinical management?)

### The four categories:

**CAT — Categorical facts.** Statements identifying entities, classes,
named diagnoses, named medications, organisms, anatomic locations,
critical alerts, allergies, and negated findings. This is the broadest
category and includes content at multiple granularity levels (see
pairing rules).

  Subtypes:
    CAT.class     — Class or category level (drug class, organism
                    class, anatomic region, diagnosis category).
                    Example: "patient on anticoagulation",
                    "gram-positive bacteremia".
    CAT.instance  — Specific named entity within a class (drug agent,
                    organism species, named diagnosis, exact anatomy).
                    Example: "apixaban", "Enterococcus durans",
                    "left anterior descending artery".
    CAT.qualifier — Modifier attached to an instance that changes
                    clinical management. Example: "reduced-dose
                    apixaban", "methicillin-susceptible S. aureus with
                    reduced vancomycin susceptibility", "type 2
                    NSTEMI".
    CAT.alert     — Critical safety alert. Example: "severe penicillin
                    allergy with anaphylaxis", "MRSA precautions",
                    "DNR/DNI", "fall risk".
    CAT.negated   — Negated finding or status. Example: "denies chest
                    pain", "no history of bleeding", "ruled out PE",
                    "non-smoker", "no known drug allergies".

**TEMP — Temporal facts.** Statements about when, how long, in what
order, or how something changed over time. Includes status-change
qualifiers that convert facts from current to historical.

  Subtypes:
    TEMP.date       — Absolute date or timepoint. Example: "admission
                      on 11/22/2023", "started in 2017".
    TEMP.duration   — Length of time. Example: "for 14 days", "over
                      the past 6 months", "4-week course".
    TEMP.since      — Time elapsed since a referenced event. Example:
                      "6 months post-stent", "POD 3", "two weeks
                      after surgery".
    TEMP.status     — Status-change qualifier. Example: "recently
                      discontinued", "previously refused", "completed
                      bisphosphonate holiday", "newly diagnosed",
                      "in remission".
    TEMP.sequence   — Ordering of events. Example: "started X, then
                      switched to Y when culture results returned,
                      then added Z".
    TEMP.trajectory — Trend over time. Example: "Hgb trending down
                      from 12 to 8 over 48 hours", "INR rising
                      despite warfarin hold", "improving renal
                      function".

**QUANT — Quantitative facts.** Numerical values with units, including
doses, frequencies, lab values, vital signs, and anthropometric or
dosing parameters.

  Subtypes:
    QUANT.dose     — Medication or intervention dose with unit.
                     Example: "5 mg", "20 mg/kg", "2 g IV".
    QUANT.freq     — Dosing frequency or interval. Example: "every
                     12 hours", "BID", "q8h", "once daily".
    QUANT.lab      — Laboratory value with unit. Example: "INR 8.5",
                     "Hgb 9.2 g/dL", "creatinine 2.3 mg/dL".
    QUANT.vital    — Vital sign. Example: "BP 88/52", "HR 132",
                     "O2 sat 75% on room air".
    QUANT.anthro   — Anthropometric or dosing parameter. Example:
                     "weight 62 kg", "BMI 31", "CrCl 30 mL/min".

**REAS — Clinical reasoning facts.** Statements that document
diagnostic or therapeutic reasoning rather than factual events.
These are often the most clinically informative and most vulnerable
to compression.

  Subtypes:
    REAS.considered — Considered and rejected diagnoses. Example:
                      "ICH was considered but ruled out based on
                      negative CT", "initially concerned for PE,
                      D-dimer negative, no further workup".
    REAS.conditional — Conditional fact with antecedent. Example:
                      "if creatinine clearance drops below 30, reduce
                      dose", "hold anticoagulation if INR > 4".
    REAS.causal     — Causal or explanatory link. Example: "started
                      warfarin FOR mechanical valve", "discontinued
                      NSAIDs DUE TO AKI", "admitted BECAUSE of failure
                      of outpatient therapy".
    REAS.uncertain  — Uncertainty marker. Example: "likely", "concerning
                      for", "cannot rule out", "low suspicion for",
                      "differential includes".
    REAS.planned    — Pending or planned action. Example: "will obtain
                      MRI tomorrow", "consider ECMO if no improvement",
                      "to be reassessed in clinic in 2 weeks".

### PAIRING RULES

The class-vs-instance distinction is the central methodological
mechanism in this experiment. Even though all of these are CAT
anchors, their compression behavior is expected to differ
dramatically by granularity. You must:

  1. For every CAT.instance anchor, identify the corresponding
     CAT.class anchor (if present in the case) and link them via
     paired_anchors. If the case mentions "apixaban" but never says
     "anticoagulation" explicitly, you may still extract the
     instance — but flag that the class anchor is absent.

  2. For every QUANT.dose and QUANT.freq anchor, identify the
     CAT.instance anchor it modifies. A dose without its associated
     drug cannot be tested.

  3. For every QUANT.lab anchor, identify any TEMP.trajectory anchor
     that references the same lab over time.

  4. For every REAS.causal anchor, identify the entities it links
     (e.g., "started warfarin for mechanical valve" links a CAT.instance
     and a CAT.qualifier).

These pairings are how the experiment tests whether compression
preserves the *relationships* between facts, not just the facts in
isolation.

### EXTRACTION TARGETS

Aim for approximately:
  - CAT: 12-18 anchors total (stratified across subtypes; aim for at
    least 3 CAT.class, 4 CAT.instance, 2 CAT.qualifier, 2 CAT.negated,
    1 CAT.alert if present)
  - TEMP: 6-10 anchors total (aim for at least 1 of each subtype if
    present in the case)
  - QUANT: 8-12 anchors total (stratified across subtypes)
  - REAS: 4-8 anchors total (this is the most variable category — some
    cases will have many considered-and-rejected differentials and
    explicit reasoning, others will have almost none)

If a subtype is not present in the case, extract zero anchors for it
rather than fabricating. The point of the experiment is to test
preservation of what IS there, not to manufacture anchors.

### DO NOT EXTRACT

  - Generic boilerplate ("the patient was seen today")
  - Information from the discussion or references sections
  - Demographic facts unless directly relevant to the case (age and
    sex are fine; race only if mentioned as clinically relevant)
  - Facts that appear only in the abstract
  - Facts you cannot tie back to a specific verbatim quote in the
    patient-specific content

## PART 2: QUESTION GENERATION

For each anchor, generate one question whose correct answer requires
recovering exactly that anchor from context. Format:

  - anchor_id (must match Part 1)
  - question (natural language, ≤ 30 words)
  - expected_answer (verbatim or near-verbatim match to anchor text)
  - scoring (exact_match / keyword_match / numeric_match_with_unit /
    semantic_match)

Questions should be answerable from the case report alone, with no
need for outside clinical knowledge. Avoid leading questions ("Was
the patient on apixaban?" is leading; "What anticoagulant was the
patient receiving?" is not).

For paired anchors, generate questions at BOTH granularity levels and
note in the question metadata which level each tests. Example for an
endocarditis case:
  - anchor C1 (CAT.class): "patient on antibiotics" →
    Q: "Was the patient treated with antibiotics?"
  - anchor C2 (CAT.instance, paired with C1): "vancomycin" →
    Q: "Which antibiotic was the patient initially treated with?"
  - anchor Q1 (QUANT.dose, paired with C2): "20 mg/kg" →
    Q: "At what dose was vancomycin administered?"
  - anchor Q2 (QUANT.freq, paired with C2): "every 12 hours" →
    Q: "How often was vancomycin given?"

This nested structure is what makes the experiment interpretable.

For REAS anchors, questions should target the reasoning itself, not
just the entities involved. Example for a REAS.considered anchor
("PE was considered but ruled out based on negative D-dimer"):
  - Bad question: "Did the patient have PE?" (tests final diagnosis,
    not reasoning)
  - Good question: "Was pulmonary embolism considered in the
    differential, and what evidence ruled it out?"

For TEMP.status anchors, questions should specifically test whether
the status change was preserved, not just the underlying entity.
Example for "anticoagulation recently discontinued for surgery":
  - Bad question: "Is the patient on anticoagulation?"
  - Good question: "What is the patient's current anticoagulation
    status, and why?"

## PART 3: CLINICAL FILLER GENERATION

Generate clinical filler that will be used to pad this case to longer
context lengths. The filler must be:

  - Realistic clinical documentation in voice, register, and structure
  - Topically RELATED but distinct from the target case (e.g., for a
    cardiac case, generate notes about the same hypothetical
    patient's physical therapy, nutrition, nursing care, care
    coordination)
  - Free of any specific named medications, exact doses, specific
    organisms, exact lab values with units, specific dates, or
    specific clinical reasoning that mirrors the target case
  - Free of any content that contradicts or confuses the target
    case's anchor facts (e.g., if target case patient is on warfarin,
    filler must not mention any anticoagulant by name)

Generate TEN filler blocks of approximately 1500 tokens each. Each
block should be a distinct note type. Choose from:

  - Physical therapy progress note
  - Nursing shift assessment
  - Nutrition consult note
  - Care coordination / social work note
  - Pain management note
  - Wound care nursing note
  - Respiratory therapy note
  - Pharmacy reconciliation note (use only generic drug CLASSES,
    never specific names)
  - Case management discharge planning note

Vary the chosen note types across the five blocks. Each block should
read as if written by a different clinician with different stylistic
habits — some terse, some more verbose, some heavily abbreviated.
Use realistic clinical abbreviations (BID, prn, AAO x3, etc.) and
section headers (S:, O:, A:, P: or SUBJECTIVE/OBJECTIVE/ASSESSMENT/
PLAN). Vital signs and labs should be referenced as "stable", "WNL",
"unchanged from prior", "trending down" — never with specific numbers.

The hypothetical patient profile for the filler should match the
target case's demographics and major comorbidities (age, sex, primary
condition category) but should not reference any of the case's
specific clinical events, named diagnoses, or named medications.

## OUTPUT FORMAT

Return everything as a single JSON object with this structure:

{
  "case_metadata": {
    "title": "...",
    "specialty": "...",
    "approximate_token_count_original": <integer>
  },
  "anchors": [
    {
      "id": "A1",
      "category": "CAT",
      "subtype": "CAT.class",
      "text": "...",
      "location": "...",
      "distinctiveness": "...",
      "granularity": "class",
      "paired_anchors": ["A5", "A12"],
      "clinical_actionability": "..."
    },
    ...
  ],
  "questions": [
    {
      "anchor_id": "A1",
      "question": "...",
      "expected_answer": "...",
      "scoring": "...",
      "granularity_tested": "class"
    },
    ...
  ],
  "filler_blocks": [
    {
      "block_id": 1,
      "note_type": "...",
      "approximate_tokens": <integer>,
      "content": "..."
    },
    ...
  ],
  "audit_notes": "..."
}

## SELF-AUDIT BEFORE RETURNING

Before producing your final JSON, audit your output against these
checks:

  1. Does every CAT.instance anchor have a paired CAT.class anchor
     (or a note that the class anchor is absent from the case)?
  2. Does every QUANT.dose and QUANT.freq anchor reference the
     CAT.instance it modifies?
  3. Are there at least two anchors in each of the high-priority
     subtypes (CAT.instance, CAT.qualifier, QUANT.dose, QUANT.lab,
     TEMP.status, REAS.considered)?
  4. Are the filler blocks completely free of named medications,
     exact lab values, exact doses, specific organisms, and clinical
     reasoning that mirrors the target case?
  5. Do the filler blocks read as plausible clinical documentation
     a busy clinician would actually write?
  6. For each question, is the answer truly only obtainable from the
     case content (not from general clinical knowledge)?
  7. For REAS anchors, do the questions target the reasoning itself
     rather than just the underlying entities?
  8. For TEMP.status anchors, do the questions test whether the
     status change was preserved, not just the underlying entity?

If any check fails, revise before returning. Note in the audit_notes
field which checks you ran, any revisions made, and any subtypes
that were absent from the case (rather than under-extracted).

Begin now. Read the attached PDF first, then return the JSON.