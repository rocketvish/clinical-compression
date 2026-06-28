# Medical Fact Extractor — Plan & Key Decisions

## Experiment Overview

Take clinical cases (initially brief uploaded cases, later ER-REASON dataset), extract ground-truth facts into a structured store, compress the documents using multiple techniques, and score fact survival across compression methods and ratios. The enriched document methodology (D → D') is a proof of concept only; real experiments use ER-REASON longitudinal records.

## Architecture

```
Document D → Fact Extractor (Opus) → Fact File F (JSON)
                                          ↓
                              Doctor Validation of F (5-10 cases only)
                                          ↓
                              FactFile-to-Case Converter
                                          ↓
                              Case JSON (anchors, questions, filler)
                                          ↓
Document D → Compression (open-weight model) → Compressed D
                                          ↓
                              Answering Model (queries against compressed D)
                                          ↓
                              LLM-as-Judge (orchestrate.py)
                                          ↓
                              Fact Type × Failure Mode Matrix
```

## Status

### ✅ Done
- Pydantic schema (FactFile, Fact, enums, validators, reconstruct()) — 18 tests
- Extraction pipeline (prompts.py, validate.py, merge.py, CLI tools) — 40 tests total
- Fact taxonomy with judge category mapping (fact-taxonomy.md)
- First case extracted: bleeding triple therapy (58 facts, doctor-validated)
- Second case extracted: endocarditis (127 facts, doctor-reviewed)
- Decomposition rules 1-14 implemented and tested
- LLM-as-judge prompt and orchestrate.py (pre-existing, ready to use)
- README with pipeline instructions
- Model selection: Qwen3-8B (primary) + Qwen3-14B (secondary) — general-purpose, no medical fine-tunes

### 🔧 In Progress
- Prompt tuning based on doctor feedback (rules 10-14 added, testing on next case):
  - Rule 10: preserve disease qualifiers (CKD stage 3, CHF with preserved EF)
  - Rule 11: treatment regimens are not drugs (triple therapy ≠ drug_name)
  - Rule 12: deduplicate facts across document sections
  - Rule 13: diagnosis hierarchy (etiology → pathology → consequence as composite)
  - Rule 14: progressive conditions as temporal trajectory, not duplicate diagnoses
  - Fix reconstruct() to merge dosages with drug names via group_id
  - Strengthen verification prompt to reliably return JSON-only
  - Fix merge.py to slice first [ last ] for prose-wrapped responses

### ⬜ Next
- Extract case 3, doctor-validate — if clean, prompt is stable
- Build FactFile → Case JSON converter (Phase A.5 below)
- Profile perplexity distributions on clinical text (Qwen3-8B, then Qwen3-14B)
- Download ER-REASON, start MIMIC-IV credentialing (access pending)
- Adapt Bearing compression code for Qwen3 architecture

## Key Decisions

### Extraction approach
- **Two-pass extraction** via claude.ai (Max plan, no API cost):
  - Pass 1: full extraction with structured prompt
  - Pass 2: verification pass catches missed facts (typically 5-8 per case)
  - Doctor review on ground-truth cases only (5-10 cases), then trust the tuned prompt at scale
- Temperature 0 for determinism
- Few-shot worked example (13 facts from synthetic paragraph) in the prompt

### Extractor model
- **Claude Opus via Max plan** — paste prompt into claude.ai, copy JSON back. No API needed for 5-10 cases. Add API runner when scaling to ER-REASON.

### Compression models (separate from extractor)
- Open-weight models required (need KV cache internals for V-only optimization)
- **Primary: Qwen3-8B dense** at 8-bit quantization — direct successor to Qwen 2.5 7B, substantially better representations, fits easily on RTX 5090 (32GB VRAM)
- **Secondary: Qwen3-14B dense** at 8-bit quantization (~14GB weights, ~18GB for KV cache) — biggest dense model that fits comfortably with cache headroom
- Avoid MoE models (Qwen3-30B-A3B etc.) — expert routing changes KV cache behavior in ways that complicate V-only compression
- No medical fine-tunes — general-purpose models outperform at 7-14B scale
- Two models gives us a transfer story: does the technique hold across model sizes within the same family?

### Fact storage format
- **Atomic facts** — compound facts decomposed into single-category entries linked by `group_id`
- **Store both verbatim span and normalized content** — verbatim for traceability, normalized for scoring
- **Primary category per fact** with tags for cross-cutting concerns
- **Negation stored as explicit flag** — critical for polarity inversion detection
- **Document metadata in header** — note type, date, author, sections present

### Fact taxonomy (see fact-taxonomy.md for full reference)
- Extraction categories: Categorical, Temporal, Quantitative, Clinical Reasoning
- Judge categories: CAT.*, TEMP.*, QUANT.*, REAS.* (mapped in taxonomy doc)
- Failure modes: class_collapse, instance_swap, status_loss, negation_loss, qualifier_loss, uncertainty_loss, magnitude_error, unit_missing, binding_failure, fabrication, refusal, attribution_loss
- Hypothesis: temporal degrades first → clinical reasoning → quantitative

### Compression techniques to test
1. V-only virtual token optimization (requires gradient descent)
2. V-only + KV cache eviction (compress-then-evict)
3. LLM summarization — Qwen3-8B local (text-level, no KV cache access needed)
4. LLM summarization — frontier model via Max plan (best possible text-level compression)
5. Pure KV cache eviction (no compression — expected to fail, replicates Bearing finding)
6. Control (uncompressed)

Techniques 3-4 are runnable today without Bearing code adaptation. The comparison between representation-level (1-2) and text-level (3-4) is a core paper contribution — they may preserve different things and fail differently.

### Compression ratios
- 2x, 3x, 3.5x, 4x (matching Bearing frontier curve)

### Evaluation: Multi-tier design

**Tier 1: Clean fact recall.** Compressed context, probe questions per anchor, does each fact survive? Baseline analog of 8/8 tasks in Bearing. Orchestrate.py handles this.

**Tier 2: Difficulty-graded recall.** Grade facts by expected retrieval difficulty:
- Easy: patient demographics, common diagnoses, current medications (high-frequency, explicitly stated)
- Medium: specific dosages, lab values with units, rare drug names (high-surprisal, should be protected by perplexity weighting)
- Hard: temporal relationships across the document, dosage changes, conditional reasoning, negated facts, uncertainty markers (multi-token relationships, qualifier tokens that get downweighted)

This directly tests the degradation hypothesis. If temporal facts fail before quantitative facts across all techniques, the Bearing pattern replicates on clinical text.

**Tier 3: Noise injection / adversarial.** Most clinically realistic tier. Real longitudinal records contain outdated information, conflicting assessments, corrected values, copy-pasted templates with stale data. Compression must handle this.

Three flavors of noise:

*Contradictory facts* — inject a filler note that says "metformin 250mg" when the real dosage is 500mg. After compression, does the model return the correct dosage or the injected one? Tests whether compression preserves the signal about which mention is authoritative.

*Plausible substitutions* — inject drug names from the same class. Patient on rivaroxaban, filler mentions apixaban in similar context. Tests the instance_swap failure mode — does compression make the model more likely to cross-wire similar entities?

*Temporal confusion* — inject events with dates that conflict with the real timeline. After compression, can the model reconstruct the correct sequence? Hardest test for temporal facts.

**Hypothesized technique-level finding for Tier 3:** text-level summarization (techniques 3-4) may be more robust to noise because the model reasons about contradictions during compression and can choose the authoritative version. Representation-level compression (techniques 1-2) preserves all information proportional to surprisal — including planted errors. If noise and real facts have similar surprisal, V-only compression preserves both equally. This would be a real clinical tradeoff: representation-level gives better overall fact survival (Tier 1-2) but worse noise robustness (Tier 3), while text-level gives worse fact survival but better noise filtering.

**Implementation:** adversarial facts are a special type of filler block in orchestrate.py. For each case, generate 5-10 planted errors (wrong dosages, swapped drugs, conflicting dates). Probe questions ask about the contested fact. Judge scores whether the answer matches the original or the planted error.

### Scoring methodology
- Targeted probes: per-anchor questions against compressed context
- LLM-as-judge (orchestrate.py) scores CORRECT / PARTIAL / INCORRECT
- Judge classifies failure mode per anchor
- Difficulty grade per anchor for Tier 2 analysis
- Adversarial accuracy (original vs planted error) for Tier 3
- Calibrate judge against doctor ratings on small sample

## Build Order

### Phase A: Schema & Extractor ← CURRENT
1. ✅ Pydantic schema encoding the fact taxonomy
2. ✅ Extraction prompt with synthetic worked example
3. ✅ Local pipeline: build_prompt → paste → validate → verify → merge
4. ✅ Verification pass prompt (exhaustiveness check)
5. 🔧 Doctor validation on first cases → tune prompt (in progress)

### Phase A.5: FactFile → Case JSON Converter (after extractor stabilized)
The bridge between extraction and evaluation. Takes a validated FactFile and produces the Case JSON that orchestrate.py consumes.

Must generate:
1. **Anchors** — map each Fact to an Anchor with judge-compatible subtype (CAT.instance, QUANT.dose, etc.), distinctiveness, granularity, clinical_actionability. Mapping defined in fact-taxonomy.md.
2. **Questions** — generate one probe question per anchor with expected_answer and scoring type. Can be templated ("What medication was the patient taking for X?") or LLM-generated for natural phrasing.
3. **Filler blocks** — realistic clinical text to pad context to target lengths. Source from ER-REASON notes, synthetic generation, or a shared filler library across cases.
4. **class_node_present** — for CAT.instance anchors, check whether the source document contains the class-level term (for Vishnu's class-vs-instance hypothesis).

Output: Case JSON matching orchestrate.py's expected format (case_metadata, anchors, questions, filler_blocks).

### Phase B: Compression Experiments (after converter built)
1. ✅ Profile perplexity distributions on clinical text (4-tier, both cases, Qwen3-8B)
2. Survey and adapt Bearing compression code for Qwen3 architecture (Claude Code surveying)
3. **Runnable now without Bearing adaptation:**
   - LLM summarization — frontier model via Max plan (paste into claude.ai)
   - LLM summarization — Qwen3-8B local (prompt-based compression)
   - Pure KV cache eviction (basic attention score computation + truncation)
4. **Needs Bearing adaptation:**
   - V-only virtual token optimization
   - V-only + KV cache eviction (compress-then-evict)
5. Run all 6 techniques at target ratios (2x, 3x, 3.5x, 4x)
6. Run on Qwen3-8B first, Qwen3-14B second
7. Orchestrator runs Tier 1-3 eval against compressed contexts
8. Judge scores fact survival and failure modes

### Phase C: Analysis
1. Aggregate into fact type × failure mode × technique × ratio × model × eval tier matrix
2. Test degradation hypothesis (temporal → reasoning → quantitative)
3. Class-vs-instance analysis (the headline result)
4. Cross-model comparison: do 8B and 14B show the same degradation patterns?
5. Cross-technique comparison: what fails differently between text-level and representation-level?
6. Tier 3 analysis: noise robustness tradeoff between compression paradigms
7. Generate paper figures including four-tier perplexity profiles

## Open Questions
- Compression time per chunk on RTX 5090 (determines experiment throughput)
- How many ER-REASON cases to run at scale (5-10 for validation, then?)
- Qwen3 architecture changes from Qwen 2.5 — any impact on V-only optimization? (check attention head count, GQA config)
- Question generation strategy for the converter: templated vs LLM-generated?
- Filler block source: ER-REASON notes, synthetic, or shared library?
- Adversarial fact generation: manual per case or templated from fact file?
- How to handle Tier 3 scoring — binary (original vs planted) or graded?
