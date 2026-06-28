# Fact Taxonomy — Structured Store Reference

## Fact Categories

### 1. Categorical

| Subcategory | Examples |
|---|---|
| Previous diagnoses | ICD-coded conditions, historical diagnoses |
| Reported symptoms | Including anatomical location |
| Patient identifiers | Name, sex, ethnicity, language, age |
| Family history | Conditions, relation |
| Behaviors | Smoking, alcohol, drug use, exercise |
| Code status | Full code, DNR, DNI, MOLST |
| Negated facts | "Denies chest pain," "no history of seizures" |
| **Critical alerts** | |
| — Allergies | Substance + reaction type |
| — Infection precautions | Contact, droplet, airborne |
| — Fall risk | Risk level, contributing factors |
| **Specific entities** | |
| — Drug names | Active, discontinued, PRN |
| — Device types | Pacemaker, port, prosthetics |

### 2. Temporal

| Subcategory | Examples |
|---|---|
| Medication start/stop | Absolute dates, relative durations ("3-month course"), qualifiers ("recently discontinued") |
| Sequencing | Order of events, procedures, interventions |
| Lab trajectories | Direction and timing of value changes |
| Dosage changes | Prior dose → current dose with timing |
| Time since events | "6 weeks post-op," "diagnosed 2 years ago" |

### 3. Quantitative

| Subcategory | Examples |
|---|---|
| Lab values | Value + unit (HbA1c 7.2%, K+ 4.2 mEq/L) |
| Vitals | BP 128/82, HR 72, SpO2 98%, Temp 37.2°C |
| Medication dosages | Dose + frequency (metformin 500mg BID) |

### 4. Clinical Reasoning

| Subcategory | Examples |
|---|---|
| Considered/rejected diagnoses | "Ruled out PE," "ACS less likely given negative troponin" |
| Conditional facts | Antecedent → action for future care teams (e.g., "if INR > 4, hold anticoagulation") |
| Explanatory links | Causal chains ("admitted due to failure of outpatient medication") |
| Uncertainty markers | "Concerning for," "cannot rule out," "differential includes" |
| Pending/planned tasks | Ordered but not resulted labs, scheduled procedures, planned follow-ups |

### 5. Meta

| Subcategory | Description |
|---|---|
| Source attribution | Who asserted the fact: patient report, outside records, physician assessment, nursing note |
| Entity-value binding | Whether the correct value remains associated with the correct entity |

---

## Mapping to Judge Scoring Categories

The extraction pipeline uses fine-grained subcategories for fact capture. The evaluation pipeline (orchestrate.py, LLM-as-judge) uses compact dot-notation subtypes calibrated for scoring. A converter module will bridge these. The mapping is not always 1:1 — some extraction subcategories map to different judge subtypes depending on the fact's specificity level.

### Categorical → CAT.*

| Extraction subcategory | Judge subtype | Notes |
|---|---|---|
| previous_diagnosis | CAT.class or CAT.instance | Class if general ("diabetes"), instance if specific ("Type 2 DM") |
| reported_symptom | CAT.class or CAT.qualifier | Qualifier if anatomy/modifier attached |
| patient_identifier | CAT.class | Demographics |
| family_history | CAT.class | |
| behavior | CAT.class or CAT.qualifier | Qualifier if specifics attached ("1 pack/day") |
| code_status | CAT.class | |
| negated_fact | CAT.negated | Always maps to negated regardless of underlying entity |
| allergy | CAT.alert | Requires substance + reaction type for CORRECT |
| infection_precaution | CAT.alert | |
| fall_risk | CAT.alert | |
| drug_name | CAT.instance | Most common mapping — specific entity required |
| device_type | CAT.instance | |

### Temporal → TEMP.*

| Extraction subcategory | Judge subtype | Notes |
|---|---|---|
| medication_timing | TEMP.date, TEMP.duration, TEMP.status, or TEMP.since | Depends on what the fact captures: absolute date, duration, status change, or elapsed time |
| event_sequence | TEMP.sequence | |
| lab_trajectory | TEMP.trajectory | |
| dosage_change | TEMP.status | Status change on a quantitative entity |
| time_since_event | TEMP.since | |

### Quantitative → QUANT.*

| Extraction subcategory | Judge subtype | Notes |
|---|---|---|
| lab_value | QUANT.lab | |
| vital_sign | QUANT.vital | |
| medication_dosage | QUANT.dose and/or QUANT.freq | Dose and frequency may be separate judge anchors from one extraction fact |

### Clinical Reasoning → REAS.*

| Extraction subcategory | Judge subtype | Notes |
|---|---|---|
| considered_rejected_diagnosis | REAS.considered | |
| conditional_fact | REAS.conditional | |
| explanatory_link | REAS.causal | |
| uncertainty_marker | REAS.uncertain | |
| pending_planned_task | REAS.planned | |

---

## Failure Mode Taxonomy (Scoring Rubric)

The canonical failure mode taxonomy comes from the LLM-as-judge (orchestrate.py). Each fact is scored on **type** (categories above) × **failure mode** (below).

| Failure mode | Description | Example | Clinical risk |
|---|---|---|---|
| class_collapse | Model gave class-level answer when instance required | "antibiotics" for "vancomycin" | Moderate — loses actionability |
| instance_swap | Model named a different instance within the same class | "rivaroxaban" for "apixaban" | **Highest** — wrong medication |
| status_loss | Entity preserved but temporal status qualifier lost | "on apixaban" for "recently discontinued apixaban" | High — could cause re-prescription |
| negation_loss | Lost negation, reporting affirmative form | "chest pain" for "denies chest pain" | **Highest** — reverses clinical meaning |
| qualifier_loss | Base entity preserved but qualifier lost | "S. aureus" for "methicillin-resistant S. aureus" | High — changes treatment |
| uncertainty_loss | Stripped uncertainty markers | "pneumonia" for "concerning for pneumonia" | High — inflates diagnostic certainty |
| magnitude_error | Numeric value wrong beyond tolerance | "INR 3.5" for "INR 8.5" | High — affects dosing decisions |
| unit_missing | Number correct but unit absent | "8.5" for "INR 8.5" | Moderate — ambiguous without context |
| binding_failure | Components survive but misassociate | "HbA1c" and "1.1" cross-wired | High — wrong value on wrong entity |
| fabrication | Answer not in case at all | Model invents a medication | **Highest** — no basis in record |
| refusal | Model declined or said not available | "not documented" | Informative signal, not clinical harm |
| attribution_loss | Source/reliability signal dropped | "Patient reports" removed | Low-moderate — loses reliability context |

Note: the earlier "degradation modes" (complete loss, polarity inversion, qualification loss) map into this taxonomy. Complete loss → refusal or fabrication depending on model behavior. Polarity inversion → negation_loss. Qualification loss → qualifier_loss or uncertainty_loss depending on what was lost.

---

## Degradation Hypothesis

**Predicted order of degradation (first → last):**

1. **Temporal** — multi-token relationships spread across document; compression disrupts spatial bindings between events and dates
2. **Clinical reasoning** — qualifier/hedging tokens are low-surprisal; perplexity weighting actively downweights the words that make reasoning conditional
3. **Quantitative** — high-surprisal tokens (numbers, units, drug names) naturally protected by perplexity weighting; vulnerable to binding failures before complete loss
