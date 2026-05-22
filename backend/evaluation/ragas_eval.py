"""
Ragas evaluation of the RAG pipeline.

Closed-loop benchmark:
  1. For each question in sample_questions.QUESTIONS, run the agent
     end-to-end (creates a row in `reports`).
  2. Capture (question, answer = bull_case + bear_case, contexts =
     retrieved SEC chunks) per question.
  3. Run Ragas faithfulness / answer_relevancy / context_precision (and
     context_recall when a ground truth is provided) using Groq for the
     judge LLM and BGE for embeddings.
  4. Persist per-question scores to `eval_scores`.
  5. Write a reproducible baseline JSON to eval_results/ and log MLflow.

Run:
  uv run --module backend.evaluation.ragas_eval
  uv run --module backend.evaluation.ragas_eval --ticker NVDA

Note: the reports table has no `question` column, so the only honest way
to evaluate is to control the question ourselves -- hence the closed-loop
design where the eval owns both the run and the scoring.
"""
import argparse
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import mlflow
from datasets import Dataset
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from backend.agents.run_agent import analyze
from backend.db.models import EvalScore
from backend.db.session import SessionLocal
from backend.evaluation.benchmarks.sample_questions import QUESTIONS
from backend.rag.retriever import search

# Quiet HF chatter
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

load_dotenv()


GROQ_MODEL = "llama-3.3-70b-versatile"
EMBED_MODEL = "BAAI/bge-large-en-v1.5"
RETRIEVAL_K = 6
RESULTS_DIR = Path("eval_results")


def _git_commit_hash() -> str:
    """Current commit hash for reproducibility; 'unknown' outside a repo."""
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"])
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _build_eval_row(question_entry: dict) -> dict:
    """Run the agent on one benchmark question; capture eval inputs."""
    question = question_entry["question"]
    ticker = question_entry["ticker"]

    print(f"\n  >>> {ticker}: {question}")
    report = analyze(ticker, question)
    if "error" in report:
        return {"error": report["error"]}

    answer = (
        f"BULL CASE: {report.get('bull_case', '')}\n\n"
        f"BEAR CASE: {report.get('bear_case', '')}"
    )

    # Re-run the same retrieval the agent used so contexts match.
    chunks = search(question, k=RETRIEVAL_K, ticker=ticker)
    contexts = [c["chunk_text"] for c in chunks]

    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "ground_truth": question_entry.get("ground_truth", "") or "",
        "report_id": report.get("report_id"),
        "ticker": ticker,
    }


