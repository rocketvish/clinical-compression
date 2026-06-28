# Medical Context Compression — Research Plan

## What we're testing

Can the representation-level compression techniques from the Bearing series (V-only perplexity-weighted pooling, KV cache eviction, compress-then-evict) transfer from coding agent transcripts to longitudinal clinical records? What breaks, how dangerous is each failure mode, and can a lightweight verification architecture catch the dangerous ones?

## Background

This research extends the Bearing blog series (rocketvish.substack.com) on context compression for AI coding agents into the medical domain.

### Techniques developed (Bearing Parts 4-5)

**V-only perplexity-weighted compression (Part 4, published).** Create virtual tokens whose Value embeddings match the original text's Value vectors via optimization. Exclude Keys from the loss (RoPE makes pooled K targets unmatchable). Weight tokens by surprisal during pooling so high-information tokens (drug names, identifiers, specific values) dominate the compressed representation while boilerplate gets downweighted. Position interpolation via torch.linspace preserves attention routing. Results: 3.2x lossless on individual turns, 2x lossless across 10-turn sequential conversations.

**Compress-then-evict (Part 5, in progress).** Compress all turns uniformly at 2x, then evict least-attended cache entries using pre-state attention importance. Results: 8/8 at 3x compression — neither pure compression (4/8) nor pure eviction (2/8) works alone. Pre-state attention beats post-state attention (8/8 vs 7/8). Frontier: 3x lossless, 3.5x near-lossless (7-8/8), significant degradation beyond 4x.

**Key findings relevant to medical application:**

Degradation follows a consistent pattern: specific identifiers degrade to model priors before structural facts degrade. In coding, bcryptjs degrades to bcrypt (wrong library version) before "uses a password hashing library" (structural understanding) degrades. The medical analog: metformin 500mg → metformin (lost dosage) → metoprolol (wrong drug entirely) → "patient takes an oral diabetes medication" (structural, last to go). Characterizing exactly where clinical text falls on this gradient is a core research question.

Token exemption is counterproductive. Keeping specific tokens verbatim during compression forces harder compression on everything else, reducing total information preserved. Uniform compression distributes fidelity loss evenly and consistently outperformed exemption variants. This finding shapes the architecture: we don't protect facts during compression. We extract them separately and compress uniformly.

Abstraction level matching: representation-level signals work for representation-level decisions. Text-level signals (regex, statistical properties) crossing into representation-level decisions consistently failed. This principle applies to the compression pipeline but not to the extraction pipeline, which operates on original uncompressed text where text-level tools are reliable.

### Why medical

Patient records are the natural analog to coding agent transcripts: sequential encounters over time (visits = turns), full of specific details where wrong values have real consequences, high boilerplate content that perplexity weighting should handle well, and context that grows over years or decades — far exceeding coding session lengths.

The stakes are fundamentally different. bcryptjs → bcrypt produces a fixable build error. metformin → metoprolol could be fatal. This demands both rigorous failure characterization and a safety architecture.

### Hardware and setup

RTX 5090 (32GB VRAM), Windows 11, Python 3.12 venv, PyTorch nightly cu128. Primary model: Qwen 2.5 Coder 7B-Instruct at 8-bit quantization (same as Bearing experiments). May add a medical-tuned open-weight model (e.g., OpenBioLLM, Meditron variant) to separate domain transfer questions from model knowledge gaps.

### Team

One researcher, one doctor, two medical doctors.

---

## Compression techniques to test

**Primary: V-only perplexity-weighted compression + KV cache eviction.** Direct transfer of the Bearing recipe. This is the main research question — does it work on clinical text at comparable ratios?

**Baseline: Codex compaction API with prompt engineering.** Text-level compression via foundation model summarization. Answers: does representation-level compression preserve different things than text-level compression? If so, what? This is also practical — a prompt-engineered compaction baseline represents what someone would build without the representation-level techniques.

**Secondary: text-based compression techniques.** Other text-level approaches for comparison, including structured extraction + summarization pipelines.

**Exploratory: lightweight file system.** Minimal structured storage for critical patient facts — single flat file per patient, human-readable. Not a replacement for compression but a complement. Must stay extremely lightweight; resist the temptation to overload it with metadata. This overlaps with the verification store (Layer 2 of the architecture below).

