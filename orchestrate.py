"""
Clinical Context Compression Pressure Test
==========================================

Tests whether anchor facts in clinical case reports are differentially
preserved across compression conditions (i.e., longer contexts produced
by padding with realistic clinical filler).

Pipeline:
    case JSON  -->  padded contexts at multiple lengths  -->  answering model
                                                                   |
                                                                   v
                                              judge model  <--  raw answers
                                                   |
                                                   v
                                       per-anchor judgments + summary

Inputs:
    A directory of case JSON files produced by the extraction prompt.
    Each file must contain: case_metadata, anchors, questions, filler_blocks.

Outputs (in --output-dir):
    answers/<case>_<length>.json     raw model answers, cached
    judgments/<case>_<length>.json   judge model judgments, cached
    summary.json                     aggregate stats incl. class-vs-instance
    summary.csv                      flat per-anchor results for analysis

Usage:
    export ANTHROPIC_API_KEY=...
    python compression_experiment.py \
        --cases-dir ./cases \
        --output-dir ./results \
        --context-lengths 8000 16000 32000 64000 128000 \
        --placement middle \
        --answering-model claude-opus-4-7 \
        --judge-model claude-sonnet-4-6

Dependencies:
    pip install anthropic tiktoken tenacity

Notes:
    - Answer and judge models should differ (avoid same-model judging bias).
    - Caching is keyed on (case_id, context_length, anchor_id); deleting
      a cache file forces re-running just that cell.
    - Token counting uses tiktoken's cl100k_base as an approximation;
      Anthropic tokenization differs slightly but the deltas don't matter
      for padding to target lengths within ~5%.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tiktoken
from anthropic import Anthropic, APIError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Configuration & logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("compression_exp")

# tiktoken is a close-enough approximation across providers for padding purposes
TOKENIZER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(TOKENIZER.encode(text))


# ---------------------------------------------------------------------------
# Case data structures
# ---------------------------------------------------------------------------

@dataclass
class Anchor:
    id: str
    category: str
    subtype: str
    text: str
    location: str
    distinctiveness: str
    granularity: str | None
    paired_anchors: list[str]
    clinical_actionability: str
    # For CAT.instance anchors: True if case_text contains explicit class-level
    # terminology for this instance (clean test of Vishnu's hypothesis), False
    # if absent, None if not specified or not applicable.
    class_node_present: bool | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Anchor":
        return cls(
            id=d["id"],
            category=d["category"],
            subtype=d.get("subtype", d["category"]),
            text=d["text"],
            location=d.get("location", ""),
            distinctiveness=d.get("distinctiveness", "medium"),
            granularity=d.get("granularity"),
            paired_anchors=d.get("paired_anchors", []),
            clinical_actionability=d.get("clinical_actionability", "medium"),
            class_node_present=_parse_class_node_present(d.get("class_node_present")),
        )


def _parse_class_node_present(value: Any) -> bool | None:
    """Coerce class_node_present to True / False / None.

    Accepts boolean, string ('true'/'false'/'n/a'), or missing values.
    Returns None for 'n/a', missing, or unrecognizable values so the
    aggregation can skip these anchors when stratifying.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "true":
            return True
        if v == "false":
            return False
    return None  # treat 'n/a', missing, or unrecognized as None


@dataclass
class Question:
    anchor_id: str
    question: str
    expected_answer: str
    scoring: str
    granularity_tested: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(
            anchor_id=d["anchor_id"],
            question=d["question"],
            expected_answer=d["expected_answer"],
            scoring=d.get("scoring", "semantic_match"),
            granularity_tested=d.get("granularity_tested"),
        )


@dataclass
class Case:
    case_id: str
    title: str
    specialty: str
    original_text: str  # the case report body; see loader for assembly
    anchors: list[Anchor]
    questions: list[Question]
    filler_blocks: list[str]

    def anchor_by_id(self, anchor_id: str) -> Anchor | None:
        return next((a for a in self.anchors if a.id == anchor_id), None)


