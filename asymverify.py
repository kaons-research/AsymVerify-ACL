#!/usr/bin/env python3
"""Run the public AsymVerify confidence-gated verifier.

This script implements the paper-facing Pass 1 -> Pass 2 -> Pass 3 routing:

1. Base classification into Clear Reply, Ambivalent, or Clear Non-Reply.
2. If confidence is below the threshold and the current label is CR/CNR,
   run a downgrade verifier against Ambivalent.
3. If confidence is below the threshold and the current label is Ambivalent
   after Pass 2, run an upgrade verifier against Clear Reply.

The script uses OpenRouter-compatible chat completions and reads the API key
from OPENROUTER_API_KEY. It writes compact predictions by default; pass
prompts and raw model responses are stored only with --include-traces.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm_asyncio


LABELS = ["Clear Reply", "Ambivalent", "Clear Non-Reply"]
DEFAULT_MODEL = "z-ai/glm-4.7"
OPENROUTER_URL = "https://openrouter.ai/api/v1"


TAXONOMY = """## EVASION TAXONOMY

Answers may begin with speaker identification such as "President Trump." or
"Vice President Harris.". Treat this as transcript formatting and focus on
the substantive response that follows.

Clear Reply: Direct answer with specific information, commitment, concrete
numbers, names, dates, or policy positions.

Ambivalent: Evasive, vague, partial, implicit, deflecting, or topic-shifting
response that appears to engage but avoids concrete commitment.

Clear Non-Reply: Explicit refusal, explicit ignorance claim, or request for
clarification."""


PASS1_PROMPT = """You are classifying political Q&A exchanges for evasion.

{taxonomy}

Question: "{question}"

Answer: "{answer}"

Think through:
1. What specific information is the question asking for?
2. Does the answer provide that specific information?
3. Is there any evasion, deflection, or vagueness?

