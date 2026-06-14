You are scoring the output of a language model on a clinical anchor
fact recovery task. The model was given a clinical case report (or a
compressed/padded version of one) and asked questions about specific
facts in the case. Your job is to judge whether each model answer
correctly recovered the anchor fact it was asked about.

You must apply scoring rules calibrated to the anchor category and
subtype. Clinical equivalence matters: "BID" and "every 12 hours" and
"twice daily" all express the same dosing frequency, and a model that
produces any of them in response to a question about q12h dosing has
correctly recovered the anchor. But "antibiotics" is NOT equivalent to
"vancomycin," and "elevated INR" is NOT equivalent to "INR 8.5."

You will receive the following inputs:
  - the original anchor fact (verbatim quote from the case)
  - the anchor's category and subtype
  - the question that was posed to the model
  - the expected answer
  - the model's actual answer

You will return a structured judgment for each item.

## SCORING RULES BY CATEGORY

### CAT (Categorical facts)

CAT.class anchors:
  CORRECT if the model's answer references the same class or category
  as the anchor, even using synonymous terminology. "Anticoagulation"
  ≡ "blood thinner therapy" ≡ "antithrombotic medication." A more
  specific answer (naming the instance when the question asked about
  the class) is also CORRECT, since recovering greater specificity
  than required implies recovering the class.

CAT.instance anchors:
  CORRECT if the model's answer names the specific entity, with
  acceptable variants for well-known synonyms or brand-generic pairs
  ("apixaban" ≡ "Eliquis"; "acetaminophen" ≡ "paracetamol"; "MI" ≡
  "myocardial infarction"). INCORRECT if the model names only the
  class ("anticoagulant" when the anchor was "apixaban"). This is
  the most important category for the experiment — be strict.
  INCORRECT if the model names a different instance within the same
  class ("rivaroxaban" when the anchor was "apixaban").

CAT.qualifier anchors:
  CORRECT only if both the base entity AND the qualifier are recovered.
  For "methicillin-susceptible S. aureus with reduced vancomycin
  susceptibility," the model must mention both MSSA and the reduced
  vancomycin susceptibility to score CORRECT. Recovering only the base
  ("S. aureus") is INCORRECT. Recovering the base plus partial qualifier
  is PARTIAL.

CAT.alert anchors:
  CORRECT only if the alert is recovered with sufficient specificity to
  preserve clinical action. "Penicillin allergy with anaphylaxis"
  requires both the agent and the severity to be CORRECT. "Drug allergy"
  alone is INCORRECT — the missing specificity could lead to
  inappropriate prescribing.

