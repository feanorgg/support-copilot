"""triage(ticket) -> TriageResult: pre-guard, classify, retrieve, draft, ground, route."""

from __future__ import annotations

import time

from app import prompts
from app.config import RUB_PER_USD, PipelineConfig, get_config
from app.grounding import ground_segments
from app.guardrails import pre_screen
from app.kb.index import chunk_by_id
from app.llm import LLMError, chat_json
from app.retrieval import retrieve
from app.router import route
from app.schemas import (
    Classification,
    Combined,
    Draft,
    LLMCall,
    RetrievedChunk,
    Segment,
    SegmentResult,
    TriageResult,
)


def triage(ticket: str, cfg: PipelineConfig | None = None) -> TriageResult:
    cfg = cfg or get_config()
    t0 = time.perf_counter()
    calls: list[LLMCall] = []
    errors: list[str] = []
    pre_flags = pre_screen(ticket)
    # Filled step by step so partial results (e.g. classification before a failed draft call)
    # survive an exception and still reach the router and the UI.
    st = _State()

    try:
        if cfg.mode == "two_call":
            _two_call(ticket, cfg, pre_flags, calls, st)
        elif cfg.mode == "single_call":
            _single_call(ticket, cfg, calls, st)
        else:
            raise ValueError(f"unknown mode {cfg.mode}")
    except LLMError as exc:
        errors.append(str(exc))
        calls.append(exc.call)
    except Exception as exc:  # embeddings/network failures must not crash triage: fail closed
        errors.append(f"{type(exc).__name__}: {exc}")
    classification, hits, draft = st.classification, st.hits, st.draft

    passed = [h for h in hits if h.passed_to_llm]
    abstain = draft is None or draft.abstain
    segments: list[SegmentResult] = []
    grounding_score = None
    if draft is not None and not draft.abstain:
        segments, grounding_score = ground_segments(
            draft.segments, chunk_by_id(), {h.chunk.id for h in passed}, ticket
        )
        cited = {c.chunk_id for s in segments for c in s.citations}
        for h in hits:
            h.cited = h.chunk.id in cited

    decision = route(
        classification=classification,
        pre_flags=pre_flags,
        abstain=abstain,
        segments=segments,
        grounding_score=grounding_score,
        min_grounding_score=cfg.min_grounding_score,
        errors=errors,
    )
    cost_rub = sum(c.cost_rub for c in calls)
    return TriageResult(
        ticket=ticket,
        config=cfg.name,
        classification=classification,
        pre_guard_flags=pre_flags,
        retrieved=hits,
        abstain=abstain,
        abstain_reason=(draft.abstain_reason if draft else ("no relevant knowledge-base excerpts" if not errors else "")),
        segments=segments,
        grounding_score=grounding_score,
        reply_text=render_reply(segments),
        agent_note=draft.agent_note if draft else "",
        route=decision,
        calls=calls,
        cost_rub=round(cost_rub, 4),
        cost_usd=round(cost_rub / RUB_PER_USD, 6),
        latency_ms=int((time.perf_counter() - t0) * 1000),
        errors=errors,
    )


class _State:
    def __init__(self):
        self.classification: Classification | None = None
        self.hits: list[RetrievedChunk] = []
        self.draft: Draft | None = None


def _two_call(ticket, cfg, pre_flags, calls, st: _State):
    cls, call = chat_json(
        stage="classify",
        model=cfg.classify_model,
        system=prompts.CLASSIFY_SYSTEM,
        user=prompts.classify_user(ticket),
        schema=Classification,
        reasoning_effort=cfg.reasoning_effort,
        max_tokens=600,
    )
    calls.append(call)
    st.classification = cls

    advice = cls.trading_advice_request or "trading_advice" in pre_flags
    if advice and not cls.has_supportable_question:
        st.draft = _decline_draft(cls.language)
        return

    hits, call = retrieve(cls.search_query or ticket, model=cfg.embed_model, top_k=cfg.top_k, min_score=cfg.min_retrieval_score)
    calls.append(call)
    st.hits = hits
    passed = [h for h in hits if h.passed_to_llm]
    if not passed:
        st.draft = Draft(abstain=True, abstain_reason="no knowledge-base excerpt above the relevance threshold", segments=[], agent_note="")
        return

    draft, call = chat_json(
        stage="draft",
        model=cfg.draft_model,
        system=prompts.draft_system(cls.language),
        user=prompts.draft_user(ticket, cls, passed),
        schema=Draft,
        reasoning_effort=cfg.reasoning_effort,
    )
    calls.append(call)
    st.draft = draft


def _single_call(ticket, cfg, calls, st: _State):
    # No classifier yet, so we retrieve on the raw ticket (multilingual embedding).
    hits, call = retrieve(ticket, model=cfg.embed_model, top_k=cfg.top_k, min_score=cfg.min_retrieval_score)
    calls.append(call)
    st.hits = hits
    passed = [h for h in hits if h.passed_to_llm]
    out, call = chat_json(
        stage="classify+draft",
        model=cfg.draft_model,
        system=prompts.COMBINED_SYSTEM,
        user=prompts.combined_user(ticket, passed),
        schema=Combined,
        reasoning_effort=cfg.reasoning_effort,
    )
    calls.append(call)
    st.classification, st.draft = out.classification, out.draft


def _decline_draft(language: str) -> Draft:
    text = prompts.DECLINE_TEMPLATES.get(language.lower()[:2], prompts.DECLINE_TEMPLATES["en"])
    note = "" if language.lower()[:2] in prompts.DECLINE_TEMPLATES else f"Template not available in '{language}'; English used, translate before sending."
    return Draft(abstain=False, abstain_reason="", segments=[Segment(text=text, kind="decline", citations=[])], agent_note=note)


def render_reply(segments: list[SegmentResult]) -> str:
    """Clean reply text (no markers). Boilerplate segments get their own paragraph."""
    paras: list[list[str]] = [[]]
    for s in segments:
        if s.kind == "boilerplate":
            if paras[-1]:
                paras.append([])
            paras[-1].append(s.text.strip())
            paras.append([])
        else:
            paras[-1].append(s.text.strip())
    return "\n\n".join(" ".join(p) for p in paras if p)
