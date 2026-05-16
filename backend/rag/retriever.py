"""
Retriever: pgvector cosine search over filing_chunks.

Embeds the query with the same BGE model used at index time; returns
top-k (chunk_text, ticker, form_type, score) tuples. Score = 1 - cosine
distance (so higher is better; range [-1, 1] but typically [0, 1]).
"""
import os

from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings

from backend.db.session import SessionLocal
from backend.db.models import Company, Filing, FilingChunk

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

load_dotenv()


EMBED_MODEL = "BAAI/bge-large-en-v1.5"
_embeddings = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        print(f"Loading {EMBED_MODEL}...")
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def search(query: str, k: int = 4, ticker: str | None = None) -> list[dict]:
    """
    Top-k chunks most similar to `query`. Optional ticker filter.
    Each result: chunk_text, filing_id, chunk_index, ticker, form_type,
    accession_number, score.
    """
    qvec = _get_embeddings().embed_query(query)

    db = SessionLocal()
    try:
        distance_col = FilingChunk.embedding.cosine_distance(qvec).label("distance")
        q = (
            db.query(FilingChunk, Filing, Company, distance_col)
            .join(Filing, FilingChunk.filing_id == Filing.id)
            .join(Company, Filing.company_id == Company.id)
            .filter(FilingChunk.embedding.isnot(None))
        )
        if ticker:
            q = q.filter(Company.ticker == ticker.upper())
        rows = q.order_by(distance_col.asc()).limit(k).all()

        return [{
            "chunk_text": chunk.chunk_text,
            "filing_id": chunk.filing_id,
            "chunk_index": chunk.chunk_index,
            "ticker": company.ticker,
            "form_type": filing.form_type,
            "accession_number": filing.accession_number,
            "score": 1.0 - float(distance),
        } for chunk, filing, company, distance in rows]
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "What are the main risk factors?"
    print(f"\nQuery: {query}\n")
    results = search(query, k=4, ticker="AAPL")
    if not results:
        print("No results. Has the embedder been run?")
    for i, r in enumerate(results, 1):
        print(
            f"{i}. {r['ticker']} {r['form_type']} "
            f"chunk #{r['chunk_index']}  score={r['score']:.4f}"
        )
        snippet = r["chunk_text"][:300].replace("\n", " ")
        print(f"   {snippet}...")
        print()
