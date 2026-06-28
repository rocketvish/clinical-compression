"""Per-token surprisal profiling for clinical case text.

Runs a single forward pass of a causal LM over a clinical case, computes
per-token surprisal (``-log2 P(token | context)``), and labels each token as a
clinical entity, a numeric/unit token, or boilerplate using the entity and
value lists from the case's structured fact file. The point is to test a
hypothesis: *are the clinically important tokens naturally high-surprisal?* If
so, perplexity-weighted compression would protect them for free.

This is exploratory analysis, not pipeline code. In particular, token-to-entity
matching is deliberately fuzzy: sub-word tokens are matched by substring against
the fact file's entity vocabulary rather than via a full character alignment.
That is good enough to see category-level separation and is documented here so
the numbers are not over-interpreted.

Usage::

    python -m src.analysis.perplexity_profile \
        --input pubmed/bleeding-triple-therapy-case.txt \
        --facts pubmed/bleeding-facts-final.json \
        --model Qwen/Qwen3-8B \
        --output results/bleeding-perplexity.png

Requires the optional GPU stack:  pip install -e .[analysis]
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
from pathlib import Path

# --- Project palette (do not change without updating the rest of the repo) ---
CATEGORY_COLORS = {
    "clinical_entity": "#1F7A8A",     # teal
    "numeric": "#C99A4F",             # gold
    "medical_vocabulary": "#5A5249",  # dark text brown
    "true_boilerplate": "#D6C49E",    # sand
}
CATEGORY_ORDER = (
    "clinical_entity", "numeric", "medical_vocabulary", "true_boilerplate",
)

DEFAULT_MODEL = "Qwen/Qwen3-8B"

# Tokens that are pure measurement units count as `numeric` even though they are
# alphabetic. Lower-cased, punctuation-stripped comparison.
UNIT_TOKENS = {
    "mg", "mcg", "ug", "g", "kg", "ml", "l", "dl", "cc",
    "mmol", "mol", "meq", "meq/l", "mmol/l", "mg/dl", "mg/l", "ng/ml",
    "iu", "u", "units", "unit", "%", "percent",
    "mmhg", "bpm", "min", "hr", "hrs", "hour", "hours", "day", "days",
    "daily", "bid", "tid", "qid", "qd", "prn",
}

# A token is "numeric" if, once sub-word/punctuation noise is stripped, it is a
# bare number (incl. decimals, ranges, and trailing units like "15mg").
_NUMERIC_RE = re.compile(r"^\d[\d.,/\-]*[a-z%]*$")

# A token counts as `true_boilerplate` if its general-English corpus frequency
# is at or above this threshold; otherwise (if not a clinical entity or numeric)
# it is `medical_vocabulary`. 1e-4 is roughly the top ~5000 English words, which
# captures function words and everyday vocabulary while leaving domain terms
# ("retropharyngeal", "chemoprophylaxis") below the line. Data-driven via
# wordfreq, so e.g. "patient" is classified by its actual corpus frequency
# rather than by manual curation.
BOILERPLATE_FREQ_THRESHOLD = 1e-4


def is_common_word(word: str) -> bool:
    # Imported lazily so --help and the non-GPU code paths work without the
    # optional analysis stack installed.
    from wordfreq import word_frequency

    return word_frequency(word.lower().strip(), "en") >= BOILERPLATE_FREQ_THRESHOLD


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Profile per-token surprisal of a clinical case and "
        "compare clinical entities against boilerplate.",
    )
    p.add_argument("--input", required=True, type=Path,
                   help="Clinical case text file (.txt).")
    p.add_argument("--facts", required=True, type=Path,
                   help="Structured fact file (.json) for the same case.")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"HF model id (default: {DEFAULT_MODEL}).")
    p.add_argument("--output", required=True, type=Path,
                   help="Output figure path (.png). The CSV and the "
                   "distribution figure are written alongside it.")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Entity vocabulary
# ---------------------------------------------------------------------------

def _word_pieces(text: str) -> set[str]:
    """Lower-cased alphabetic word pieces of length >= 3 from a string."""
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 3}


def build_entity_vocab(facts_path: Path) -> set[str]:
    """Collect the clinical-entity word vocabulary from a fact file.

    Pulls words from every fact's ``entities`` and ``content`` (the value/number
    side is handled by the numeric classifier instead). Returns a set of
    lower-cased word pieces used for fuzzy sub-word matching.
    """
    # Imported here so that argument parsing / --help works without the schema
    # package being importable in odd environments.
    from src.schema.fact_schema import FactFile

    fact_file = FactFile.from_json(facts_path)
    vocab: set[str] = set()
    for fact in fact_file.facts:
        for entity in fact.entities:
            vocab |= _word_pieces(entity)
    # Drop the generic "patient" anchor entity: it is boilerplate, not a
    # clinically distinguishing term, and would mislabel every mention.
    vocab.discard("patient")
    return vocab


# ---------------------------------------------------------------------------
# Token categorization
# ---------------------------------------------------------------------------

def _clean_token(token_text: str) -> str:
    """Decoded-token text -> lower-cased, whitespace/punctuation-trimmed form."""
    return token_text.strip().strip(".,;:()[]{}\"'").lower()


def categorize_token(token_text: str, entity_vocab: set[str]) -> str:
    """Label a token: clinical_entity, numeric, true_boilerplate, or
    medical_vocabulary.

    Precedence: clinical_entity > numeric > true_boilerplate >
    medical_vocabulary. A token matching the fact-file entity vocabulary is
    clinical; a bare number/unit is numeric; a common general-English word is
    true_boilerplate (boilerplate even in a medical context); anything left
    over is medical_vocabulary (domain words like "retropharyngeal" that are
    neither entities nor common words).
    """
    clean = _clean_token(token_text)
    if not clean:
        return "true_boilerplate"
    # clinical_entity: exact word match (len >= 3), or a longer sub-word
    # fragment of an entity word (e.g. "rivar" / "oxaban" -> "rivaroxaban").
    # The length-4 floor on the substring path keeps short function words from
    # matching inside entities (e.g. "the" inside "therapy").
    if len(clean) >= 3 and clean in entity_vocab:
        return "clinical_entity"
    if len(clean) >= 4 and any(clean in word for word in entity_vocab):
        return "clinical_entity"
    if clean in UNIT_TOKENS or _NUMERIC_RE.match(clean):
        return "numeric"
    if is_common_word(clean):
        return "true_boilerplate"
    return "medical_vocabulary"


# ---------------------------------------------------------------------------
# Model + forward pass
# ---------------------------------------------------------------------------

def load_model(model_id: str):
    """Load tokenizer + model at 8-bit quantization on the GPU."""
    try:
        import torch  # noqa: F401
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )
    except ImportError as exc:  # pragma: no cover - environment guard
        sys.exit(
            f"Missing dependency: {exc.name}. Install the analysis extra with:"
            "\n    pip install -e .[analysis]"
        )

    print(f"Loading {model_id} at 8-bit ...", flush=True)
    quant_config = BitsAndBytesConfig(load_in_8bit=True)
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=quant_config,
            device_map="auto",
        )
    except Exception as exc:  # noqa: BLE001 - convert to friendly message
        _handle_cuda_oom(exc, context="model loading")
        raise
    model.eval()
    return tokenizer, model


def _handle_cuda_oom(exc: Exception, *, context: str) -> None:
    """Print a clear message and exit if `exc` is a CUDA OOM; else return."""
    import torch

    is_oom = isinstance(exc, getattr(torch.cuda, "OutOfMemoryError", ()))
    if not is_oom and isinstance(exc, RuntimeError):
        is_oom = "out of memory" in str(exc).lower()
    if is_oom:
        try:
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(
            f"\nCUDA out of memory during {context}.\n"
            "The model did not fit in VRAM even at 8-bit. Try:\n"
            "  - closing other GPU processes (check `nvidia-smi`)\n"
            "  - using a smaller model via --model "
            "(e.g. Qwen/Qwen2.5-Coder-7B-Instruct)\n"
            "  - shortening the input case.\n"
        )


def compute_surprisal(tokenizer, model, text: str):
    """Return (token_texts, surprisals) aligned per token.

    Surprisal for the token at position ``t`` (t >= 1) is predicted from the
    context before it: ``-log2 P(token_t | token_<t)``. The first token has no
    context, so it is reported with surprisal ``nan`` and excluded from stats.
    """
    import torch

    enc = tokenizer(text, return_tensors="pt")
    input_ids = enc["input_ids"]

    max_len = getattr(tokenizer, "model_max_length", None)
    if max_len and max_len < 1_000_000 and input_ids.shape[1] > max_len:
        print(
            f"Warning: input has {input_ids.shape[1]} tokens, exceeding the "
            f"model context of {max_len}; truncating.",
            flush=True,
        )
        input_ids = input_ids[:, :max_len]

    input_ids = input_ids.to(model.device)
    try:
        with torch.no_grad():
            logits = model(input_ids).logits
    except Exception as exc:  # noqa: BLE001
        _handle_cuda_oom(exc, context="forward pass")
        raise

    # logits[:, t, :] predicts token t+1. log-softmax in nats, converted to
    # bits with a plain float divisor (avoids any CPU/GPU tensor mismatch).
    log2_probs = torch.log_softmax(logits.float(), dim=-1) / math.log(2.0)
    ids = input_ids[0]
    token_texts = [tokenizer.decode([int(i)]) for i in ids]

    surprisals: list[float] = [float("nan")]  # first token: no context
    for t in range(1, ids.shape[0]):
        surprisals.append(float(-log2_probs[0, t - 1, ids[t]]))
    return token_texts, surprisals


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Mean/median/count of surprisal per category (NaN tokens excluded)."""
    stats: dict[str, dict[str, float]] = {}
    for cat in CATEGORY_ORDER:
        vals = [r["surprisal"] for r in rows
                if r["category"] == cat and r["surprisal"] == r["surprisal"]]
        if vals:
            stats[cat] = {
                "n": len(vals),
                "mean": statistics.mean(vals),
                "median": statistics.median(vals),
            }
        else:
            stats[cat] = {"n": 0, "mean": float("nan"), "median": float("nan")}
    return stats


