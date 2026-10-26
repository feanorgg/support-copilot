"""Turn page snapshots into retrieval chunks.

One chunk per FAQ item and one "steps" chunk per page. The withdraw page repeats the deposit
page's FAQ verbatim, so identical Q&A pairs are merged into a single chunk that lists every
page it appears on: duplicates would otherwise crowd the top-k and inflate citations.
"""

from __future__ import annotations

import hashlib
import re

from app.schemas import Chunk

PAGE_SHORT = {
    "how-to-deposit": "deposit",
    "how-to-withdraw": "withdraw",
    "how-to-open-an-account": "open-account",
    "how-to-verify-account": "verify-account",
}


def slugify(text: str, max_words: int = 8) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {"a", "an", "the", "my", "i", "is", "to", "do", "can", "what", "how", "of", "on", "in", "for", "be"}
    kept = [w for w in words if w not in stop] or words
    return "-".join(kept[:max_words])


def build_chunks(pages: list[dict]) -> list[Chunk]:
    chunks: list[Chunk] = []
    by_hash: dict[str, Chunk] = {}

    for page in pages:
        short = PAGE_SHORT.get(page["slug"], page["slug"])

        if page["steps"]:
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(page["steps"], 1))
            body = f"{page['intro']}\n{steps}".strip()
            chunks.append(
                Chunk(
                    id=f"{short}#steps",
                    kind="steps",
                    section=f"{page['title']}: steps",
                    text=f"{page['title']}: steps\n{body}",
                    pages=[page["slug"]],
                    urls=[page["url"]],
                    page_titles=[page["title"]],
                )
            )

        for item in page["faq"]:
            digest = hashlib.sha1(f"{item['q']}\n{item['a']}".encode()).hexdigest()
            if digest in by_hash:
                existing = by_hash[digest]
                existing.pages.append(page["slug"])
                existing.urls.append(page["url"])
                existing.page_titles.append(page["title"])
                continue
            chunk = Chunk(
                id=f"{short}#faq-{slugify(item['q'])}",
                kind="faq",
                section=item["q"],
                text=f"{item['q']}\n{item['a']}",
                pages=[page["slug"]],
                urls=[page["url"]],
                page_titles=[page["title"]],
            )
            by_hash[digest] = chunk
            chunks.append(chunk)

    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk id collision"
    return chunks


def embed_text(chunk: Chunk) -> str:
    """Text sent to the embedding model: page context + section + body."""
    return f"{' / '.join(chunk.page_titles)}\n{chunk.text}"
