"""
FinBERT Sentiment Evaluator.

Scores news_articles rows where sentiment_score IS NULL using
ProsusAI/finbert, writes label + signed score back to the row,
then aggregates per-company stats and persists one prediction
per company to ml_predictions.
"""
import os
import re
from collections import Counter

import mlflow
import torch
from dotenv import load_dotenv
from transformers import pipeline

from backend.db.session import SessionLocal
from backend.db.models import Company, NewsArticle
from backend.db.crud import save_ml_prediction
from backend.ingestion.pipeline import safe_float

# Quiet transformers + tokenizer chatter before they import.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

load_dotenv()


FINBERT_MODEL = "ProsusAI/finbert"
BATCH_SIZE = 16
MAX_LENGTH = 512

# Minimal stopword list -- enough to keep "dominant theme" word counts
# from being dominated by english function words.
STOPWORDS = {
    "about", "above", "after", "again", "against", "all", "also", "and",
    "any", "are", "because", "been", "before", "being", "below", "between",
    "both", "but", "could", "down", "during", "each", "from", "further",
    "have", "having", "here", "into", "more", "most", "once", "only",
    "other", "over", "same", "should", "some", "such", "than", "that",
    "their", "them", "then", "there", "these", "they", "this", "those",
    "through", "under", "until", "very", "were", "what", "when", "where",
    "which", "while", "with", "would", "your", "youll", "youre", "youve",
    "said", "says", "will", "just",
}
WORD_RE = re.compile(r"[A-Za-z]{4,}")


def _label_to_score(label: str, prob: float) -> float:
    """Map (label, prob in [0, 1]) -> signed score in [-1, +1]."""
    label = (label or "").lower()
    if label == "positive":
        return float(prob)
    if label == "negative":
        return -float(prob)
    return 0.0


def _build_text(article: NewsArticle) -> str:
    parts = []
    if article.title:
        parts.append(article.title.strip())
    if article.description:
        parts.append(article.description.strip())
    return ". ".join(p for p in parts if p).strip()


def score_unscored_articles(classifier) -> int:
    """Score every article with sentiment_score IS NULL. Returns count scored."""
    db = SessionLocal()
    scored = 0
    try:
        unscored = (
            db.query(NewsArticle)
            .filter(NewsArticle.sentiment_score.is_(None))
            .all()
        )
        if not unscored:
            print("  no unscored articles")
            return 0

        pairs = [(a, _build_text(a)) for a in unscored]
        pairs = [(a, t) for a, t in pairs if t]
        print(f"  {len(pairs)} articles to score (batch size {BATCH_SIZE})")

        for start in range(0, len(pairs), BATCH_SIZE):
            chunk = pairs[start : start + BATCH_SIZE]
            texts = [t for _, t in chunk]
            results = classifier(
                texts,
                batch_size=BATCH_SIZE,
                truncation=True,
                max_length=MAX_LENGTH,
            )
            for (article, _), result in zip(chunk, results):
                label = str(result["label"]).lower()
                prob = float(result["score"])
                article.sentiment_label = label
                article.sentiment_score = _label_to_score(label, prob)
                scored += 1
            db.commit()
            print(f"  scored {min(start + BATCH_SIZE, len(pairs))} / {len(pairs)}")
        return scored
    finally:
        db.close()


def _dominant_theme(articles: list[NewsArticle], top_n: int = 3) -> list[str]:
    """Top-N alphabetic words (len >= 4, not stopwords) across the given articles."""
    counter = Counter()
    for art in articles:
        text = _build_text(art).lower()
        for w in WORD_RE.findall(text):
            if w not in STOPWORDS:
                counter[w] += 1
    return [w for w, _ in counter.most_common(top_n)]