def load_case(path: Path) -> Case:
    """Load a case JSON file produced by the extraction prompt.

    The extraction prompt produces anchor/question/filler outputs but does
    not necessarily include the full case body. If a 'case_text' field is
    present we use it; otherwise we expect a companion .txt file next to
    the JSON named <case_id>.txt.
    """
    data = json.loads(path.read_text())
    case_id = path.stem

    case_text = data.get("case_text")
    if case_text is None:
        txt_path = path.with_suffix(".txt")
        if not txt_path.exists():
            raise FileNotFoundError(
                f"Case body missing: provide 'case_text' in {path.name} "
                f"or supply {txt_path.name}"
            )
        case_text = txt_path.read_text()

    metadata = data.get("case_metadata", {})
    return Case(
        case_id=case_id,
        title=metadata.get("title", case_id),
        specialty=metadata.get("specialty", "unknown"),
        original_text=case_text,
        anchors=[Anchor.from_dict(a) for a in data["anchors"]],
        questions=[Question.from_dict(q) for q in data["questions"]],
        filler_blocks=[fb["content"] for fb in data["filler_blocks"]],
    )


# ---------------------------------------------------------------------------
# Context padding
# ---------------------------------------------------------------------------

def build_padded_context(
    case: Case,
    target_tokens: int,
    placement: str = "middle",
    seed: int = 0,
) -> str:
    """Build a context of approximately target_tokens by padding the case
    text with filler blocks. The case content is placed according to
    placement ('beginning', 'middle', 'end').

    Filler blocks are recycled (and individually truncated as needed) to
    hit the target. We do NOT split the case text — it's always intact.
    """
    rng = random.Random(seed)

    case_tokens = count_tokens(case.original_text)
    if case_tokens >= target_tokens:
        log.warning(
            "Case %s body is %d tokens, already >= target %d. Returning unpadded.",
            case.case_id, case_tokens, target_tokens,
        )
        return case.original_text

    needed_filler_tokens = target_tokens - case_tokens

    # Stitch filler blocks together, recycling as needed
    filler_parts: list[str] = []
    accumulated = 0
    block_pool = list(case.filler_blocks)
    rng.shuffle(block_pool)
    i = 0
    while accumulated < needed_filler_tokens:
        block = block_pool[i % len(block_pool)]
        block_tokens = count_tokens(block)
        if accumulated + block_tokens <= needed_filler_tokens:
            filler_parts.append(block)
            accumulated += block_tokens
        else:
            # truncate this final block to exactly fit
            remaining = needed_filler_tokens - accumulated
            truncated = TOKENIZER.decode(TOKENIZER.encode(block)[:remaining])
            filler_parts.append(truncated)
            accumulated = needed_filler_tokens
        i += 1
        if i > 10000:  # safety
            break

    # Separate adjacent filler blocks with a synthetic note header for realism
    separators = [
        "\n\n--- ADDITIONAL CLINICAL DOCUMENTATION ---\n\n",
        "\n\n--- NURSING / ANCILLARY NOTE ---\n\n",
        "\n\n--- CARE COORDINATION ENTRY ---\n\n",
    ]
    joined_filler = ""
    for idx, fp in enumerate(filler_parts):
        joined_filler += separators[idx % len(separators)] + fp

    if placement == "beginning":
        return case.original_text + joined_filler
    elif placement == "end":
        return joined_filler + "\n\n--- INDEX CASE ---\n\n" + case.original_text
    elif placement == "middle":
        # split filler roughly in half by tokens
        midpoint = needed_filler_tokens // 2
        tokens = TOKENIZER.encode(joined_filler)
        first_half = TOKENIZER.decode(tokens[:midpoint])
        second_half = TOKENIZER.decode(tokens[midpoint:])
        return (
            first_half
            + "\n\n--- INDEX CASE ---\n\n"
            + case.original_text
            + "\n\n--- ADDITIONAL DOCUMENTATION CONTINUED ---\n\n"
            + second_half
        )
    else:
        raise ValueError(f"Unknown placement: {placement}")