Output ONLY a JSON object:
{{"classification": "Clear Reply" | "Ambivalent" | "Clear Non-Reply", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""


PASS2_CR_TO_AMB_PROMPT = """Question: "{question}"
Answer: "{answer}"

Ignore speaker identification at the start of the answer and focus on the
substantive response.

Does this answer admit only one interpretation, or multiple interpretations?

Clear Reply = only one interpretation is possible. The answer explicitly
commits to a position.

Ambivalent = multiple interpretations are possible. The answer implies
something but does not explicitly state it, or requires inference.

Output ONLY a JSON object:
{{"classification": "Clear Reply" | "Ambivalent", "reasoning": "brief explanation"}}"""


PASS2_CNR_TO_AMB_PROMPT = """Question: "{question}"
Answer: "{answer}"

Ignore speaker identification at the start of the answer and focus on the
substantive response.

Is this a Clear Non-Reply or Ambivalent?

Clear Non-Reply = explicitly refuses, explicitly claims ignorance, or asks
for clarification.

Ambivalent = provides a response but allows multiple interpretations, gives
information that does not answer the question, or appears to engage without
committing to an answer.

Output ONLY a JSON object:
{{"classification": "Clear Non-Reply" | "Ambivalent", "reasoning": "brief explanation"}}"""


PASS3_AMB_TO_CR_PROMPT = """Question: "{question}"
Answer: "{answer}"

The current label is Ambivalent. Check whether it should be Clear Reply.

Ignore speaker identification at the start of the answer and inspect the first
substantive sentence.

Upgrade to Clear Reply if the first substantive sentence directly answers the
question with a yes/no answer, specific stance, concrete information, or clear
position, and is not immediately undercut by "but", "however", or "although".

Keep Ambivalent if the answer only hints, pivots, reframes, or requires
inference to recover the requested commitment.

Output ONLY a JSON object:
{{"classification": "Clear Reply" | "Ambivalent", "reasoning": "brief explanation"}}"""


@dataclass
class Settings:
    model: str
    threshold: float
    passes: set[int]
    max_tokens: int
    concurrency: int
    include_traces: bool


def parse_json_object(text: str | None) -> dict[str, Any] | None:
    """Extract a JSON object from a model response."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def normalize_label(label: Any, fallback: str = "Ambivalent") -> str:
    if not isinstance(label, str):
        return fallback
    label = label.strip()
    lower = label.lower()
    for canonical in LABELS:
        if lower == canonical.lower():
            return canonical
    aliases = {
        "cr": "Clear Reply",
        "clear_reply": "Clear Reply",
        "reply": "Clear Reply",
        "amb": "Ambivalent",
        "ambivalent": "Ambivalent",
        "cnr": "Clear Non-Reply",
        "clear_non_reply": "Clear Non-Reply",
        "clear non reply": "Clear Non-Reply",
        "non-reply": "Clear Non-Reply",
        "nonreply": "Clear Non-Reply",
    }
    return aliases.get(lower, fallback)


def clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def get_client() -> AsyncOpenAI:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set. See .env.example.")
    return AsyncOpenAI(base_url=OPENROUTER_URL, api_key=key, timeout=300.0)


async def call_model(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    prompt: str,
    pass_id: str,
    settings: Settings,
) -> dict[str, Any]:
    start = time.time()
    async with semaphore:
        last_error = None
        for attempt in range(1, 6):
            try:
                response = await client.chat.completions.create(
                    model=settings.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=settings.max_tokens,
                    response_format={"type": "json_object"},
                )
                message = response.choices[0].message
                raw = message.content
                if not raw:
                    raw = getattr(message, "reasoning", None)
                if not raw:
                    raw = getattr(message, "reasoning_content", None)
                parsed = parse_json_object(raw)
                usage = response.usage
                result = {
                    "pass_id": pass_id,
                    "success": parsed is not None,
                    "parsed": parsed,
                    "latency_ms": round((time.time() - start) * 1000, 1),
                    "tokens": {
                        "input": getattr(usage, "prompt_tokens", 0) if usage else 0,
                        "output": getattr(usage, "completion_tokens", 0) if usage else 0,
                    },
                    "attempts": attempt,
                }
                if settings.include_traces:
                    result["prompt"] = prompt
                    result["raw_response"] = raw
                return result
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = str(exc)
                if "429" in last_error or "rate" in last_error.lower():
                    await asyncio.sleep(min(2 ** attempt, 30))
                    continue
                break
        result = {
            "pass_id": pass_id,
            "success": False,
            "parsed": None,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "tokens": {"input": 0, "output": 0},
            "attempts": 5,
            "error": last_error or "request failed",
        }
        if settings.include_traces:
            result["prompt"] = prompt
        return result


def compact_pass(result: dict[str, Any], fallback: str, original: str | None = None) -> dict[str, Any]:
    parsed = result.get("parsed") or {}
    label = normalize_label(parsed.get("classification"), fallback=fallback)
    compact = {
        "pass_id": result["pass_id"],
        "success": bool(result.get("success")),
        "classification": label,
        "confidence": clamp_confidence(parsed.get("confidence", 0.0)),
        "reasoning": parsed.get("reasoning"),
        "latency_ms": result.get("latency_ms", 0),
        "tokens": result.get("tokens", {"input": 0, "output": 0}),
        "attempts": result.get("attempts", 0),
    }
    if original is not None:
        compact["changed"] = label != original
    for key in ("prompt", "raw_response", "error"):
        if key in result:
            compact[key] = result[key]
    return compact


async def classify_row(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    idx: int,
    row: pd.Series,
    settings: Settings,
    question_col: str,
    answer_col: str,
    label_col: str | None,
) -> dict[str, Any]:
    question = str(row.get(question_col, ""))
    answer = str(row.get(answer_col, ""))
    true_label = normalize_label(row.get(label_col), fallback="") if label_col else ""

    passes: list[dict[str, Any]] = []
    api_calls = 0

    p1_prompt = PASS1_PROMPT.format(taxonomy=TAXONOMY, question=question, answer=answer)
    p1 = compact_pass(
        await call_model(client, semaphore, p1_prompt, "P1", settings),
        fallback="Ambivalent",
    )
    passes.append(p1)
    api_calls += 1

    current = p1["classification"]
    confidence = p1["confidence"]
    gated = confidence >= settings.threshold

    if not gated and 2 in settings.passes:
        if current == "Clear Reply":
            prompt = PASS2_CR_TO_AMB_PROMPT.format(question=question, answer=answer)
            p2 = compact_pass(
                await call_model(client, semaphore, prompt, "P2-CR-to-AMB", settings),
                fallback="Clear Reply",
                original="Clear Reply",
            )
            passes.append(p2)
            api_calls += 1
            current = p2["classification"]
        elif current == "Clear Non-Reply":
            prompt = PASS2_CNR_TO_AMB_PROMPT.format(question=question, answer=answer)
            p2 = compact_pass(
                await call_model(client, semaphore, prompt, "P2-CNR-to-AMB", settings),
                fallback="Clear Non-Reply",
                original="Clear Non-Reply",
            )
            passes.append(p2)
            api_calls += 1
            current = p2["classification"]

    if not gated and 3 in settings.passes and current == "Ambivalent":
        prompt = PASS3_AMB_TO_CR_PROMPT.format(question=question, answer=answer)
        p3 = compact_pass(
            await call_model(client, semaphore, prompt, "P3-AMB-to-CR", settings),
            fallback="Ambivalent",
            original="Ambivalent",
        )
        passes.append(p3)
        api_calls += 1
        current = p3["classification"]

    result = {
        "index": int(idx),
        "prediction": current,
        "pass1_prediction": p1["classification"],
        "pass1_confidence": confidence,
        "high_confidence_exit": gated,
        "api_calls": api_calls,
        "passes_run": [p["pass_id"] for p in passes],
        "passes": passes,
    }
    if label_col:
        result["true_label"] = true_label
        result["correct"] = current == true_label
    return result


def detect_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    raise SystemExit(f"Could not find a {label} column. Tried: {', '.join(candidates)}")


def macro_f1(true_labels: list[str], predictions: list[str]) -> float:
    scores = []
    for label in LABELS:
        tp = sum(t == label and p == label for t, p in zip(true_labels, predictions))
        fp = sum(t != label and p == label for t, p in zip(true_labels, predictions))
        fn = sum(t == label and p != label for t, p in zip(true_labels, predictions))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        scores.append(f1)
    return sum(scores) / len(scores)


def summarize(results: list[dict[str, Any]], label_col: str | None) -> dict[str, Any]:
    predictions = [r["prediction"] for r in results]
    summary = {
        "n": len(results),
        "total_api_calls": sum(r["api_calls"] for r in results),
        "calls_per_example": round(sum(r["api_calls"] for r in results) / len(results), 3) if results else 0,
        "high_confidence_exits": sum(r["high_confidence_exit"] for r in results),
        "prediction_counts": dict(Counter(predictions)),
        "pass_counts": dict(Counter(pass_id for r in results for pass_id in r["passes_run"])),
    }
    if label_col:
        true_labels = [r["true_label"] for r in results]
        summary["accuracy"] = sum(t == p for t, p in zip(true_labels, predictions)) / len(results)
        summary["macro_f1"] = macro_f1(true_labels, predictions)
    return summary


async def run(args: argparse.Namespace) -> None:
    passes = {int(part) for part in args.passes.split(",") if part.strip()}
    if 1 not in passes:
        raise SystemExit("--passes must include Pass 1")
    unsupported = passes - {1, 2, 3}
    if unsupported:
        raise SystemExit(f"Unsupported passes: {sorted(unsupported)}")

    settings = Settings(
        model=args.model,
        threshold=args.threshold,
        passes=passes,
        max_tokens=args.max_tokens,
        concurrency=args.concurrency,
        include_traces=args.include_traces,
    )
    df = pd.read_csv(args.input)
    if args.limit:
        df = df.head(args.limit)

    question_col = args.question_col or detect_column(
        df, ["question", "interview_question", "q"], "question"
    )
    answer_col = args.answer_col or detect_column(
        df, ["answer", "interview_answer", "response", "r"], "answer"
    )
    label_col = args.label_col if args.label_col else None
    if label_col and label_col not in df.columns:
        raise SystemExit(f"Label column '{label_col}' is not present in {args.input}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = get_client()
    semaphore = asyncio.Semaphore(settings.concurrency)
    tasks = [
        classify_row(client, semaphore, int(idx), row, settings, question_col, answer_col, label_col)
        for idx, row in df.iterrows()
    ]
    results = await tqdm_asyncio.gather(*tasks, desc="AsymVerify")
    results = sorted(results, key=lambda item: item["index"])
    summary = summarize(results, label_col)
    summary["model"] = args.model
    summary["passes"] = sorted(passes)
    summary["confidence_threshold"] = args.threshold

    with (output_dir / "predictions.txt").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(result["prediction"] + "\n")

    pd.DataFrame(
        {
            "index": [r["index"] for r in results],
            "prediction": [r["prediction"] for r in results],
            "pass1_prediction": [r["pass1_prediction"] for r in results],
            "pass1_confidence": [r["pass1_confidence"] for r in results],
            "high_confidence_exit": [r["high_confidence_exit"] for r in results],
            "api_calls": [r["api_calls"] for r in results],
            "passes_run": [";".join(r["passes_run"]) for r in results],
        }
    ).to_csv(output_dir / "predictions.csv", index=False)

    with (output_dir / "results.json").open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"Wrote predictions and metrics to {output_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AsymVerify with OpenRouter")
    parser.add_argument("--input", required=True, help="CSV input file")
    parser.add_argument("--output-dir", default="outputs/run", help="Output directory")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id")
    parser.add_argument("--passes", default="1,2,3", help="Comma-separated pass ids: 1, 1,2, 1,3, or 1,2,3")
    parser.add_argument("--threshold", type=float, default=0.95, help="Pass-1 confidence gate")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent API requests")
    parser.add_argument("--max-tokens", type=int, default=1000, help="Maximum completion tokens")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for smoke tests")
    parser.add_argument("--question-col", default=None, help="Question column override")
    parser.add_argument("--answer-col", default=None, help="Answer column override")
    parser.add_argument("--label-col", default=None, help="Optional gold-label column")
    parser.add_argument(
        "--include-traces",
        action="store_true",
        help="Store prompts and raw model responses in results.json",
    )
    return parser


if __name__ == "__main__":
    asyncio.run(run(build_parser().parse_args()))
