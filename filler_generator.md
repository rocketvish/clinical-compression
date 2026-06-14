# PROMPT 3 — Clinical Filler Generator

**Input:** The `<case_id>_part1.json` produced by Prompt 1 (attach as
file). Only the `case_metadata` field is needed; you do not need the
full case_text.

**Output:** A JSON file you save as `<case_id>_part3.json`. The merger
script combines it with part1 and part2.

---

You are generating realistic clinical documentation that will serve as
contextual padding in a context-compression research experiment. The
filler will be interleaved with a real patient case during evaluation;
the experiment measures whether specific facts in the real case
survive when surrounded by this filler.

The integrity of the experiment depends critically on the filler being
clinically realistic but containing NO specific medical content that
could be confused with or substitute for the real case's content. A
clinician reading the filler should find it plausible as "this looks
like the kind of note one might write about a hospitalized patient,"
but should not be able to extract any specific clinical fact from it.

## Reading the input

From the attached part1.json, you need only:
  - `case_metadata.primary_condition_category` (e.g., "cardiology")
  - `case_metadata.patient_descriptor` (e.g., "55-year-old male")
  - `case_metadata.comorbidity_categories` (e.g., ["cardiovascular",
    "renal", "endocrine"])

You do NOT need to read `case_text` or `excluded_text`. In fact, do
NOT read them — knowing the case's specifics increases the risk of
accidental leakage into filler. The metadata gives you enough
information to generate filler that matches the patient profile at
the demographic and broad-system level.

## Generation task

Generate 10 filler blocks of approximately 1500 tokens each. Total
filler should be approximately 15,000 tokens.

Each block should be a distinct note type. Vary across the 10 blocks
using this menu:
  - Physical therapy progress note
  - Nursing shift assessment
  - Nutrition consult note
  - Care coordination / social work note
  - Pain management note
  - Wound care nursing note (only if plausible for patient profile)
  - Respiratory therapy note
  - Pharmacy reconciliation note
  - Case management discharge planning note
  - Occupational therapy evaluation
  - Speech-language pathology note (only if plausible)
  - Chaplaincy or spiritual care note
  - Patient education encounter

Each block should read as if written by a different clinician with
different stylistic habits — some terse and abbreviation-heavy, some
verbose and narrative, some structured S/O/A/P format, some less
structured. Use realistic clinical register and authentic
abbreviations (BID, prn, AAO x3, NAD, WNL, etc.).

## CRITICAL contamination constraints

The following constraints are non-negotiable. Each one corresponds to
a specific failure mode that would invalidate experimental results.

**FORBIDDEN: Named medications, even generic names.** Do not write
"aspirin," "metoprolol," "insulin," "warfarin," "lisinopril," or any
other drug name. Refer to medications by therapeutic class only:
"the patient's antihypertensive regimen," "scheduled diabetes
medications," "as-needed pain medication." Even if a class
description has only one common member (e.g., "an SGLT2 inhibitor"),
prefer the class.

**FORBIDDEN: Named specific medical conditions or diagnoses.** Do
NOT write "hypertension," "diabetes," "atrial fibrillation,"
"coronary artery disease," "CKD," "COPD," "heart failure," etc.
Refer to comorbidities only at the SYSTEM level, e.g.,
"cardiovascular comorbidities," "metabolic conditions," "chronic
medical issues," "the patient's chronic conditions." If the
patient_descriptor or comorbidity_categories list contains specific
words like "hypertension," DO NOT use that word in filler — it
will contaminate the experiment.

**FORBIDDEN: Specific organism names.** Do not write "Staphylococcus
aureus," "E. coli," "MRSA," "Enterococcus," etc. Refer to infections
generically: "the patient's documented infection," "per ID team
recommendations."

**FORBIDDEN: Specific lab values with units.** No "creatinine 2.3
mg/dL," no "INR 4.5," no "Hgb 8.4 g/dL." Reference lab values only
qualitatively: "labs stable," "WNL," "unchanged from prior,"
"trending down per team awareness," "within expected ranges for
this patient."

**FORBIDDEN: Specific vital signs.** No "BP 88/52," no "HR 132," no
"O2 sat 75%." Use qualitative descriptions: "vitals stable through
shift," "afebrile," "hemodynamically stable," "tolerating activity."

**FORBIDDEN: Specific doses or frequencies.** No "5 mg," no "BID,"
no "20 mg/kg," no "q8h." If you must reference a regimen, say "per
home regimen," "scheduled medications," "as ordered."

**FORBIDDEN: Specific dates.** No "11/22/2023," no "January 15th,"
no "yesterday at 14:30." Use relative: "this morning," "overnight,"
"prior to admission," "earlier this shift."

