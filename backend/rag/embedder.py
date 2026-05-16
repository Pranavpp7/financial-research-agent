"""
RAG Embedder (LangChain-based).

For each filing where is_embedded=0 and raw_text is non-empty:
  1. Write raw_text (HTML) to a temp file
  2. Load via UnstructuredHTMLLoader (preserves paragraph/section structure)
  3. Split via RecursiveCharacterTextSplitter
  4. Embed via HuggingFaceEmbeddings (BAAI/bge-large-en-v1.5)
  5. Persist chunks to filing_chunks (Vector(1024) column)
"""
import os
import tempfile

from dotenv import load_dotenv
from langchain_community.document_loaders import UnstructuredHTMLLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

from backend.db.session import SessionLocal
from backend.db.models import Filing, FilingChunk

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

load_dotenv()


EMBED_MODEL = "BAAI/bge-large-en-v1.5"
CHUNK_SIZE = 1500       # characters
CHUNK_OVERLAP = 200     # characters
BATCH_SIZE = 32

_embeddings = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        print(f"Loading {EMBED_MODEL} (first run downloads ~1.3 GB)...")
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            encode_kwargs={
                "normalize_embeddings": True,
                "batch_size": BATCH_SIZE,
            },
        )
    return _embeddings


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _load_html_to_docs(html: str):
    """LangChain's UnstructuredHTMLLoader is file-based; round-trip via tempfile."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as f:
        f.write(html)
        tmp_path = f.name
    try:
        return UnstructuredHTMLLoader(tmp_path).load()
    finally:
        os.remove(tmp_path)


def process_filing(filing_id: int) -> dict:
    db = SessionLocal()
    try:
        filing = db.query(Filing).filter(Filing.id == filing_id).first()
        if not filing:
            return {"error": f"filing_id={filing_id} not found"}
        if not filing.raw_text:
            return {"error": "raw_text is empty"}

        if (db.query(FilingChunk)
                .filter(FilingChunk.filing_id == filing_id)
                .first()):
            return {"skipped": True, "reason": "already chunked"}

        print(f"  loading HTML via UnstructuredHTMLLoader ({len(filing.raw_text):,} chars)...")
        docs = _load_html_to_docs(filing.raw_text)
        print(f"  loaded {len(docs)} document(s); splitting...")
        splits = _splitter().split_documents(docs)
        print(f"  {len(splits)} chunks; embedding...")

        embeddings = _get_embeddings()
        texts = [s.page_content for s in splits]
        vectors = embeddings.embed_documents(texts)

        for idx, (split, vec) in enumerate(zip(splits, vectors)):
            db.add(FilingChunk(
                filing_id=filing.id,
                chunk_text=split.page_content,
                chunk_index=idx,
                embedding=vec,
            ))
        filing.is_embedded = 1
        db.commit()
        return {"chunks": len(splits)}
    finally:
        db.close()


def run_for_unembedded():
    db = SessionLocal()
    try:
        filings = (
            db.query(Filing)
            .filter(Filing.is_embedded == 0)
            .filter(Filing.raw_text.isnot(None))
            .filter(Filing.raw_text != "")
            .all()
        )
        print(f"Found {len(filings)} filings to embed")
        for filing in filings:
            print(f"\nFiling {filing.id} ({filing.form_type} {filing.accession_number}):")
            result = process_filing(filing.id)
            if "error" in result:
                print(f"  ERROR: {result['error']}")
            elif result.get("skipped"):
                print(f"  SKIPPED: {result['reason']}")
            else:
                print(f"  DONE: {result['chunks']} chunks embedded")
    finally:
        db.close()


if __name__ == "__main__":
    run_for_unembedded()
