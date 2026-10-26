"""Pipeline wiring with the LLM and retrieval mocked out (no network, no API key)."""

import pytest

from app import pipeline
from app.config import get_config
from app.llm import LLMError
from app.schemas import Chunk, Citation, Classification, Draft, LLMCall, RetrievedChunk, Segment

CHUNK = Chunk(
    id="deposit#faq-minimum-deposit-amount", kind="faq", section="What is the minimum deposit amount?",
    text="What is the minimum deposit amount?\nThe minimum deposit starts from 8 USD, depending on the account type.",
    pages=["how-to-deposit"], urls=["https://valetax.com/how-to-deposit/"], page_titles=["How to Deposit"],
)


def _cls(**kw):
    base = dict(category="deposit", urgency="low", language="en", sentiment="neutral", trading_advice_request=False,
                complaint=False, kyc_aml_decision_request=False, has_supportable_question=True,
                search_query="minimum deposit", summary="asks min deposit")
    return Classification(**{**base, **kw})


GOOD_DRAFT = Draft(abstain=False, abstain_reason="", agent_note="", segments=[
    Segment(text="Hi!", kind="boilerplate", citations=[]),
    Segment(text="The minimum deposit starts from 8 USD.", kind="claim",
            citations=[Citation(chunk_id=CHUNK.id, quote="The minimum deposit starts from 8 USD")]),
])


@pytest.fixture
def mock_env(monkeypatch):
    state = {"cls": _cls(), "draft": GOOD_DRAFT, "draft_error": False, "retrieve_calls": 0}

    def fake_chat_json(*, stage, schema, **_):
        call = LLMCall(stage=stage, model="m", cost_rub=0.01)
        if stage == "classify":
            return state["cls"], call
        if state["draft_error"]:
            raise LLMError("draft: boom", call)
        return state["draft"], call

    def fake_retrieve(query, **_):
        state["retrieve_calls"] += 1
        return [RetrievedChunk(chunk=CHUNK, score=0.7, passed_to_llm=True)], LLMCall(stage="retrieve", model="e")

    monkeypatch.setattr(pipeline, "chat_json", fake_chat_json)
    monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "chunk_by_id", lambda: {CHUNK.id: CHUNK})
    return state


CFG = get_config("haiku_two_call")


def test_happy_path_is_draft_ready(mock_env):
    res = pipeline.triage("What is the minimum deposit?", CFG)
    assert res.route.action == "draft_ready"
    assert res.grounding_score == 1.0
    assert res.retrieved[0].cited
    assert res.reply_text == "Hi!\n\nThe minimum deposit starts from 8 USD."


def test_draft_failure_keeps_classification_and_fails_closed(mock_env):
    mock_env["draft_error"] = True
    res = pipeline.triage("What is the minimum deposit?", CFG)
    assert res.classification is not None
    assert res.route.action == "specialist_review" and "llm_failure" in res.route.reasons


def test_pure_trading_advice_uses_template_without_retrieval(mock_env):
    mock_env["cls"] = _cls(trading_advice_request=True, has_supportable_question=False, language="es")
    res = pipeline.triage("¿Compro oro?", CFG)
    assert mock_env["retrieve_calls"] == 0
    assert res.segments[0].kind == "decline" and "asesoramiento" in res.reply_text
    assert res.route.action == "draft_ready"


def test_invented_number_routes_to_specialist(mock_env):
    mock_env["draft"] = Draft(abstain=False, abstain_reason="", agent_note="", segments=[
        Segment(text="Withdrawals arrive within 2 days.", kind="claim",
                citations=[Citation(chunk_id=CHUNK.id, quote="The minimum deposit starts from 8 USD")]),
    ])
    res = pipeline.triage("How long do withdrawals take?", CFG)
    assert res.route.action == "specialist_review" and "ungrounded_draft" in res.route.reasons
