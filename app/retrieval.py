"""Dense retrieval over the in-memory index (cosine on L2-normalised vectors)."""

from __future__ import annotations

from app.kb.index import load_index
from app.llm import embed
from app.schemas import LLMCall, RetrievedChunk


def retrieve(query: str, *, model: str, top_k: int, min_score: float) -> tuple[list[RetrievedChunk], LLMCall]:
    chunks, vectors = load_index()
    qvec, call = embed([query], model=model, stage="retrieve")
    scores = vectors @ qvec[0]
    order = scores.argsort()[::-1][:top_k]
    hits = [
        RetrievedChunk(chunk=chunks[i], score=round(float(scores[i]), 4), passed_to_llm=bool(scores[i] >= min_score))
        for i in order
    ]
    return hits, call