Target compression ratios: 2x is the minimum useful threshold. 3x is the target for "lossless" (matching the coding result). 3-4x is the practical operating range — compress to 3-4x, let the model accumulate new context, recompress when the window fills. We may find clinical text supports higher or lower ratios than code; establishing this threshold is the first experimental goal.

### Model considerations

Start with Qwen 2.5 Coder 7B to isolate the technique transfer question (same model, different domain). If the technique doesn't transfer on Qwen, that's informative — it tells us domain-specific model knowledge matters for what compression preserves. Then consider a medical-tuned model for the full experimental campaign if warranted. Using open-weight models enables representation-level techniques across model families.

---

## Architecture: compression with verification layer

### Design principle

Don't trust compression alone for high-stakes information. Extract critical facts before compression into a separate store, compress uniformly (proven to be optimal), and verify model output against the store after generation. This mirrors clinical workflow: physicians reason from working memory but verify against the chart.

Important clarification: the extraction pipeline and the compression pipeline are completely separate operations. Extraction copies facts out of the original text into a structured store. Compression then proceeds on the full text at uniform ratios — no tokens are exempted, no compression budget is affected by extraction. The facts exist in two places: approximately in the compressed representation (where perplexity weighting naturally gives high-surprisal clinical terms more weight), and exactly in the structured store.

### Three layers

**Layer 1 — Compressed working context.** The model reasons from compressed patient history via the KV cache. Fast, fits in the context window, preserves structural understanding ("patient has diabetes, on oral medications, recent labs showed elevated HbA1c"). This is where V-only perplexity-weighted compression and cache eviction operate.

**Layer 2 — Structured verification store.** Pre-compression, an extraction pipeline pulls critical clinical facts from the original text into a structured file. Single file per patient, flat structure, human-readable. Schema defined with the doctor collaborators (see below). This is purely additive storage — it doesn't interact with or constrain the compression pipeline.

**Layer 3 — Post-generation verification.** After the model generates a response from compressed context, cross-reference any clinical details against the structured store. If the model says "continue metoprolol" but the store says "metformin," flag the discrepancy before it reaches anyone.

### Structured vs. unstructured boundary

The core architectural question: what goes in the verification store (structured, must be exact) vs. what stays in compressed context (unstructured, can be approximate)?

In clinical text, this boundary is cleaner than in code. Structured facts map to known ontologies and finite vocabularies. Unstructured content is clinical reasoning that compression needs to preserve approximately.

**Structured (→ verification store):** medications with dosages and frequencies (RxNorm vocabulary), allergies with reaction types, lab values with units and dates (LOINC codes), active diagnoses (ICD-10), vital signs with values, surgical history, code status, social history (smoking, alcohol), family history.

**Unstructured (→ compressed context):** clinical reasoning, differential diagnoses, subjective assessments, plan rationale, physician decision-making narrative.

Draft schema for the structured store:

```yaml
patient_id: [id]
active_medications:
  - name: metformin
    dose: 500mg
    frequency: BID
    start_date: 2024-03-15
allergies:
  - substance: penicillin
    reaction: anaphylaxis
active_diagnoses:
  - description: Type 2 diabetes
    code: E11.9
last_labs:
  - name: HbA1c
    value: 7.2%
    date: 2024-03-15
  - name: Cr
    value: 1.1
    date: 2024-03-15
vitals:
  - BP: 128/82
  - HR: 72
  - SpO2: 98%
code_status: Full code
surgical_history:
  - Appendectomy (2015)
social:
  - Non-smoker
  - Occasional alcohol
family_history: []
```

This schema is a starting draft. The doctor collaborators should refine it — they know what's clinically critical to never lose. Keep it flat and minimal.

### Extraction pipeline

The extraction pipeline operates on original uncompressed clinical text, where text-level tools are reliable. This is consistent with the abstraction level matching principle: text-level extraction on text-level data, representation-level compression on representation-level data.

**Recommended approach: section-aware regex + dictionary matching.** Clinical notes have predictable section headers (MEDICATIONS, ALLERGIES, LABS, ASSESSMENT). Within those sections, patterns are highly constrained — drug names from a formulary (finite dictionary), lab values in "name value unit" format, vitals in standard notation. This covers the highest-priority verification store facts with debuggable, measurable tooling.

**If needed: add SciSpaCy/MedSpaCy for free-text entity detection.** Medications and diagnoses mentioned in narrative sections (HPI, assessment/plan) won't be caught by section-aware regex. Clinical NER adds coverage here, but start without it and measure the gap.

