"""Build / load the in-memory vector index (chunks.jsonl + embeddings.npy)."""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from app.config import EMBED_MODEL, INDEX_DIR
from app.kb.chunk import build_chunks, embed_text
from app.kb.scrape import load_pages
from app.llm import embed
from app.schemas import Chunk

CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
VECTORS_PATH = INDEX_DIR / "embeddings.npy"
META_PATH = INDEX_DIR / "meta.json"


def build_index(model: str = EMBED_MODEL) -> tuple[list[Chunk], np.ndarray]:
    chunks = build_chunks(load_pages())
    vectors, call = embed([embed_text(c) for c in chunks], model=model, stage="index")
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_PATH.write_text("\n".join(c.model_dump_json() for c in chunks) + "\n", encoding="utf-8")
    np.save(VECTORS_PATH, vectors)
    META_PATH.write_text(
        json.dumps({"embed_model": model, "n_chunks": len(chunks), "dim": int(vectors.shape[1]), "cost_rub": call.cost_rub}, indent=2),
        encoding="utf-8",
    )
    load_index.cache_clear()
    return chunks, vectors


@lru_cache(maxsize=1)
def load_index() -> tuple[list[Chunk], np.ndarray]:
    chunks = [Chunk.model_validate_json(line) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line]
    vectors = np.load(VECTORS_PATH)
    assert len(chunks) == vectors.shape[0], "index is out of sync, rebuild it"
    return chunks, vectors


def chunk_by_id() -> dict[str, Chunk]:
    return {c.id: c for c in load_index()[0]}