def print_summary(stats: dict[str, dict[str, float]], model_id: str, case: str) -> None:
    print(f"\nSurprisal by category  -  {model_id}  -  {case}")
    print(f"{'category':<20}{'n':>7}{'mean (bits)':>14}{'median (bits)':>16}")
    print("-" * 57)
    for cat in CATEGORY_ORDER:
        s = stats[cat]
        print(f"{cat:<20}{s['n']:>7}{s['mean']:>14.3f}{s['median']:>16.3f}")
    print()


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["position", "token", "surprisal_bits", "category"])
        for r in rows:
            writer.writerow([r["position"], r["token"], r["surprisal"], r["category"]])
    print(f"Wrote per-token CSV: {path}")


def plot_scatter(rows: list[dict], path: Path, model_id: str, case: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 5))
    for cat in CATEGORY_ORDER:
        xs = [r["position"] for r in rows
              if r["category"] == cat and r["surprisal"] == r["surprisal"]]
        ys = [r["surprisal"] for r in rows
              if r["category"] == cat and r["surprisal"] == r["surprisal"]]
        ax.scatter(xs, ys, s=14, c=CATEGORY_COLORS[cat], label=cat,
                   alpha=0.8, edgecolors="none")
    ax.set_xlabel("token position")
    ax.set_ylabel("surprisal (bits)")
    ax.set_title(f"Per-token surprisal — {model_id} — {case}")
    ax.legend(loc="upper right", framealpha=0.9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Wrote scatter figure: {path}")


def plot_distribution(rows: list[dict], path: Path, model_id: str, case: str) -> None:
    """Box plot of surprisal distribution per category, means annotated."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data, labels, colors, means = [], [], [], []
    for cat in CATEGORY_ORDER:
        vals = [r["surprisal"] for r in rows
                if r["category"] == cat and r["surprisal"] == r["surprisal"]]
        if not vals:
            continue
        data.append(vals)
        labels.append(f"{cat}\n(n={len(vals)})")
        colors.append(CATEGORY_COLORS[cat])
        means.append(statistics.mean(vals))

    fig, ax = plt.subplots(figsize=(8, 6))
    bp = ax.boxplot(data, patch_artist=True, showmeans=True, widths=0.6,
                    meanprops=dict(marker="D", markerfacecolor="white",
                                   markeredgecolor="black", markersize=6))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.85)
    for median in bp["medians"]:
        median.set_color("black")

    ax.set_xticklabels(labels)
    ax.set_ylabel("surprisal (bits)")
    ax.set_title(f"Surprisal distribution by category — {model_id} — {case}")

    # Annotate each box with its mean value.
    y_top = ax.get_ylim()[1]
    for i, mean in enumerate(means, start=1):
        ax.annotate(f"mean {mean:.2f}", xy=(i, mean),
                    xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=9, fontweight="bold")
    ax.set_ylim(top=y_top * 1.05)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Wrote distribution figure: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.input.is_file():
        sys.exit(f"Input case not found: {args.input}")
    if not args.facts.is_file():
        sys.exit(f"Fact file not found: {args.facts}")

    case_name = args.input.stem
    text = args.input.read_text(encoding="utf-8")
    entity_vocab = build_entity_vocab(args.facts)
    print(f"Loaded {len(entity_vocab)} entity word pieces from {args.facts.name}.")

    tokenizer, model = load_model(args.model)
    token_texts, surprisals = compute_surprisal(tokenizer, model, text)

    rows: list[dict] = []
    for pos, (tok, surp) in enumerate(zip(token_texts, surprisals)):
        rows.append({
            "position": pos,
            "token": tok,
            "surprisal": surp,
            "category": categorize_token(tok, entity_vocab),
        })

    stats = summarize(rows)
    print_summary(stats, args.model, case_name)

    out_png = args.output
    out_png.parent.mkdir(parents=True, exist_ok=True)
    csv_path = out_png.with_suffix(".csv")
    dist_png = out_png.with_name(f"{out_png.stem}_dist{out_png.suffix}")

    write_csv(rows, csv_path)
    plot_scatter(rows, out_png, args.model, case_name)
    plot_distribution(rows, dist_png, args.model, case_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
