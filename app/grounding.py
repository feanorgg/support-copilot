"""Deterministic grounding checks for drafted replies.

For every citation the model must supply a verbatim quote from a chunk it was given. We locate
the quote in the chunk text (exact after normalisation, then fuzzy) to (a) prove it exists and
(b) get char offsets so the UI can highlight it. Claim segments need at least one located quote,
and every number in a segment must appear in the cited chunks or in the ticket itself.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from app.guardrails import output_violations
from app.schemas import Chunk, Segment, SegmentResult, VerifiedCitation

FUZZY_MIN_SCORE = 90.0
FUZZY_MIN_LEN = 12

_PUNCT_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Casefold, unify quotes/dashes, collapse whitespace; keep a map back to original offsets."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = False
    for i, ch in enumerate(text.translate(_PUNCT_MAP)):
        if ch.isspace():
            if prev_space or not out:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        prev_space = False
        for c in ch.casefold():
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def normalize(text: str) -> str:
    return _normalize_with_map(text)[0].strip()


def locate_quote(quote: str, text: str) -> tuple[str, float, int | None, int | None]:
    """Return (status, score, start, end) of `quote` inside `text`. Quotes with ellipses are
    split and every part must be found in order."""
    parts = [normalize(p).strip(" .\"'") for p in _ELLIPSIS.split(quote)]
    parts = [p for p in parts if p]
    if not parts:
        return "unverified", 0.0, None, None

    ntext, idx = _normalize_with_map(text)
    pos, spans, statuses, scores = 0, [], [], []
    for part in parts:
        hit = ntext.find(part, pos)
        if hit >= 0:
            spans.append((hit, hit + len(part)))
            statuses.append("verified")
            scores.append(100.0)
            pos = hit + len(part)
            continue
        if len(part) < FUZZY_MIN_LEN:
            return "unverified", 0.0, None, None
        al = fuzz.partial_ratio_alignment(part, ntext[pos:])
        if al is None or al.score < FUZZY_MIN_SCORE:
            return "unverified", round(al.score if al else 0.0, 1), None, None
        spans.append((pos + al.dest_start, pos + al.dest_end))
        statuses.append("fuzzy")
        scores.append(al.score)
        pos += al.dest_end

    start, end = idx[spans[0][0]], idx[spans[-1][1] - 1] + 1
    status = "verified" if all(s == "verified" for s in statuses) else "fuzzy"
    return status, round(min(scores), 1), start, end


def numbers_in(text: str) -> set[str]:
    """Atomic digit runs, with non-ASCII digits (Arabic-Indic, Devanagari, Thai...) mapped to ASCII."""
    ascii_text = "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in text)
    return set(re.findall(r"\d+", ascii_text))


def ground_segments(
    segments: list[Segment], chunks: dict[str, Chunk], allowed_ids: set[str], ticket: str
) -> tuple[list[SegmentResult], float | None]:
    markers: dict[str, int] = {}
    ticket_numbers = numbers_in(ticket)
    results: list[SegmentResult] = []

    verified: list[list[VerifiedCitation]] = []
    for seg in segments:
        cites: list[VerifiedCitation] = []
        for c in seg.citations:
            n = markers.setdefault(c.chunk_id, len(markers) + 1)
            if c.chunk_id not in allowed_ids or c.chunk_id not in chunks:
                cites.append(VerifiedCitation(n=n, chunk_id=c.chunk_id, quote=c.quote, status="unknown_chunk", score=0.0))
                continue
            status, score, start, end = locate_quote(c.quote, chunks[c.chunk_id].text)
            cites.append(VerifiedCitation(n=n, chunk_id=c.chunk_id, quote=c.quote, status=status, score=score, start=start, end=end))
        verified.append(cites)

    def _located(cites: list[VerifiedCitation]) -> list[VerifiedCitation]:
        return [c for c in cites if c.status in ("verified", "fuzzy")]

    # Non-claim segments ("if it's not there after 60 minutes, reply") may reuse numbers from any
    # source cited elsewhere in the same reply; claims must be backed by their own citations.
    reply_numbers = set(ticket_numbers)
    for cites in verified:
        for c in _located(cites):
            reply_numbers |= numbers_in(chunks[c.chunk_id].text)

    for seg, cites in zip(segments, verified):
        located = _located(cites)
        issues: list[str] = []
        status = "not_required"

        if seg.kind == "claim":
            support_numbers = set(ticket_numbers)
            for c in located:
                support_numbers |= numbers_in(chunks[c.chunk_id].text)
        else:
            support_numbers = reply_numbers
        stray = sorted(numbers_in(seg.text) - support_numbers)

        if seg.kind == "claim":
            status = "grounded"
            if not located:
                status = "unsupported"
                issues.append("claim has no verifiable quote")
        if stray:
            status = "numeric_mismatch"
            issues.append(f"numbers not found in cited sources or ticket: {', '.join(stray)}")
        bad_cites = [c for c in cites if c.status in ("unverified", "unknown_chunk")]
        if bad_cites:
            issues.append(f"{len(bad_cites)} citation(s) could not be verified")
        violations = output_violations(seg.text)
        if violations:
            status = "forbidden"
            issues.extend(violations)

        results.append(SegmentResult(text=seg.text, kind=seg.kind, citations=cites, status=status, issues=issues))

    claims = [r for r in results if r.kind == "claim"]
    score = None if not claims else round(sum(r.status == "grounded" for r in claims) / len(claims), 3)
    return results, score
