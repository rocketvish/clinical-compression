# Clinical Context Compression Pressure Test

Orchestration script for the experiment described in our conversation:
test whether anchor facts in clinical case reports are differentially
preserved as context length increases via clinical-filler padding.

## What this runs

For each case × each context length:

1. Build padded context (case + filler at the specified length, with
   the case placed at beginning/middle/end per `--placement`).
2. For each question in the case, query the answering model with
   `(padded_context, question)` → get a model answer.
3. For each answer, query the judge model with the structured scoring
   prompt → get a CORRECT/PARTIAL/INCORRECT judgment + failure mode.
4. Aggregate across all cases × lengths → summary stats including
   the headline class-vs-instance analysis.

Both answer and judge calls are cached on disk per
`(case_id, context_length)`. Reruns skip cached cells. To force a
specific cell to rerun, delete that one cache file.

## Inputs

Place one JSON file per case in `--cases-dir`. The JSON should be the
direct output of the extraction prompt — same schema:

```json
{
  "case_metadata": {
    "title": "...",
    "specialty": "...",
    "approximate_token_count_original": 3200
  },
  "case_text": "<the full case report body here, OR omit and supply <case_id>.txt next to it>",
  "anchors": [
    {
      "id": "A1",
      "category": "CAT",
      "subtype": "CAT.instance",
      "text": "vancomycin",
      "location": "medications",
      "distinctiveness": "medium",
      "granularity": "instance",
      "paired_anchors": ["A2"],
      "clinical_actionability": "high"
    }
  ],
  "questions": [
    {
      "anchor_id": "A1",
      "question": "Which antibiotic was the patient initially treated with?",
      "expected_answer": "vancomycin",
      "scoring": "keyword_match",
      "granularity_tested": "instance"
    }
  ],
  "filler_blocks": [
    {"block_id": 1, "note_type": "Nursing", "approximate_tokens": 800, "content": "..."}
  ]
}
```

The case body (`case_text`) is required because the extraction prompt
itself doesn't always include it. If absent from the JSON, the script
looks for `<case_id>.txt` next to the JSON file.

## Setup

```bash
pip install anthropic tiktoken tenacity
export ANTHROPIC_API_KEY=sk-...
```

## Running

```bash
python compression_experiment.py \
  --cases-dir ./cases \
  --output-dir ./results \
  --context-lengths 8000 16000 32000 64000 128000 \
  --placement middle \
  --answering-model claude-opus-4-7 \
  --judge-model claude-sonnet-4-6
```

For the today's pressure test on the 6 anticoagulation + endocarditis
cases, with the default ladder of 5 lengths, you're looking at:

- 6 cases × 5 lengths × ~12 questions = ~360 answer calls
- 360 judge calls
- Roughly $20-50 in API costs depending on case length and model
- Wall clock: 1-3 hours with the default 0.5s pacing between calls

## Outputs

- `results/answers/<case>_<length>.json` — raw answers, cached
- `results/judgments/<case>_<length>.json` — judge outputs, cached
- `results/summary.json` — aggregate stats
- `results/summary.csv` — flat per-anchor results suitable for pandas

The script prints the headline class-vs-instance analysis to stdout
at the end of the run. That's the result that matters most for
deciding whether Vishnu's hypothesis transfers.

## What to look for

The headline pattern Vishnu's coding-agent result predicts:

- At short context: most CAT.instance anchors are recovered correctly
- At medium-long context: `instance_lost_class_preserved` count rises
  faster than `both_lost` (the failure mode is *class collapse*, not
  total information loss)
- At extreme context: `both_lost` rises but the *ratio* of
  `instance_lost_class_preserved` to `both_lost` stays high

If you see that pattern across multiple cases, you have a publishable
preliminary result. If you don't see compression effects at all, your
context lengths are too short for the frontier models you're using —
extend the ladder upward or move to smaller (less context-robust)
models.

## Caveats

- Token counting uses tiktoken (`cl100k_base`); Anthropic tokenization
  differs slightly. Actual context lengths run ~3% over target due to
  separator overhead. This is fine for relative comparisons across
  lengths, which is what the experiment cares about.
- The script assumes the answering model can fit the longest requested
  context in its window. Claude Opus 4.7 supports 200K tokens by
  default. For lengths >200K you would need additional configuration.
- LLM-as-judge has known leniency bias. Spot-check at least 10% of
  PARTIAL judgments manually before drawing conclusions.
- Different answer and judge models are strongly recommended. The
  script warns if you set them identical.