**FORBIDDEN: Specific durations that match the case.** Avoid
"six months prior," "for 14 days," "two weeks ago" — these can
collide with TEMP anchors in the case. Use vague relative time:
"some time ago," "earlier in the admission," "prior to this
encounter."

**FORBIDDEN: Specific clinical events that mirror the case.** Even
generically described. Do not reference acute bleeding, acute
arrhythmia, specific procedures, specific complications. The
filler should describe routine inpatient care activities (PT
sessions, dietary tolerance, ambulation, discharge planning,
psychosocial assessment) — NOT acute clinical events.

**FORBIDDEN: Specific clinical reasoning.** Do not document
considered-and-rejected differentials, do not document conditional
management plans ("if X then Y"), do not document causal
reasoning chains. Keep all filler notes at the level of routine
clinical workflow documentation, NOT diagnostic or therapeutic
reasoning.

## What the filler SHOULD contain

The filler is realistic clinical workflow documentation. Appropriate
content includes:

  - Functional status assessments (mobility, ADLs, ambulation
    distance, transfer status, fall risk at a general level)
  - Subjective patient reports about how they are feeling generally
    ("denies acute complaints overnight," "reports feeling
    fatigued," "engaged with care plan")
  - Family / social context (presence at bedside, support systems,
    home environment, transportation arrangements)
  - Care coordination activities (DME planning, home services
    referrals, follow-up appointment scheduling)
  - Nutritional tolerance and dietary observations (without specific
    diet types or restrictions that would imply a specific
    condition)
  - Psychosocial observations (mood, engagement, coping, family
    dynamics)
  - Routine education content (general patient education about
    activity, follow-up, when to call)
  - Generic monitoring activities ("monitoring per protocol,"
    "scheduled reassessment")
  - Equipment / DME planning
  - Insurance / financial coordination at a high level

The patient profile at the system level is acceptable: a 55-year-old
patient with multiple chronic conditions is fine to reference, as
long as the specific conditions are not named. "A patient with
significant cardiovascular and metabolic comorbidity burden" is
fine; "a patient with atrial fibrillation, hypertension, and
diabetes" is forbidden.

## Stylistic variation

Make the 10 blocks feel like they were written by 10 different
clinicians. Variation axes to deliberately use:

  - Length within blocks: some 1200 tokens, some 1700 tokens (mean
    around 1500)
  - Structure: some SOAP-formatted, some narrative paragraphs, some
    list-based
  - Abbreviation density: some use AAO x3 / NAD / WNL freely, some
    are more spelled-out
  - Voice: some first-person ("I assessed the patient"), some
    third-person passive ("Patient was assessed")
  - Specialty register: PT note voice ≠ chaplaincy note voice ≠
    pharmacy note voice
  - Granularity: some focus on a single domain (PT mobility), some
    span multiple domains (case management overview)

## Output schema

Return a single JSON object with this exact structure:

```json
{
  "filler_blocks": [
    {
      "block_id": 1,
      "note_type": "Physical therapy progress note",
      "approximate_tokens": 1500,
      "content": "<the full filler block content as a single string>"
    }
  ],
  "filler_constraints_used": [
    "no named medications",
    "no named diagnoses",
    "no specific organisms",
    "no specific lab values",
    "no specific vital signs",
    "no specific doses or frequencies",
    "no specific dates",
    "no acute clinical events",
    "no specific clinical reasoning"
  ],
  "audit_notes": "<brief notes on any close calls or stylistic choices>"
}
```

Note: DO NOT include `case_metadata`, `case_text`, `excluded_text`,
`anchors`, or `questions` in this output. The merger script combines
this part3.json with part1 and part2.

## Self-audit before returning

Before returning, scan your filler blocks for these specific
contamination patterns:

  1. Search for medication name patterns: `mg`, `mcg`, `units`, common
     drug suffixes (-pril, -sartan, -olol, -statin, -azole, -mycin).
     Any hits? Either remove or replace with class-level descriptors.

  2. Search for diagnosis name patterns: "hypertension," "diabetes,"
     "atrial fibrillation," and any specific condition that matches
     case_metadata.comorbidity_categories at the named-diagnosis level.

  3. Search for specific numbers attached to clinical units: any
     occurrence of digits followed by "mg," "mL," "kg," "%,"
     "mg/dL," "mmHg," etc.

  4. Search for date patterns: month names, "/" between digits, "ago"
     phrases.

  5. Search for acute event language: "bleeding," "stroke,"
     "infarction," "arrhythmia," "sepsis," "exacerbation,"
     "decompensation." If found, rewrite.

Document the self-audit briefly in audit_notes.

Begin now. Read the case_metadata from the attached part1.json,
ignore case_text and excluded_text, and return only the JSON object
for Part 3.