CAT.negated anchors:
  CORRECT if the model's answer preserves the negation. "Denies chest
  pain" ≡ "no chest pain" ≡ "chest pain absent." INCORRECT if the
  model reports the underlying entity without negation ("chest pain"
  when the anchor was "denies chest pain") — this is the most
  dangerous failure mode for negation and should be marked clearly.
  INCORRECT if the model reports an opposite affirmation ("has chest
  pain" when the anchor was "denies chest pain").

### TEMP (Temporal facts)

TEMP.date anchors:
  CORRECT if the model recovers the date with acceptable format
  variation (11/22/2023 ≡ November 22, 2023 ≡ 2023-11-22). INCORRECT
  if any component differs (year, month, or day).

TEMP.duration anchors:
  CORRECT if duration matches with acceptable unit conversion ("14
  days" ≡ "two weeks"; "6 months" ≡ "half a year"). INCORRECT if the
  numeric duration differs, even if the timeframe is approximately
  similar ("3 weeks" is INCORRECT for "14 days" — close but not
  equivalent for clinical purposes).

TEMP.since anchors:
  CORRECT if the time elapsed and the referenced event are both
  preserved. "6 months post-stent" requires both "6 months" and
  "stent" to be recovered. Approximate matches acceptable on the
  time portion ("about 6 months" ≡ "6 months").

TEMP.status anchors:
  CORRECT only if the status change is explicitly preserved. For
  "recently discontinued apixaban," the model must indicate both the
  entity (apixaban) AND the discontinuation status. INCORRECT if the
  model reports the entity without the status change ("on apixaban"
  when the anchor was "recently discontinued apixaban") — this is
  one of the highest-stakes failure modes and should be flagged.

TEMP.sequence anchors:
  CORRECT if the relative ordering of events is preserved, even if
  exact dates are not. "Started vancomycin, then switched to
  ampicillin+gentamicin when culture results returned" requires the
  sequence (vancomycin → switch → ampicillin/gent) to be intact.
  INCORRECT if the order is reversed or if a key transition event is
  dropped.

TEMP.trajectory anchors:
  CORRECT if the direction of change is preserved. "Hgb trending
  down from 12 to 8" ≡ "hemoglobin dropping" ≡ "Hgb decreasing."
  INCORRECT if the direction is reversed or absent. PARTIAL if
  direction is correct but specific values are wrong ("Hgb falling"
  when anchor specified "from 12 to 8" — direction preserved,
  magnitude lost).

### QUANT (Quantitative facts)

QUANT.dose anchors:
  CORRECT if the numeric value AND unit are both preserved exactly.
  "5 mg" requires both "5" and "mg." Acceptable: "5 milligrams,"
  "5 mg PO." INCORRECT if either the number or unit is wrong, or if
  the dose is given without units. Weight-based dosing requires the
  rate AND the unit ("20 mg/kg" must include "/kg").

QUANT.freq anchors:
  CORRECT if the frequency is preserved with acceptable clinical
  synonym variation. "BID" ≡ "twice daily" ≡ "every 12 hours" ≡
  "q12h" ≡ "2x/day." "TID" ≡ "three times daily" ≡ "q8h."
  "Once daily" ≡ "QD" ≡ "daily." Be permissive here — these are real
  clinical synonyms. INCORRECT only if the actual frequency differs
  (q8h vs q12h, even though both are "multiple times daily," are
  clinically distinct).

QUANT.lab anchors:
  CORRECT if the numeric value and unit are both preserved. Tolerance:
  numeric values must match to one decimal place where the anchor
  has one decimal place (anchor "INR 8.5" requires answer "8.5",
  not "8" or "approximately 8"). Units must be present where the
  anchor includes them. PARTIAL if the number is correct but units
  are missing (clinically problematic but not a fabrication).

QUANT.vital anchors:
  Same rules as QUANT.lab. Blood pressure requires both systolic and
  diastolic ("88/52" is one anchor, not two). "Hypotensive" or "low
  BP" is INCORRECT when the anchor is a specific number — clinical
  interpretation is not equivalent to the measurement.

QUANT.anthro anchors:
  Same rules as QUANT.lab.

### REAS (Clinical reasoning facts)

REAS.considered anchors:
  CORRECT only if the model recovers both (a) that the diagnosis was
  considered, and (b) the reason it was ruled out (or the evidence
  that lowered its probability). For "ICH was considered but ruled
  out based on negative CT," the model must mention both
  consideration of ICH and the negative CT finding. PARTIAL if
  consideration is recovered but the ruling-out evidence is lost.
  INCORRECT if only the final diagnosis is reported with no mention
  of considered alternatives.

REAS.conditional anchors:
  CORRECT only if both the condition AND the consequent are preserved.
  For "if creatinine clearance drops below 30, reduce dose," the
  model must capture the conditional structure (the IF and the
  THEN). INCORRECT if the conditional is collapsed to an
  unconditional statement ("reduce dose" or "CrCl 30 cutoff" alone).

REAS.causal anchors:
  CORRECT if the causal link is preserved between the two entities.
  "Started warfarin for mechanical valve" requires both entities AND
  the causal connection (FOR, DUE TO, BECAUSE). PARTIAL if the
  entities are recovered without the causal link (the model says
  "patient on warfarin, has mechanical valve" without connecting
  them). INCORRECT if the wrong causal direction is asserted.

REAS.uncertain anchors:
  CORRECT if the uncertainty marker is preserved. "Likely
  pneumonia" ≡ "probable pneumonia" ≡ "concerning for pneumonia."
  INCORRECT if the uncertainty is stripped ("pneumonia" when the
  anchor was "likely pneumonia") — this is a high-stakes failure
  mode that inflates apparent diagnostic certainty.

REAS.planned anchors:
  CORRECT if both the planned action AND its conditional/temporal
  context are preserved. "Will obtain MRI tomorrow" requires both
  MRI and the timing. "Consider ECMO if no improvement" requires
  both ECMO and the conditional. PARTIAL if action is recovered
  without context.

## OUTPUT FORMAT

For each item, return:

{
  "anchor_id": "A1",
  "judgment": "CORRECT" | "PARTIAL" | "INCORRECT",
  "rationale": "Brief explanation of the judgment, referencing the
                specific scoring rule applied",
  "failure_mode": null | "class_collapse" | "instance_swap" |
                  "status_loss" | "negation_loss" | "qualifier_loss" |
                  "uncertainty_loss" | "magnitude_error" |
                  "unit_missing" | "fabrication" | "refusal" | "other",
  "preserved_class": true | false | "n/a"  (For CAT.instance anchors
                  only: did the answer at least preserve the class
                  even if it lost the instance? This is essential for
                  the class-vs-instance analysis.)
}

The failure_mode taxonomy is critical for the experiment. Apply the
most specific applicable failure mode:

  class_collapse: model gave a class-level answer when an instance was
                  required (e.g., "antibiotics" for "vancomycin")
  instance_swap:  model named a different instance within the same
                  class (e.g., "rivaroxaban" for "apixaban") — this
                  is a fabrication risk and the most dangerous failure
  status_loss:    model preserved an entity but lost its temporal
                  status qualifier (e.g., "on apixaban" for "recently
                  discontinued apixaban")
  negation_loss:  model lost the negation, reporting the affirmative
                  form of a denied finding
  qualifier_loss: model preserved the base entity but lost the
                  qualifier that changes clinical management
  uncertainty_loss: model stripped uncertainty markers, converting
                  hedged reasoning to apparent certainty
  magnitude_error: numeric value is wrong (off by more than acceptable
                  tolerance)
  unit_missing:   numeric value correct but unit absent (clinically
                  problematic; commonly seen under compression)
  fabrication:    model produced an answer that does not appear in
                  the case at all (most concerning for clinical
                  safety)
  refusal:        model declined to answer or said the information
                  was not available
  other:          failure that doesn't fit the above (describe in
                  rationale)

## SUMMARY STATISTICS

After scoring all items, also produce a summary block:

{
  "n_total": <integer>,
  "n_correct": <integer>,
  "n_partial": <integer>,
  "n_incorrect": <integer>,
  "by_category": {
    "CAT.class": { "correct": x, "partial": x, "incorrect": x },
    "CAT.instance": { ... },
    ...
  },
  "by_failure_mode": {
    "class_collapse": <integer>,
    "instance_swap": <integer>,
    ...
  },
  "class_vs_instance_analysis": {
    "n_paired_instances": <integer>,
    "instance_correct": <integer>,
    "instance_lost_class_preserved": <integer>,
    "both_lost": <integer>,
    "class_lost_instance_correct": <integer>
  }
}

The class_vs_instance_analysis is the headline result for testing
Vishnu's hypothesis. The expected pattern is:
  - instance_lost_class_preserved > 0 (the categorical-vs-exact
    degradation pattern exists)
  - instance_lost_class_preserved > both_lost (the model fails by
    collapsing to class, not by total information loss)
  - class_lost_instance_correct ≈ 0 (the model rarely recovers an
    instance while losing its class — would be an odd failure mode)

If those patterns hold, Vishnu's coding-agent finding has replicated
in clinical text and the project has a publishable result.

## GENERAL SCORING PRINCIPLES

  1. Read the model's full answer before judging. Models sometimes
     bury the correct answer in a longer response or qualify it in
     ways that affect judgment.

  2. When the model produces multiple possible answers ("could be X
     or Y"), judge based on whether the correct answer is included
     AND treated as a leading candidate. A correct answer buried as
     the third option among five is PARTIAL at best.

  3. Be strict on negation, uncertainty markers, and status
     qualifiers. These are the failure modes where leniency causes
     the most clinical harm and where reviewers will scrutinize the
     scoring most carefully.

  4. Be lenient on phrasing where clinical synonymy is well-
     established (BID ≡ q12h ≡ twice daily). Be strict where
     terminological precision matters clinically (MSSA vs MRSA,
     apixaban vs rivaroxaban).

  5. When in doubt between CORRECT and PARTIAL, choose PARTIAL.
     When in doubt between PARTIAL and INCORRECT, choose
     INCORRECT. This conservative bias prevents the well-known
     LLM-judge tendency toward generosity.

  6. If the model refuses to answer or says the information is not
     available in the context, mark INCORRECT with failure_mode
     "refusal" — this is a meaningful experimental signal,
     particularly informative for distinguishing "compression
     destroyed the information" from "compression confused the
     model into hallucination."

Begin scoring. Process all items, then produce the summary block.