"""
Ragas evaluation of the RAG pipeline.

Closed-loop benchmark:
  1. For each question in sample_questions.QUESTIONS, run the agent
     end-to-end (creates a row in `reports`).
  2. Capture (question, answer = bull_case + bear_case, contexts =
     retrieved SEC chunks) per question.
  3. Run Ragas faithfulness / answer_relevancy / context_precision
     using Groq for the judge LLM and BGE for embeddings.
  4. Persist per-question scores to `eval_scores`.
  5. Log aggregates to MLflow.

Note: the reports table has no `question` column, so the only honest way
to evaluate is to control the question ourselves -- hence the closed-loop
design where the eval owns both the run and the scoring.
"""
import math
import os

import mlflow
from datasets import Dataset
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_relevancy, context_precision, faithfulness

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
        "ground_truth": "",
        "report_id": report.get("report_id"),
        "ticker": ticker,
    }


def _safe_float(x) -> float:
    try:
        f = float(x)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in .env")

    print(f"Building benchmark dataset from {len(QUESTIONS)} questions...")
    rows = []
    for q in QUESTIONS:
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
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=judge_llm,
        embeddings=judge_embeddings,
        raise_exceptions=False,
    )
    df = results.to_pandas()

    # Persist per-question scores tied to each report
    print("\nPersisting scores to eval_scores...")
    db = SessionLocal()
    saved = 0
    try:
        for row, (_, scores) in zip(rows, df.iterrows()):
            faith = _safe_float(scores.get("faithfulness"))
            relev = _safe_float(scores.get("answer_relevancy"))
            ctx = _safe_float(scores.get("context_precision"))
            ragas_overall = (faith + relev + ctx) / 3.0
            db.add(EvalScore(
                report_id=row["report_id"],
                faithfulness=faith,
                relevancy=relev,
                context_precision=ctx,
                ragas_score=ragas_overall,
            ))
            saved += 1
        db.commit()
    finally:
        db.close()

    # MLflow
    print("Logging to MLflow...")
    mlflow.set_experiment("ragas_evaluation")
    with mlflow.start_run():
        mlflow.log_param("model", GROQ_MODEL)
        mlflow.log_param("embedding_model", EMBED_MODEL)
        mlflow.log_param("retrieval_k", RETRIEVAL_K)
        mlflow.log_param("num_questions", len(rows))
        for col in ["faithfulness", "answer_relevancy", "context_precision"]:
            if col in df.columns:
                values = df[col].dropna()
                if len(values):
                    mlflow.log_metric(f"{col}_mean", float(values.mean()))
                    mlflow.log_metric(f"{col}_min", float(values.min()))
                    mlflow.log_metric(f"{col}_max", float(values.max()))

    # Summary
    print(f"\n{'='*108}")
    print(f"Ragas Evaluation")
    print(f"{'='*108}")
    print(f"  Questions evaluated: {len(rows)}")
    print(f"  Eval scores saved:   {saved}")
    print()
    print(
        f"  {'Question':<62} {'Faith':>7} {'Relev':>7} {'CtxP':>7}  Overall"
    )
    print(f"  {'-'*62} {'-'*7} {'-'*7} {'-'*7}  {'-'*7}")
    for row, (_, scores) in zip(rows, df.iterrows()):
        faith = _safe_float(scores.get("faithfulness"))
        relev = _safe_float(scores.get("answer_relevancy"))
        ctx = _safe_float(scores.get("context_precision"))
        overall = (faith + relev + ctx) / 3
        q = row["question"]
        q_disp = (q[:60] + "..") if len(q) > 62 else q
        print(
            f"  {q_disp:<62} {faith:>7.3f} {relev:>7.3f} {ctx:>7.3f}  {overall:>7.3f}"
        )

    print()
    if "faithfulness" in df.columns:
        print(
            f"  AVERAGES   "
            f"faith={df['faithfulness'].mean():.3f}   "
            f"relev={df['answer_relevancy'].mean():.3f}   "
            f"ctx_prec={df['context_precision'].mean():.3f}"
        )
    print(f"{'='*108}\n")


if __name__ == "__main__":
    main()
