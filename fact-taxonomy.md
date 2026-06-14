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

## Degradation Modes (Scoring Rubric)

Each fact is scored on **type** (categories above) × **degradation mode** (below):

| Mode | Description | Example |
|---|---|---|
| Complete loss | Fact absent from output | Allergy to penicillin not mentioned |
| Binding failure | Components survive but misassociate | "HbA1c" and "1.1" both present but cross-wired |
| Polarity inversion | Clinical meaning reversed | "Denies chest pain" → "chest pain" |
| Qualification loss | Uncertainty/hedging stripped | "Concerning for pneumonia" → "pneumonia" |
| Attribution loss | Source/reliability signal dropped | "Patient reports" removed from assertion |

---

## Degradation Hypothesis

**Predicted order of degradation (first → last):**

1. **Temporal** — multi-token relationships spread across document; compression disrupts spatial bindings between events and dates
2. **Clinical reasoning** — qualifier/hedging tokens are low-surprisal; perplexity weighting actively downweights the words that make reasoning conditional
3. **Quantitative** — high-surprisal tokens (numbers, units, drug names) naturally protected by perplexity weighting; vulnerable to binding failures before complete loss
