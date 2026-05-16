"""
SEC Filing Embedder.

Chunks raw filing text and embeds each chunk with BAAI/bge-large-en-v1.5
via sentence-transformers (1024-dim vectors). Writes chunks to the
filing_chunks table and flips the parent Filing's is_embedded flag.
"""
import os

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from backend.db.session import SessionLocal
from backend.db.models import Filing, FilingChunk

# Quiet HF / tokenizer chatter for clean script output.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

load_dotenv()


EMBED_MODEL = "BAAI/bge-large-en-v1.5"
EMBED_DIM = 1024
DEFAULT_CHUNK_SIZE = 500   # words (not BPE tokens -- see chunk_text docstring)
DEFAULT_OVERLAP = 50       # words
DEFAULT_BATCH_SIZE = 32

_model = None  # lazy singleton


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"Loading embedding model {EMBED_MODEL} (first run downloads ~1.3 GB)...")
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """
    Split `text` into chunks of ~`chunk_size` words with `overlap` words
    of context shared between adjacent chunks. Returns list of chunk strings.

    Note: chunks are sized in WORDS, not BPE tokens. BGE's max sequence
    length is 512 BPE tokens; 500 words usually fits but the model truncates
    internally if a chunk overflows. If exact BPE-token boundaries matter
    later, swap text.split() for the model's tokenizer.
    """
    if not text:
        return []
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    words = text.split()
    if not words:
        return []

    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(words), step):
        chunk_words = words[start : start + chunk_size]
        if not chunk_words:
            break
        chunks.append(" ".join(chunk_words))
        if start + chunk_size >= len(words):
            break
    return chunks


def embed_chunks(
    chunks: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """Embed `chunks` and return a list of 1024-dim float vectors."""
    if not chunks:
        return []
    model = _get_model()
    vectors = model.encode(
        chunks,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,   # cosine-friendly; BGE recommends it
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


def process_filing(filing_id: int, text: str, db) -> dict:
    """
    Chunk + embed one filing's raw_text and persist to filing_chunks.
    Skips if the filing already has any chunks. Returns a status dict.
    """
    existing = (
        db.query(FilingChunk)
        .filter(FilingChunk.filing_id == filing_id)
        .first()
    )
    if existing:
        return {
            "filing_id": filing_id,
            "skipped": True,
            "chunks": 0,
            "reason": "already embedded",
        }

    chunks = chunk_text(text)
    if not chunks:
        return {
            "filing_id": filing_id,
            "skipped": True,
            "chunks": 0,
            "reason": "no chunks (empty text)",
        }

    vectors = embed_chunks(chunks)
    for idx, (chunk_str, vec) in enumerate(zip(chunks, vectors)):
        db.add(FilingChunk(
            filing_id=filing_id,
            chunk_text=chunk_str,
            chunk_index=idx,
            embedding=vec,
        ))

    filing = db.query(Filing).filter(Filing.id == filing_id).first()
    if filing:
        filing.is_embedded = 1

    db.commit()
    return {"filing_id": filing_id, "skipped": False, "chunks": len(chunks)}


def run_embedding_pipeline() -> dict:
    """
    Embed every filing where is_embedded=0 AND raw_text is non-empty.
    Returns summary counts.
    """
    db = SessionLocal()
    summary = {
        "found": 0,
        "processed": 0,
        "skipped": 0,
        "total_chunks": 0,
        "errors": [],
    }
    try:
        filings = (
            db.query(Filing)
            .filter(Filing.is_embedded == 0)
            .filter(Filing.raw_text.isnot(None))
            .filter(Filing.raw_text != "")
            .all()
        )
        summary["found"] = len(filings)
        print(f"Found {len(filings)} filings to embed")
        if not filings:
            return summary

        for filing in filings:
            try:
                result = process_filing(filing.id, filing.raw_text, db)
                if result.get("skipped"):
                    summary["skipped"] += 1
                    reason = result.get("reason", "skipped")
                    print(f"  filing_id={filing.id}  SKIPPED ({reason})")
                else:
                    summary["processed"] += 1
                    summary["total_chunks"] += result["chunks"]
                    print(f"  filing_id={filing.id}  {result['chunks']} chunks embedded")
            except Exception as e:
                summary["errors"].append(f"filing_id={filing.id}: {e}")
                print(f"  filing_id={filing.id}  ERROR: {e}")
                db.rollback()
        return summary
    finally:
        db.close()


def main():
    summary = run_embedding_pipeline()
    print(f"\n{'='*60}")
    print(f"Embedding Pipeline ({EMBED_MODEL})")
    print(f"{'='*60}")
    print(f"  Filings found (is_embedded=0): {summary['found']}")
    print(f"  Filings processed:             {summary['processed']}")
    print(f"  Filings skipped:               {summary['skipped']}")
    print(f"  Chunks embedded:               {summary['total_chunks']}")
    if summary["errors"]:
        print(f"  Errors ({len(summary['errors'])}):")
        for err in summary["errors"]:
            print(f"    {err}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