**Critical: measure extraction accuracy independently.** Extraction accuracy caps the verification layer's effectiveness. If extraction misses a medication in the original text, the verification layer can't catch the compressed representation getting it wrong. Measure extraction precision and recall on a sample of notes before plugging into the full pipeline.

---

## Datasets

**ER-REASON (starting point).** 25,174 notes spanning discharge summaries, progress notes, H&Ps, consults, echocardiography reports, imaging notes, and ER provider documentation across 3,984 encounters. Multiple note types for testing compression across clinical text formats. Good longitudinal depth within encounters. Limited to ED visits. Available at physionet.org/content/er-reason/1.0.0/. Paper: arxiv.org/pdf/2505.22919.

**MIMIC-IV (validation).** Real de-identified records from Beth Israel Deaconess Medical Center. Only discharge summaries and imaging reports — less note variety but discharge summaries are already human-compressed (physician summarizing a hospitalization), making them a harder compression test. Requires PhysioNet credentialing (CITI training, ~1-2 days to complete). Paper: nature.com/articles/s41597-022-01899-x.

**TIMER-Bench (evaluation methodology).** Standardized temporal reasoning evaluation over clinical records. Tests exactly what sequential compression needs to preserve: temporal relationships across encounters. Use as evaluation framework on ER-REASON data. GitHub: github.com/som-shahlab/TIMER. Paper: nature.com/articles/s41746-025-01965-9.

---

## Evaluation framework

### Primary metric: anchor fact recall

Define anchor facts per note type — ground-truth clinical facts extracted from the original note (medication X at dose Y, lab Z at value W, diagnosis Q with code R). Generate from compressed context. Score at three granularity levels:

**Exact match:** metformin 500mg BID. Strictest — measures whether compression preserves specific values.
**Category match:** metformin at some dose. Measures whether the right entity survives even if specifics degrade.
**Structural match:** patient takes an oral diabetes medication. Loosest — measures whether structural understanding survives.

The gap between these levels *is* the degradation pattern. Mapping where clinical text falls on this gradient is a core deliverable.

"Lossless" = all anchor facts preserved at exact match level, analogous to 8/8 task pass in the coding eval.

### Secondary metric: clinical decision equivalence

Given a patient history, do full-context and compressed-context produce the same clinical decisions? Scored by the doctor collaborators as: clinically identical, clinically acceptable (different but safe), or clinically different (would change patient care). This requires doctor time and is deferred to Phase 4.

### Tertiary metrics

Temporal reasoning preservation (TIMER-Bench methodology): can the model reconstruct event sequences from compressed history?

Decision difficulty: to what degree do clinical decisions become harder due to information loss from compression? Some decisions are judgment calls where missing a supporting fact makes the call harder without changing the outcome. Distinct from wrong decisions.

Inference cost estimation: compressed context vs. full context, assuming clinically equivalent decisions are achieved.

---

## Experimental phases

### Phase 1: Technique validation (researcher-led, no doctor needed)

**Goal:** Does the compression recipe transfer to clinical text? What's the lossless threshold?

**Prerequisite:** Download and profile ER-REASON — note lengths, vocabulary distribution, boilerplate ratio. The boilerplate ratio tells us whether perplexity weighting will have the same leverage it had on code (where boilerplate was 40-60% of tokens).

**Experiments:**

1. Single-note compression sweep: pick 3 different note types (discharge summary, progress note, H&P). Run V-only perplexity-weighted compression at 2x, 3x, 3.5x, 4x. Measure anchor fact recall at all three granularity levels.

2. Codex compaction API baseline: compress the same notes via text-level summarization. Compare what's preserved vs. lost relative to representation-level compression. Does representation-level compression preserve different things than text-level?

3. Sequential compression across encounters: pick patients with 10-20+ encounters, compress each visit as a "turn," test recall of anchor facts accumulated over the full history.

4. Compress-then-evict on sequential results: does the 3x lossless finding replicate on clinical text?

**Deliverable:** Lossless thresholds for clinical text by note type. Comparison to coding thresholds. Initial comparison of representation-level vs. text-level compression. Boilerplate analysis.

### Phase 2: Failure taxonomy (needs doctor time)

**Goal:** Characterize what degrades first and what's clinically dangerous.

**Experiments:**

