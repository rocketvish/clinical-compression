"""LLM text-compression baseline for clinical case reports.

Sends a clinical case through a local model with a compression prompt that
demands clinically-actionable detail be preserved (drug names, dosages, lab
values, qualified diagnoses, temporal relationships, negations, allergies),
then saves the compressed text plus a small metadata sidecar. This is the
text-level baseline against which embedding/KV compression is compared.

Usage::

    python -m src.analysis.text_compress \
        --input pubmed/bleeding-triple-therapy-case.txt \
        --model Qwen/Qwen3-8B \
        --target-words 470 \
        --output results/bleeding-qwen3-3x.txt

Requires the optional GPU stack:  pip install -e .[analysis]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

# Reuse the 8-bit loader and OOM handler from the perplexity profiler so the
# two analysis scripts share identical model-loading behavior.
from src.analysis.perplexity_profile import _handle_cuda_oom, load_model

DEFAULT_MODEL = "Qwen/Qwen3-8B"
MAX_NEW_TOKENS = 2048

SYSTEM_PROMPT_TEMPLATE = (
    "You are a clinical text compression assistant. Compress the following "
    "clinical case report to approximately {target_words} words while "
    "preserving ALL clinically actionable information. You must preserve: "
    "specific drug names (not drug classes), exact dosages and frequencies, "
    "lab values with units, diagnoses with qualifiers (stage, severity, type), "
    "temporal relationships, clinical reasoning, negated findings, allergies "
    "with reaction types. Do not generalize specific entities to categories. "
    "Do not omit dosages. Do not drop temporal markers. Return ONLY the "
    "compressed text. No commentary."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compress a clinical case with a local LLM, preserving "
        "clinically actionable detail.",
    )
    p.add_argument("--input", required=True, type=Path,
                   help="Clinical case text file (.txt).")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"HF model id (default: {DEFAULT_MODEL}).")
    p.add_argument("--target-words", required=True, type=int,
                   help="Approximate word count for the compressed output.")
    p.add_argument("--output", required=True, type=Path,
                   help="Output path for the compressed text. Metadata is "
                   "written alongside with a _metadata.txt suffix.")
    return p.parse_args(argv)


def _strip_thinking(text: str) -> str:
    """Remove any <think>...</think> block Qwen3 may emit despite the flag."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def compress(tokenizer, model, case_text: str, target_words: int) -> str:
    """Run the compression prompt and return the compressed text."""
    import torch

    messages = [
        {"role": "system",
         "content": SYSTEM_PROMPT_TEMPLATE.format(target_words=target_words)},
        {"role": "user", "content": case_text},
    ]
    # enable_thinking=False keeps Qwen3 out of its reasoning mode so the output
    # is the compressed text only (not a <think> trace).
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    enc = tokenizer(prompt, return_tensors="pt").to(model.device)

    try:
        with torch.no_grad():
            out = model.generate(
                **enc,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
    except Exception as exc:  # noqa: BLE001
        _handle_cuda_oom(exc, context="generation")
        raise

    new_tokens = out[0, enc["input_ids"].shape[1]:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return _strip_thinking(text)


def write_metadata(path: Path, *, model_id: str, target_words: int,
                   actual_words: int, input_name: str) -> None:
    lines = [
        f"model: {model_id}",
        f"input: {input_name}",
        f"target_words: {target_words}",
        f"actual_words: {actual_words}",
        f"date: {_dt.date.today().isoformat()}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote metadata: {path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.input.is_file():
        sys.exit(f"Input case not found: {args.input}")

    case_text = args.input.read_text(encoding="utf-8")
    tokenizer, model = load_model(args.model)

    compressed = compress(tokenizer, model, case_text, args.target_words)
    actual_words = len(compressed.split())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(compressed + "\n", encoding="utf-8")
    print(f"Wrote compressed text: {args.output}")

    meta_path = args.output.with_name(f"{args.output.stem}_metadata.txt")
    write_metadata(
        meta_path,
        model_id=args.model,
        target_words=args.target_words,
        actual_words=actual_words,
        input_name=args.input.name,
    )

    print(f"\nTarget words: {args.target_words}  |  Actual words: {actual_words}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