def _safe_float(x) -> float:
    try:
        f = float(x)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main(ticker_filter: str | None = None):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in .env")

    questions = QUESTIONS
    if ticker_filter:
        ticker_filter = ticker_filter.upper()
        questions = [q for q in QUESTIONS if q["ticker"].upper() == ticker_filter]
        if not questions:
            print(f"No benchmark questions for ticker {ticker_filter}.")
            return

    print(f"Building benchmark dataset from {len(questions)} questions...")
    rows = []
    for q in questions:
        row = _build_eval_row(q)
        if "error" in row:
            print(f"    SKIPPED: {row['error']}")
            continue
        if not row["contexts"]:
            print("    SKIPPED: no retrieved contexts (filings not embedded?)")
            continue
        rows.append(row)

    if not rows:
        print("No benchmark rows produced -- nothing to evaluate.")
        return

    print(f"\n{len(rows)} rows ready for Ragas.")

    dataset = Dataset.from_dict({
        "question": [r["question"] for r in rows],
        "answer": [r["answer"] for r in rows],
        "contexts": [r["contexts"] for r in rows],
        "ground_truth": [r["ground_truth"] for r in rows],
    })

    # context_recall is reference-based: only meaningful when at least one
    # row carries a ground_truth. Otherwise it would be all-NaN.
    has_ground_truth = any(r["ground_truth"].strip() for r in rows)
    metrics = [faithfulness, answer_relevancy, context_precision]
    if has_ground_truth:
        metrics.append(context_recall)
        print("  ground truths present -> including context_recall")
    else:
        print("  no ground truths -> skipping context_recall")

    # Ragas wants its own wrappers around langchain LLMs/embeddings.
    judge_llm = LangchainLLMWrapper(ChatGroq(
        model=GROQ_MODEL,
        temperature=0.0,
        api_key=api_key,
    ))
    judge_embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    ))

    print("Running Ragas evaluation (this calls the judge LLM ~3x per row)...")
    results = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=judge_embeddings,
        raise_exceptions=False,
    )
    df = results.to_pandas()
    has_recall_col = "context_recall" in df.columns

    # ── Persist per-question scores tied to each report ──────────────
    print("\nPersisting scores to eval_scores...")
    per_question = []
    db = SessionLocal()
    saved = 0
    try:
        for row, (_, scores) in zip(rows, df.iterrows()):
            faith = _safe_float(scores.get("faithfulness"))
            ans_rel = _safe_float(scores.get("answer_relevancy"))
            ctx_prec = _safe_float(scores.get("context_precision"))
            ctx_recall = (
                _safe_float(scores.get("context_recall")) if has_recall_col else None
            )

            component_scores = [faith, ans_rel, ctx_prec]
            if ctx_recall is not None:
                component_scores.append(ctx_recall)
            overall = _mean(component_scores)

            db.add(EvalScore(
                report_id=row["report_id"],
                faithfulness=faith,
                relevancy=ans_rel,            # legacy alias
                answer_relevancy=ans_rel,
                context_precision=ctx_prec,
                context_recall=ctx_recall,
                ragas_score=overall,
            ))
            saved += 1

            per_question.append({
                "question": row["question"],
                "ticker": row["ticker"],
                "report_id": row["report_id"],
                "faithfulness": faith,
                "answer_relevancy": ans_rel,
                "context_precision": ctx_prec,
                "context_recall": ctx_recall,
                "overall": overall,
            })
        db.commit()
    finally:
        db.close()

    # ── Aggregate means ──────────────────────────────────────────────
    aggregate = {
        "faithfulness_mean": _mean([p["faithfulness"] for p in per_question]),
        "answer_relevancy_mean": _mean([p["answer_relevancy"] for p in per_question]),
        "context_precision_mean": _mean([p["context_precision"] for p in per_question]),
        "context_recall_mean": (
            _mean([p["context_recall"] for p in per_question])
            if has_recall_col else None
        ),
        "overall_mean": _mean([p["overall"] for p in per_question]),
    }

    # ── Write reproducible baseline JSON ──────────────────────────────
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"baseline_{timestamp}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit_hash(),
        "model": GROQ_MODEL,
        "embedding_model": EMBED_MODEL,
        "retrieval_k": RETRIEVAL_K,
        "ticker_filter": ticker_filter,
        "num_questions": len(per_question),
        "has_ground_truth": has_ground_truth,
        "per_question": per_question,
        "aggregate": aggregate,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote baseline JSON -> {out_path}")

    # ── MLflow ────────────────────────────────────────────────────────
    print("Logging to MLflow...")
    mlflow.set_experiment("ragas_evaluation")
    with mlflow.start_run():
        mlflow.log_param("model", GROQ_MODEL)
        mlflow.log_param("embedding_model", EMBED_MODEL)
        mlflow.log_param("retrieval_k", RETRIEVAL_K)
        mlflow.log_param("num_questions", len(per_question))
        mlflow.log_param("git_commit", payload["git_commit"])
        if ticker_filter:
            mlflow.log_param("ticker_filter", ticker_filter)
        for key, value in aggregate.items():
            if value is not None:
                mlflow.log_metric(key, float(value))

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'='*108}")
    print(f"Ragas Evaluation")
    print(f"{'='*108}")
    print(f"  Questions evaluated: {len(per_question)}")
    print(f"  Eval scores saved:   {saved}")
    print(f"  Git commit:          {payload['git_commit'][:12]}")
    print()
    print(
        f"  {'Question':<58} {'Faith':>7} {'AnsRel':>7} {'CtxP':>7} {'CtxR':>7}  Overall"
    )
    print(f"  {'-'*58} {'-'*7} {'-'*7} {'-'*7} {'-'*7}  {'-'*7}")
    for p in per_question:
        q = p["question"]
        q_disp = (q[:56] + "..") if len(q) > 58 else q
        recall_disp = f"{p['context_recall']:>7.3f}" if p["context_recall"] is not None else f"{'-':>7}"
        print(
            f"  {q_disp:<58} {p['faithfulness']:>7.3f} {p['answer_relevancy']:>7.3f} "
            f"{p['context_precision']:>7.3f} {recall_disp}  {p['overall']:>7.3f}"
        )

    print()
    recall_mean = aggregate["context_recall_mean"]
    recall_str = f"{recall_mean:.3f}" if recall_mean is not None else "n/a"
    print(
        f"  AVERAGES   "
        f"faith={aggregate['faithfulness_mean']:.3f}   "
        f"ans_rel={aggregate['answer_relevancy_mean']:.3f}   "
        f"ctx_prec={aggregate['context_precision_mean']:.3f}   "
        f"ctx_recall={recall_str}   "
        f"overall={aggregate['overall_mean']:.3f}"
    )
    print(f"{'='*108}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ragas RAG-pipeline baseline eval")
    parser.add_argument(
        "--ticker",
        default=None,
        help="evaluate only questions for this ticker (e.g. NVDA)",
    )
    args = parser.parse_args()
    main(ticker_filter=args.ticker)