5. At each compression ratio, catalog every incorrect or degraded anchor fact. Classify by type: drug name, dosage, lab value, temporal relationship, diagnosis, procedure, clinical reasoning.

6. Doctor rates each failure on a severity scale: clinically insignificant, could cause harm, dangerous. This creates the risk map.

7. Compare degradation patterns to coding: do structural facts (patient has diabetes) survive longer than specific details (metformin 500mg BID)? Is the gradient the same shape?

8. Root-cause analysis: for cases where compression causes a clinical decision change, trace back to the specific lost fact. Feed back into the failure taxonomy.

**Deliverable:** Ranked failure taxonomy with clinical severity ratings. This is the most publishable piece for a medical AI audience.

### Phase 3: Verification layer prototype (researcher-led, doctor validates)

**Goal:** Build and measure the safety net.

**Experiments:**

9. Finalize structured schema with doctor collaborators.

10. Build extraction pipeline (section-aware regex + dictionary matching on original text). Measure extraction accuracy independently — precision and recall on a sample of notes.

11. Build verification step: after generating from compressed context, cross-reference output against the store. Measure catch rate (what percentage of compression-induced errors does the verification layer flag?).

12. End-to-end test: extract → compress → generate → verify → report. Compare unverified vs. verified error rates.

**Deliverable:** Extraction accuracy, verification layer catch rate, end-to-end error rates. Target: 90%+ catch rate for clinically dangerous errors.

### Phase 4: Clinical equivalence (needs doctor heavily)

**Goal:** Does compressed context produce the same clinical decisions?

**Experiments:**

13. Doctor defines 3-4 clinical decision questions per encounter: prescriptions, differential diagnosis, lab orders, interaction flags.

14. Run each question against full context and compressed context at the recommended ratio. Doctor blind-reviews both outputs.

15. Score each pair: clinically identical, clinically acceptable, clinically different.

16. Root-cause any clinical differences to specific lost facts. Feed back into failure taxonomy and inform whether the verification layer would have caught them.

**Deliverable:** Clinical equivalence rate at recommended compression ratio with and without verification.

### Phase 5: Retrospective salience model (future, depends on Phases 1-4)

**Goal:** Learn which clinical facts matter from observed usage patterns.

**Experiments:**

17. Run diverse clinical queries against patient histories, tracking attention to each cache entry across queries.

18. Accumulate attention evidence to identify which facts the model consistently attends to.

19. Train lightweight model to predict clinical importance from note features (note type, section, entity type, temporal recency).

20. Compare learned salience vs. perplexity weighting for informing compression decisions.

**Deliverable:** A clinical salience model — automated clinical significance scoring. This is speculative; limited prior work exists on retrospective salience in clinical contexts.

### Parallelism and scheduling

Phases 1 and 3 (extraction pipeline) can start in parallel since they share no dependencies. Phase 3 extraction work (steps 9-10) can begin while Phase 1 experiments are running.

Phases 2 and 4 need doctor time — batch meetings to use their availability efficiently.

Phase 5 depends on all prior phases and is future work.

Start MIMIC-IV credentialing (CITI training) immediately in parallel with everything — it's a 1-2 day gate with no reason to defer.

---

## Publishability

**Strongest paper: failure taxonomy (Phase 2) + verification layer (Phase 3).** Nobody has systematically characterized how representation-level compression degrades clinical information with clinical severity ratings. The verification layer is the practical solution. Together: "We compressed longitudinal patient records. Here's exactly what breaks, how dangerous each failure mode is, and an architecture that catches the dangerous failures."

**Target venues:** CHIL, ML4H workshop at NeurIPS, JAMIA, npj Digital Medicine.

**Title direction:** "Failure Modes and Safety Verification for Context Compression in Clinical AI Systems"

---

## Open questions for collaborators

1. What clinical facts must never be lost? (Defines the verification store schema — draft above, needs refinement.)
2. What's your severity rating for different types of information loss? (Defines the failure taxonomy rubric for Phase 2.)
3. What clinical decision questions would you ask given a patient history? (Defines the Phase 4 evaluation.)
4. How do you personally distinguish "important" from "background" when reading a chart? (Informs the salience model direction in Phase 5.)
5. What does your actual workflow look like when reviewing a long patient history? (The verification layer should mirror real clinical workflow.)
6. Are there note types or clinical scenarios where lossy compression is more acceptable? (Helps prioritize where the lossless threshold matters most.)
