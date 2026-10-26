"""Pydantic models: LLM output contracts (Classification, Draft) and pipeline results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------- Knowledge base ----------


class Chunk(BaseModel):
    id: str  # "<page>#<section>", e.g. "deposit#faq-minimum-deposit-amount"
    kind: Literal["steps", "faq"]
    section: str
    text: str  # first line is the section heading; quotes are verified against this text
    pages: list[str]
    urls: list[str]
    page_titles: list[str]


# ---------- LLM output contracts ----------

Category = Literal[
    "deposit",
    "withdrawal",
    "account_opening",
    "verification",
    "trading_conditions",
    "platform_technical",
    "account_access",
    "other",
]
Urgency = Literal["low", "medium", "high"]
Sentiment = Literal["positive", "neutral", "negative"]
SegmentKind = Literal["claim", "boilerplate", "unknown", "decline", "handoff"]


class Classification(BaseModel):
    category: Category
    urgency: Urgency
    language: str = Field(description="ISO 639-1 code of the customer's language, e.g. en, es, ar")
    sentiment: Sentiment
    trading_advice_request: bool = Field(
        description="Asks for buy/sell recommendations, signals, price predictions/targets or which leverage to use"
    )
    complaint: bool = Field(description="Expresses a complaint/dispute, threatens escalation, alleges fraud or demands compensation")
    kyc_aml_decision_request: bool = Field(
        description="Asks about/contests the outcome of verification, KYC/AML review, account restriction or source-of-funds checks"
    )
    has_supportable_question: bool = Field(
        description="Contains at least one support question other than a trading-advice request"
    )
    search_query: str = Field(description="Standalone English search query for the knowledge base")
    summary: str = Field(description="One-line English summary for the support agent")


class Citation(BaseModel):
    chunk_id: str
    quote: str = Field(description="Short verbatim excerpt copied character-for-character from the chunk")


class Segment(BaseModel):
    text: str
    kind: SegmentKind
    citations: list[Citation]


class Draft(BaseModel):
    abstain: bool
    abstain_reason: str
    segments: list[Segment]
    agent_note: str = Field(description="Short English note for the support agent (gaps, conflicts, what to check)")


class Combined(BaseModel):
    classification: Classification
    draft: Draft


# ---------- Pipeline results ----------

CitationStatus = Literal["verified", "fuzzy", "unverified", "unknown_chunk"]
SegmentStatus = Literal["grounded", "unsupported", "numeric_mismatch", "not_required", "forbidden"]
Action = Literal["draft_ready", "specialist_review", "abstain"]


class VerifiedCitation(BaseModel):
    n: int  # marker number shown in the UI, stable per (chunk_id) within one reply
    chunk_id: str
    quote: str
    status: CitationStatus
    score: float
    start: int | None = None  # char offsets of the quote inside Chunk.text
    end: int | None = None


class SegmentResult(BaseModel):
    text: str
    kind: SegmentKind
    citations: list[VerifiedCitation]
    status: SegmentStatus
    issues: list[str] = []


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    passed_to_llm: bool
    cited: bool = False


class RouteDecision(BaseModel):
    action: Action
    reasons: list[str]


class LLMCall(BaseModel):
    stage: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_rub: float = 0.0
    latency_ms: int = 0
    error: str | None = None


class TriageResult(BaseModel):
    ticket: str
    config: str
    classification: Classification | None
    pre_guard_flags: dict[str, list[str]]
    retrieved: list[RetrievedChunk]
    abstain: bool
    abstain_reason: str
    segments: list[SegmentResult]
    grounding_score: float | None
    reply_text: str
    agent_note: str
    route: RouteDecision
    calls: list[LLMCall]
    cost_rub: float
    cost_usd: float
    latency_ms: int
    errors: list[str]