def aggregate_and_persist() -> list[dict]:
    """One ml_predictions row per company that has any scored article."""
    db = SessionLocal()
    summaries = []
    try:
        for company in db.query(Company).all():
            articles = (
                db.query(NewsArticle)
                .filter(NewsArticle.company_id == company.id)
                .all()
            )
            if not articles:
                continue

            scored = [a for a in articles if a.sentiment_score is not None]
            if not scored:
                continue

            scores = [float(a.sentiment_score) for a in scored]
            avg = sum(scores) / len(scores)
            pos = [a for a in scored if (a.sentiment_label or "").lower() == "positive"]
            neg = [a for a in scored if (a.sentiment_label or "").lower() == "negative"]
            neu = [a for a in scored if (a.sentiment_label or "").lower() == "neutral"]

            most_pos = max(scored, key=lambda a: a.sentiment_score)
            most_neg = min(scored, key=lambda a: a.sentiment_score)
            theme = _dominant_theme(pos)
            confidence = len(scored) / len(articles)

            shap_values = {
                "avg_sentiment": safe_float(avg),
                "positive_count": len(pos),
                "negative_count": len(neg),
                "neutral_count": len(neu),
                "total_articles": len(articles),
                "most_positive_headline": (most_pos.title or "")[:300],
                "most_negative_headline": (most_neg.title or "")[:300],
            }

            save_ml_prediction(db, company.id, {
                "model_name": "finbert_sentiment",
                "prediction": safe_float(avg),
                "confidence": safe_float(confidence),
                "shap_values": shap_values,
                "features_used": {
                    "ticker": company.ticker,
                    "scored_articles": len(scored),
                    "total_articles": len(articles),
                    "dominant_theme": ", ".join(theme) if theme else "",
                },
            })

            summaries.append({
                "ticker": company.ticker,
                "total": len(articles),
                "scored": len(scored),
                "avg": avg,
                "pos": len(pos),
                "neg": len(neg),
                "neu": len(neu),
                "theme": theme,
                "most_pos": most_pos.title,
                "most_neg": most_neg.title,
            })
        return summaries
    finally:
        db.close()


def main():
    print("Loading FinBERT (first run downloads ~440 MB)...")
    device = 0 if torch.cuda.is_available() else -1
    print(f"  device: {'cuda:0' if device == 0 else 'cpu'}")
    classifier = pipeline(
        "sentiment-analysis",
        model=FINBERT_MODEL,
        tokenizer=FINBERT_MODEL,
        device=device,
    )

    print("Scoring unscored news articles...")
    n_scored = score_unscored_articles(classifier)

    print("Aggregating per-company sentiment...")
    summaries = aggregate_and_persist()

    # ── MLflow ──────────────────────────────────────
    print("Logging run to MLflow...")
    mlflow.set_experiment("finbert_sentiment")
    with mlflow.start_run():
        mlflow.log_params({
            "model": FINBERT_MODEL,
            "batch_size": BATCH_SIZE,
            "max_length": MAX_LENGTH,
            "device": "cuda:0" if device == 0 else "cpu",
        })
        mlflow.log_metric("articles_scored_this_run", n_scored)
        mlflow.log_metric("companies_summarized", len(summaries))
        if summaries:
            avgs = [s["avg"] for s in summaries]
            mlflow.log_metric("company_sentiment_mean", sum(avgs) / len(avgs))
            mlflow.log_metric("company_sentiment_max", max(avgs))
            mlflow.log_metric("company_sentiment_min", min(avgs))

    # ── Summary ─────────────────────────────────────
    print(f"\n{'='*108}")
    print(f"FinBERT Sentiment Evaluator")
    print(f"{'='*108}")
    print(f"  Articles scored this run:  {n_scored}")
    print(f"  Companies summarized:      {len(summaries)}")
    print()

    if not summaries:
        print("  No companies with scored articles. Run the ingestion pipeline first.")
        print(f"{'='*108}\n")
        return

    print(
        f"  {'Ticker':<8} {'Articles':>9} {'Scored':>7} {'Avg':>7} "
        f"{'Pos':>4} {'Neu':>4} {'Neg':>4}  Theme"
    )
    print(
        f"  {'-'*8} {'-'*9} {'-'*7} {'-'*7} "
        f"{'-'*4} {'-'*4} {'-'*4}  {'-'*40}"
    )
    for s in sorted(summaries, key=lambda s: s["avg"], reverse=True):
        theme = ", ".join(s["theme"]) if s["theme"] else "-"
        print(
            f"  {s['ticker']:<8} {s['total']:>9} {s['scored']:>7} "
            f"{s['avg']:>+7.3f} "
            f"{s['pos']:>4} {s['neu']:>4} {s['neg']:>4}  {theme}"
        )

    top = max(summaries, key=lambda s: s["avg"])
    bot = min(summaries, key=lambda s: s["avg"])
    print(f"\n  Most-positive company {top['ticker']} (avg {top['avg']:+.3f}):")
    print(f"    headline: {top['most_pos']}")
    print(f"  Most-negative company {bot['ticker']} (avg {bot['avg']:+.3f}):")
    print(f"    headline: {bot['most_neg']}")
    print(f"{'='*108}\n")


if __name__ == "__main__":
    main()
