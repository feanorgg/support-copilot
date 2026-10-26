"""Deterministic routing. Fail-closed: anything uncertain goes to a human reviewer.

Actions:
  draft_ready        - a support agent reviews the grounded draft and sends it
  specialist_review  - escalate to a human reviewer (complaints, KYC/AML, high urgency,
                       unsafe/ungrounded draft, LLM failure); any draft is only a suggestion
  abstain            - the KB does not cover the question; the agent answers manually
"""

from __future__ import annotations

from app.schemas import Classification, RouteDecision, SegmentResult


def route(
    *,
    classification: Classification | None,
    pre_flags: dict[str, list[str]],
    abstain: bool,
    segments: list[SegmentResult],
    grounding_score: float | None,
    min_grounding_score: float,
    errors: list[str],
) -> RouteDecision:
    specialist: list[str] = []
    info: list[str] = []

    if classification is None or errors:
        specialist.append("llm_failure")
    if classification is not None:
        if classification.complaint or "complaint" in pre_flags:
            specialist.append("complaint")
        if classification.kyc_aml_decision_request or "kyc_aml" in pre_flags:
            specialist.append("kyc_aml_outcome")
        if classification.urgency == "high":
            specialist.append("high_urgency")
        if classification.trading_advice_request or "trading_advice" in pre_flags:
            info.append("trading_advice_declined")
    else:
        if "complaint" in pre_flags:
            specialist.append("complaint")
        if "kyc_aml" in pre_flags:
            specialist.append("kyc_aml_outcome")

    if any(s.status == "forbidden" for s in segments):
        specialist.append("policy_violation_in_draft")
    if any(s.status in ("unsupported", "numeric_mismatch") for s in segments):
        specialist.append("ungrounded_draft")
    already_flagged = {"ungrounded_draft", "policy_violation_in_draft"} & set(specialist)
    if grounding_score is not None and grounding_score < min_grounding_score and not already_flagged:
        specialist.append("low_grounding_score")
    if any(s.kind == "unknown" for s in segments):
        info.append("partial_answer")

    if specialist:
        return RouteDecision(action="specialist_review", reasons=specialist + info)
    if abstain or not segments:
        return RouteDecision(action="abstain", reasons=["not_covered_by_kb"] + info)
    # A draft with no cited claim and no decline only says "we'll check": nothing in the KB
    # answered the question. Keep it as a holding reply, but the agent must answer manually.
    if not any(s.kind in ("claim", "decline") for s in segments):
        return RouteDecision(action="abstain", reasons=["no_kb_answer_holding_reply_only"] + info)
    return RouteDecision(action="draft_ready", reasons=info)