# ---------------------------------------------------------------------------
# Answering model client
# ---------------------------------------------------------------------------

ANSWER_SYSTEM_PROMPT = """You are a clinical assistant reviewing a patient \
chart. The chart contains the patient's index case documentation along \
with additional clinical notes from the same admission. Answer questions \
about the patient based on the chart content. Be specific and concise. \
If the answer is not present in the chart, say "not documented" — do \
not guess or infer beyond what is written."""


@dataclass
class AnswerCall:
    case_id: str
    context_length: int
    anchor_id: str
    question: str
    answer: str
    input_tokens: int
    output_tokens: int


class AnswerClient:
    def __init__(self, model: str, max_tokens: int = 256):
        self.client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    @retry(
        retry=retry_if_exception_type((APIError, APIStatusError)),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def answer(self, context: str, question: str) -> tuple[str, int, int]:
        user_msg = (
            f"CHART:\n\n{context}\n\n---\n\n"
            f"QUESTION: {question}\n\n"
            f"Provide a concise, specific answer based only on the chart above."
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=ANSWER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return (
            text.strip(),
            resp.usage.input_tokens,
            resp.usage.output_tokens,
        )


# ---------------------------------------------------------------------------
# Judge client
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You are a clinical NLP research assistant scoring \
language model outputs on a clinical anchor fact recovery task. You will \
judge whether a model's answer correctly recovered a specific anchor fact \
from a clinical case. You must follow the scoring rules calibrated to the \
anchor's category and subtype. Be conservative: when in doubt between \
CORRECT and PARTIAL, choose PARTIAL; when in doubt between PARTIAL and \
INCORRECT, choose INCORRECT.

Return ONLY a JSON object, no other text."""


JUDGE_USER_TEMPLATE = """Score the following item.

ANCHOR FACT (verbatim from case):
"{anchor_text}"

ANCHOR CATEGORY: {category}
ANCHOR SUBTYPE: {subtype}
GRANULARITY: {granularity}

QUESTION POSED TO MODEL:
{question}

EXPECTED ANSWER:
{expected_answer}

MODEL'S ACTUAL ANSWER:
{model_answer}

SCORING RULES FOR THIS SUBTYPE:
{rules}

Return ONLY this JSON object:

{{
  "judgment": "CORRECT" | "PARTIAL" | "INCORRECT",
  "rationale": "<one sentence>",
  "failure_mode": null | "class_collapse" | "instance_swap" | "status_loss" | "negation_loss" | "qualifier_loss" | "uncertainty_loss" | "magnitude_error" | "unit_missing" | "fabrication" | "refusal" | "other",
  "preserved_class": true | false | "n/a"
}}

Failure mode taxonomy:
- class_collapse: model gave class-level answer when instance required (e.g., "antibiotics" for "vancomycin")
- instance_swap: model named a different instance within the same class (most dangerous)
- status_loss: entity preserved but temporal status qualifier lost
- negation_loss: lost negation, reporting affirmative form
- qualifier_loss: base entity preserved but qualifier lost
- uncertainty_loss: stripped uncertainty markers
- magnitude_error: numeric value wrong beyond tolerance
- unit_missing: number correct but unit absent
- fabrication: answer not in case at all
- refusal: model declined / said not available
- other: doesn't fit above

For CAT.instance anchors, ALWAYS set preserved_class to true or false.
For other categories, set preserved_class to "n/a".
"""


SCORING_RULES: dict[str, str] = {
    "CAT.class": (
        "CORRECT if answer references the same class or category as the anchor, "
        "including synonymous terminology. More specific (instance-level) answers "
        "are also CORRECT."
    ),
    "CAT.instance": (
        "CORRECT if answer names the specific entity (brand-generic synonyms OK). "
        "INCORRECT if only the class is named (class_collapse). "
        "INCORRECT if a different instance within the same class is named (instance_swap)."
    ),
    "CAT.qualifier": (
        "CORRECT only if BOTH base entity AND qualifier are recovered. "
        "PARTIAL if base entity preserved without qualifier."
    ),
    "CAT.alert": (
        "CORRECT only if alert is recovered with sufficient specificity to "
        "preserve clinical action (e.g., 'penicillin allergy with anaphylaxis' "
        "requires both agent and severity)."
    ),
    "CAT.negated": (
        "CORRECT if negation preserved. INCORRECT if the entity is reported "
        "without negation (negation_loss) or with opposite affirmation."
    ),
    "TEMP.date": (
        "CORRECT if date matches with acceptable format variation. INCORRECT "
        "if any date component differs."
    ),
    "TEMP.duration": (
        "CORRECT if numeric duration matches with acceptable unit conversion. "
        "INCORRECT if the numeric duration differs even slightly."
    ),
    "TEMP.since": (
        "CORRECT if both elapsed time and referenced event are preserved."
    ),
    "TEMP.status": (
        "CORRECT ONLY if the status change is explicitly preserved. "
        "INCORRECT if entity is preserved without the status change (status_loss). "
        "This is a high-stakes failure mode."
    ),
    "TEMP.sequence": (
        "CORRECT if relative ordering of events is preserved, even without "
        "exact dates. INCORRECT if order is reversed or a key transition is dropped."
    ),
    "TEMP.trajectory": (
        "CORRECT if direction of change is preserved. PARTIAL if direction "
        "correct but specific values are wrong."
    ),
    "QUANT.dose": (
        "CORRECT only if numeric value AND unit both preserved exactly. "
        "Weight-based dosing requires the rate and unit (e.g., '20 mg/kg' "
        "must include '/kg')."
    ),
    "QUANT.freq": (
        "Permissive on clinical synonyms (BID ≡ q12h ≡ twice daily). "
        "INCORRECT only if actual frequency differs (q8h vs q12h)."
    ),
    "QUANT.lab": (
        "CORRECT if numeric value and unit both preserved. PARTIAL if number "
        "correct but units absent."
    ),
    "QUANT.vital": (
        "Same as QUANT.lab. BP requires both systolic and diastolic. "
        "Clinical interpretation (e.g., 'hypotensive') is INCORRECT for a "
        "specific number anchor."
    ),
    "QUANT.anthro": "Same as QUANT.lab.",
    "REAS.considered": (
        "CORRECT only if BOTH consideration of the diagnosis AND the reason "
        "it was ruled out are preserved. PARTIAL if only consideration preserved."
    ),
    "REAS.conditional": (
        "CORRECT only if BOTH condition AND consequent are preserved. "
        "INCORRECT if conditional is collapsed to unconditional statement."
    ),
    "REAS.causal": (
        "CORRECT if causal link between entities is preserved (FOR, DUE TO, "
        "BECAUSE). PARTIAL if entities preserved without the link."
    ),
    "REAS.uncertain": (
        "CORRECT if uncertainty marker preserved. INCORRECT if uncertainty "
        "is stripped (uncertainty_loss)."
    ),
    "REAS.planned": (
        "CORRECT if both planned action AND its conditional/temporal context "
        "are preserved. PARTIAL if action recovered without context."
    ),
}


@dataclass
class Judgment:
    case_id: str
    context_length: int
    anchor_id: str
    judgment: str
    rationale: str
    failure_mode: str | None
    preserved_class: bool | str  # bool or "n/a"


class JudgeClient:
    def __init__(self, model: str, max_tokens: int = 400):
        self.client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    @retry(
        retry=retry_if_exception_type((APIError, APIStatusError)),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def judge(self, anchor: Anchor, question: Question, model_answer: str) -> dict:
        rules = SCORING_RULES.get(
            anchor.subtype, SCORING_RULES.get(anchor.category, "Use general clinical judgment.")
        )
        user_msg = JUDGE_USER_TEMPLATE.format(
            anchor_text=anchor.text,
            category=anchor.category,
            subtype=anchor.subtype,
            granularity=anchor.granularity or "n/a",
            question=question.question,
            expected_answer=question.expected_answer,
            model_answer=model_answer,
            rules=rules,
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

        # Robust JSON extraction: strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Failed to parse judge JSON; treating as INCORRECT/other. Raw: %s", text[:200])
            return {
                "judgment": "INCORRECT",
                "rationale": f"Judge output unparseable: {text[:120]}",
                "failure_mode": "other",
                "preserved_class": "n/a",
            }


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def cache_path(base_dir: Path, kind: str, case_id: str, length: int) -> Path:
    sub = base_dir / kind
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{case_id}_{length}.json"


def load_cache(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            log.warning("Corrupt cache at %s; ignoring.", path)
    return None


def save_cache(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Per-case run
# ---------------------------------------------------------------------------

def run_case_at_length(
    case: Case,
    target_length: int,
    placement: str,
    answer_client: AnswerClient,
    judge_client: JudgeClient,
    output_dir: Path,
) -> list[Judgment]:
    # Answer phase (cached)
    ans_path = cache_path(output_dir, "answers", case.case_id, target_length)
    cached_ans = load_cache(ans_path)
    if cached_ans:
        log.info("Cached answers found for %s @ %d", case.case_id, target_length)
        answer_records = cached_ans["answers"]
    else:
        context = build_padded_context(case, target_length, placement=placement)
        actual_tokens = count_tokens(context)
        log.info(
            "Built context for %s: target=%d, actual=%d, placement=%s",
            case.case_id, target_length, actual_tokens, placement,
        )
        answer_records = []
        for q in case.questions:
            log.info("  ANSWER  %s @ %d: anchor=%s", case.case_id, target_length, q.anchor_id)
            try:
                ans, in_tok, out_tok = answer_client.answer(context, q.question)
            except Exception as e:  # noqa: BLE001
                log.error("Answer call failed for %s/%s: %s", case.case_id, q.anchor_id, e)
                ans, in_tok, out_tok = f"[ERROR: {e}]", 0, 0
            answer_records.append({
                "anchor_id": q.anchor_id,
                "question": q.question,
                "expected_answer": q.expected_answer,
                "model_answer": ans,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            })
            time.sleep(0.5)  # gentle pacing
        save_cache(ans_path, {
            "case_id": case.case_id,
            "context_length_target": target_length,
            "context_length_actual": actual_tokens,
            "placement": placement,
            "answer_model": answer_client.model,
            "answers": answer_records,
        })

    # Judge phase (cached)
    judge_path = cache_path(output_dir, "judgments", case.case_id, target_length)
    cached_judge = load_cache(judge_path)
    if cached_judge:
        log.info("Cached judgments found for %s @ %d", case.case_id, target_length)
        return [Judgment(**j) for j in cached_judge["judgments"]]

    judgments: list[Judgment] = []
    for rec in answer_records:
        anchor = case.anchor_by_id(rec["anchor_id"])
        question = next(q for q in case.questions if q.anchor_id == rec["anchor_id"])
        if anchor is None:
            continue
        log.info("  JUDGE   %s @ %d: anchor=%s", case.case_id, target_length, anchor.id)
        try:
            j = judge_client.judge(anchor, question, rec["model_answer"])
        except Exception as e:  # noqa: BLE001
            log.error("Judge call failed for %s/%s: %s", case.case_id, anchor.id, e)
            j = {
                "judgment": "INCORRECT",
                "rationale": f"Judge error: {e}",
                "failure_mode": "other",
                "preserved_class": "n/a",
            }
        judgments.append(Judgment(
            case_id=case.case_id,
            context_length=target_length,
            anchor_id=anchor.id,
            judgment=j["judgment"],
            rationale=j["rationale"],
            failure_mode=j.get("failure_mode"),
            preserved_class=j.get("preserved_class", "n/a"),
        ))
        time.sleep(0.3)

    save_cache(judge_path, {
        "case_id": case.case_id,
        "context_length": target_length,
        "judge_model": judge_client.model,
        "judgments": [j.__dict__ for j in judgments],
    })
    return judgments


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(all_judgments: list[Judgment], cases: dict[str, Case]) -> dict:
    """Produce the headline summary, including the class-vs-instance analysis."""

    summary: dict[str, Any] = {
        "n_total": len(all_judgments),
        "by_length": {},
        "by_subtype": {},
        "by_failure_mode": {},
        "class_vs_instance": {},
    }

    # by length
    for j in all_judgments:
        L = str(j.context_length)
        bucket = summary["by_length"].setdefault(
            L, {"CORRECT": 0, "PARTIAL": 0, "INCORRECT": 0}
        )
        bucket[j.judgment] = bucket.get(j.judgment, 0) + 1

    # by subtype (anchor lookup needed)
    for j in all_judgments:
        case = cases[j.case_id]
        anchor = case.anchor_by_id(j.anchor_id)
        if anchor is None:
            continue
        bucket = summary["by_subtype"].setdefault(
            anchor.subtype, {"CORRECT": 0, "PARTIAL": 0, "INCORRECT": 0}
        )
        bucket[j.judgment] = bucket.get(j.judgment, 0) + 1

    # by failure mode
    for j in all_judgments:
        if j.failure_mode:
            summary["by_failure_mode"][j.failure_mode] = (
                summary["by_failure_mode"].get(j.failure_mode, 0) + 1
            )

    # class-vs-instance analysis (the headline experimental result)
    # Stratified by whether case_text contained an explicit class node for
    # each instance. The 'with_class_node' subset is the cleanest test of
    # Vishnu's hypothesis — there the class was available in source for the
    # model to recover. Compare against 'all_instances' to see whether the
    # effect is concentrated in cases with a true class node in source.
    summary["class_vs_instance"] = {
        "all_instances": {},
        "with_class_node": {},
        "without_class_node": {},
    }
    for j in all_judgments:
        case = cases[j.case_id]
        anchor = case.anchor_by_id(j.anchor_id)
        if anchor is None or anchor.subtype != "CAT.instance":
            continue
        L = str(j.context_length)
        instance_recovered = j.judgment == "CORRECT"
        class_preserved = j.preserved_class is True or j.preserved_class == "true"

        # Decide which strata this anchor belongs to
        strata = ["all_instances"]
        if anchor.class_node_present is True:
            strata.append("with_class_node")
        elif anchor.class_node_present is False:
            strata.append("without_class_node")
        # If class_node_present is None ("n/a" or missing), the anchor counts
        # only toward 'all_instances'.

        for stratum in strata:
            bucket = summary["class_vs_instance"][stratum].setdefault(L, {
                "n_paired_instances": 0,
                "instance_correct": 0,
                "instance_lost_class_preserved": 0,
                "both_lost": 0,
                "class_lost_instance_correct": 0,
            })
            bucket["n_paired_instances"] += 1
            if instance_recovered and class_preserved:
                bucket["instance_correct"] += 1
            elif instance_recovered and not class_preserved:
                bucket["class_lost_instance_correct"] += 1
            elif not instance_recovered and class_preserved:
                bucket["instance_lost_class_preserved"] += 1
            else:
                bucket["both_lost"] += 1

    return summary


def write_csv(all_judgments: list[Judgment], cases: dict[str, Case], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "case_id", "context_length", "anchor_id", "category", "subtype",
            "granularity", "distinctiveness", "clinical_actionability",
            "class_node_present",
            "judgment", "failure_mode", "preserved_class", "rationale",
        ])
        for j in all_judgments:
            case = cases[j.case_id]
            anchor = case.anchor_by_id(j.anchor_id)
            if anchor is None:
                continue
            # Render class_node_present as "true"/"false"/"n/a" for CSV
            if anchor.class_node_present is True:
                cnp = "true"
            elif anchor.class_node_present is False:
                cnp = "false"
            else:
                cnp = "n/a"
            w.writerow([
                j.case_id, j.context_length, j.anchor_id,
                anchor.category, anchor.subtype, anchor.granularity or "",
                anchor.distinctiveness, anchor.clinical_actionability,
                cnp,
                j.judgment, j.failure_mode or "", j.preserved_class,
                j.rationale,
            ])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Clinical context compression pressure test orchestrator."
    )
    p.add_argument("--cases-dir", type=Path, required=True,
                   help="Directory of case JSON files (and optional .txt bodies).")
    p.add_argument("--output-dir", type=Path, required=True,
                   help="Directory for cached answers, judgments, and summary.")
    p.add_argument("--context-lengths", type=int, nargs="+",
                   default=[8000, 16000, 32000, 64000, 128000])
    p.add_argument("--placement", choices=["beginning", "middle", "end"],
                   default="middle")
    p.add_argument("--answering-model", default="claude-opus-4-7")
    p.add_argument("--judge-model", default="claude-sonnet-4-6")
    p.add_argument("--case-glob", default="*.json",
                   help="Glob pattern for case files (default: *.json).")
    args = p.parse_args()

    if not args.cases_dir.exists():
        log.error("Cases directory does not exist: %s", args.cases_dir)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.answering_model == args.judge_model:
        log.warning(
            "Answering and judge model are identical (%s). "
            "Use different models to avoid same-model leniency bias.",
            args.answering_model,
        )

    case_paths = sorted(args.cases_dir.glob(args.case_glob))
    if not case_paths:
        log.error("No case files matched %s in %s", args.case_glob, args.cases_dir)
        return 1
    cases: dict[str, Case] = {}
    for cp in case_paths:
        try:
            c = load_case(cp)
            cases[c.case_id] = c
            log.info("Loaded case %s (%d anchors, %d questions, %d filler blocks)",
                     c.case_id, len(c.anchors), len(c.questions), len(c.filler_blocks))
        except Exception as e:  # noqa: BLE001
            log.error("Failed to load %s: %s", cp, e)

    if not cases:
        log.error("No cases loaded.")
        return 1

    answer_client = AnswerClient(model=args.answering_model)
    judge_client = JudgeClient(model=args.judge_model)

    all_judgments: list[Judgment] = []
    for case in cases.values():
        for L in args.context_lengths:
            try:
                js = run_case_at_length(
                    case=case,
                    target_length=L,
                    placement=args.placement,
                    answer_client=answer_client,
                    judge_client=judge_client,
                    output_dir=args.output_dir,
                )
                all_judgments.extend(js)
            except Exception as e:  # noqa: BLE001
                log.exception("Failed run for %s @ %d: %s", case.case_id, L, e)

    summary = aggregate(all_judgments, cases)
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    csv_path = args.output_dir / "summary.csv"
    write_csv(all_judgments, cases, csv_path)

    log.info("Done. Summary written to %s and %s", summary_path, csv_path)

    # Print headline class-vs-instance result, stratified
    cvi = summary.get("class_vs_instance", {})
    stratum_labels = {
        "all_instances": "ALL CAT.instance anchors (omnibus result)",
        "with_class_node": "Subset where class node was PRESENT in case_text "
                           "(cleanest test of Vishnu's hypothesis)",
        "without_class_node": "Subset where class node was ABSENT in case_text "
                              "(instance-only failures, less interpretable)",
    }
    for stratum_key, label in stratum_labels.items():
        stratum = cvi.get(stratum_key, {})
        if not stratum:
            log.info("(no data in stratum: %s)", stratum_key)
            continue
        log.info("=" * 70)
        log.info("CLASS-VS-INSTANCE — %s", label)
        log.info("=" * 70)
        for L in sorted(stratum.keys(), key=int):
            b = stratum[L]
            n = b["n_paired_instances"] or 1
            log.info(
                "L=%6s  n=%3d  inst_correct=%3d (%.0f%%)  "
                "lost_but_class_kept=%3d (%.0f%%)  both_lost=%3d (%.0f%%)",
                L, b["n_paired_instances"],
                b["instance_correct"], 100 * b["instance_correct"] / n,
                b["instance_lost_class_preserved"],
                100 * b["instance_lost_class_preserved"] / n,
                b["both_lost"], 100 * b["both_lost"] / n,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())