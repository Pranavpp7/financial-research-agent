"""
RAG Q&A: retrieve top-k chunks, format as context, ask Groq Llama 3.3 70B.
"""
import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from backend.rag.retriever import search

load_dotenv()


SYSTEM_PROMPT = (
    "You are a financial research assistant. Answer the question using ONLY "
    "the provided SEC filing context. Cite each claim by chunk reference in "
    "[brackets] (e.g. [AAPL 10-K chunk #42]). If the context does not contain "
    "the answer, say so explicitly -- do not speculate."
)

GROQ_MODEL = "llama-3.3-70b-versatile"


def answer(question: str, k: int = 6, ticker: str | None = "AAPL") -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not found in .env. Add it and re-run."
        )

    chunks = search(question, k=k, ticker=ticker)
    if not chunks:
        return {
            "answer": "No relevant chunks found. Has the embedder been run?",
            "sources": [],
        }

    context_blocks = []
    for c in chunks:
        header = f"[{c['ticker']} {c['form_type']} chunk #{c['chunk_index']}]"
        context_blocks.append(f"{header}\n{c['chunk_text']}")
    context = "\n\n".join(context_blocks)

    llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=api_key)
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
    ])

    return {
        "answer": response.content,
        "sources": [{
            "ticker": c["ticker"],
            "form_type": c["form_type"],
            "chunk_index": c["chunk_index"],
            "score": c["score"],
        } for c in chunks],
    }


def main():
    questions = [
        "What are Apple's biggest risk factors?",
        "How much revenue did Apple report in the most recent period?",
        "What does Apple say about supply chain concentration?",
        "What are Apple's main product segments?",
    ]
    for q in questions:
        print(f"\n{'='*88}")
        print(f"Q: {q}")
        print(f"{'='*88}")
        try:
            result = answer(q, k=6, ticker="AAPL")
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        print(f"\nA: {result['answer']}")
        if result["sources"]:
            print(f"\nSources used:")
            for s in result["sources"]:
                print(
                    f"  {s['ticker']} {s['form_type']} "
                    f"chunk #{s['chunk_index']}  score={s['score']:.4f}"
                )


if __name__ == "__main__":
    main()
