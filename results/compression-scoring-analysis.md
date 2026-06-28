# Text Compression Baseline — Scoring Analysis

## Case: Bleeding Complications of Triple Therapy
## Source: 58 ground-truth facts from bleeding-facts-final.json

---

## Technique 3: LLM Summarization — Qwen3-8B Local (3x, 440 words)

**Raw score: 57/58 facts present (98%)**

### Missing (1)
- f055 [categorical/device_type] "Simple nasal packing was used for mild bleeding episodes"
  - Compressed text says "simple packing" — "nasal" qualifier dropped
  - Matcher artifact: concept is present, exact phrase is not
  - **Adjusted: effectively 58/58**

### CRITICAL: Fabricated dosages (3 instances)
The model invented specific dosages not present in the source document:

1. **"prasugrel 10 mg daily"** — source says only "prasugrel" with no dose
2. **"aspirin 81 mg daily"** — source says only "aspirin" with no dose  
3. **"Rivaroxaban was initiated at a renal dose of 15 mg daily"** — source says "renally dosed rivaroxaban" without specifying the exact dose. The 15 mg figure appears in the Discussion section as the ROCKET AF trial dose for CrCl 30-49 mL/min, not as this patient's prescribed dose.

All three dosages are plausible (they match common clinical practice), which makes them more dangerous — a downstream clinician would have no reason to question them. This is the **fabrication** failure mode from the judge taxonomy and the most clinically dangerous type of error.

**Failure mode classification:** fabrication (3 instances)
**Clinical risk:** HIGH — wrong dosage could lead to medication errors

### Implications
Local text-level compression fills information gaps with plausible but unsourced values. The model "knows" common dosages and inserts them when the source is vague. This is worse than leaving the gap because it creates false confidence in specific numbers.

---

## Technique 4: LLM Summarization — Frontier Model / Opus 4.8 (3x, ~470 words)

**Raw score: 53/58 facts present (91%)**
**Adjusted score: 57/58 (98%) after correcting matcher strictness**

### Matcher false negatives (4 — facts actually present)
- f009 [temporal/time_since_event] "six months" → compressed to "6 months" (numeric format change)
- f040 [temporal/event_sequence] "five days" → compressed to "5 days" (numeric format change)
- f054 [categorical/drug_name] "triple antithrombotic therapy" → compressed to "triple therapy" (shortened phrase)
- f055 [categorical/device_type] "simple nasal packing" → compressed to "simple packing" (qualifier dropped from phrase but concept present)

### Genuinely missing (1)
- f044 [temporal/event_sequence] "Cardiology reevaluated the patient's antithrombotic regimen after bleeding recurred"
  - Compressed text jumps to the actions (discontinued rivaroxaban, switched prasugrel to clopidogrel) without mentioning the reevaluation step
  - **Failure mode:** complete_loss of a procedural/temporal fact
  - **Clinical risk:** LOW — the actions themselves are preserved, only the meta-step of "reevaluation" is lost

### No fabrications
Opus preserved the source's vagueness faithfully:
- Medications listed without doses stayed without doses
- "Renally dosed rivaroxaban" stayed vague, no specific mg value inserted
- No information was added that doesn't exist in the source

---

## Head-to-Head Comparison at 3x

| Metric | Opus 4.8 (frontier) | Qwen3-8B (local) |
|---|---|---|
| Fact recall (adjusted) | 57/58 (98%) | 58/58 (100%) |
| Fabrications | 0 | 3 |
| Clinical safety | Clean | Dangerous |
| Word count | ~470 | 440 |

### Key finding
**Fact recall and clinical safety are different axes.** Qwen3-8B scores higher on raw recall (it "found" more facts) but produced 3 fabricated dosages that could cause clinical harm. Opus scores slightly lower on recall but never fabricated information. A pure fact-survival metric would rate Qwen3-8B higher, which is the wrong conclusion for clinical safety.

This highlights a gap in the evaluation framework: the current scoring (CORRECT / PARTIAL / INCORRECT) doesn't penalize fabrication differently from correct recall. The judge's failure_mode taxonomy captures this (fabrication is a labeled failure mode), but it only applies to INCORRECT judgments. A fabricated dosage that matches common practice would be scored CORRECT by a naive matcher — the fact is "present" in the compressed output, it's just wrong.

### Implications for the research
1. **Text-level compression has a fabrication risk that scales inversely with model capability.** Frontier models respect the source's vagueness; weaker models fill gaps with plausible but unsourced values.
2. **Representation-level compression (V-only) cannot fabricate by construction.** It operates on the KV cache, not on generated text. The compressed representation either preserves the original information or loses it — it cannot invent new information. This is a fundamental safety advantage.
3. **Evaluation must score fabrication separately from recall.** A fact-survival metric that treats fabricated-but-plausible answers as correct will systematically overrate text-level compression and underrate the safety advantage of representation-level compression.

---

## Matcher Limitations

The automated scorer uses exact substring matching of entity names and values against the compressed text. Known limitations:

1. **Format sensitivity:** "six months" vs "6 months", "five days" vs "5 days" — numeric vs spelled-out forms are treated as different strings
2. **Phrase sensitivity:** "triple antithrombotic therapy" vs "triple therapy" — shortened phrases miss
3. **Cannot detect fabrication:** the scorer checks presence, not provenance. A fabricated dosage registers as PRESENT because the entity + value are in the text
4. **No semantic matching:** "simple packing" vs "simple nasal packing" misses on exact substring

### Recommended improvements for production scoring
- Add numeric normalization (spelled-out numbers → digits)
- Use the LLM-as-judge (orchestrate.py) instead of substring matching for real experiments
- Add a provenance check: is the fact present in the compressed text AND traceable to the source document?
- Score fabrication as a separate axis from recall, with higher clinical risk weighting

---

## Next Steps
- Run both techniques at 4x compression (~350 words) to find the breaking point
- Run representation-level compression (V-only) at 3x for direct comparison
- Score with the LLM-as-judge instead of substring matching for production results
- Add fabrication detection to the evaluation framework
