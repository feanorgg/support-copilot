from app.grounding import ground_segments, locate_quote, numbers_in
from app.guardrails import output_violations, pre_screen
from app.kb.chunk import build_chunks
from app.kb.scrape import load_pages
from app.router import route
from app.schemas import Chunk, Citation, Classification, Segment

CHUNK = Chunk(
    id="deposit#faq-minimum-deposit-amount",
    kind="faq",
    section="What is the minimum deposit amount?",
    text="What is the minimum deposit amount?\nThe minimum deposit starts from 8 USD, depending on the account type.",
    pages=["how-to-deposit"],
    urls=["https://valetax.com/how-to-deposit/"],
    page_titles=["How to Deposit"],
)
CHUNKS = {CHUNK.id: CHUNK}


def _cls(**kw):
    base = dict(
        category="deposit", urgency="low", language="en", sentiment="neutral", trading_advice_request=False,
        complaint=False, kyc_aml_decision_request=False, has_supportable_question=True, search_query="q", summary="s",
    )
    return Classification(**{**base, **kw})


# ---------- quotes ----------

def test_exact_quote_offsets_point_into_original_text():
    status, score, start, end = locate_quote("the minimum deposit starts from 8 usd", CHUNK.text)
    assert status == "verified" and score == 100
    assert CHUNK.text[start:end] == "The minimum deposit starts from 8 USD"


def test_quote_normalises_whitespace_and_curly_quotes():
    text = "will follow that day’s   exchange rates."
    status, _, start, end = locate_quote("that day's exchange rates", text)
    assert status == "verified"
    assert text[start:end] == "that day’s   exchange rates"


def test_fuzzy_quote_tolerates_small_typo_fix():
    text = "insifficient margin to process withdrawals"
    status, score, *_ = locate_quote("insufficient margin to process withdrawals", text)
    assert status == "fuzzy" and score >= 90


def test_fabricated_quote_is_unverified():
    status, *_ = locate_quote("withdrawals are processed within 3 business days", CHUNK.text)
    assert status == "unverified"


def test_ellipsis_quote_requires_all_parts_in_order():
    assert locate_quote("The minimum deposit ... depending on the account type", CHUNK.text)[0] == "verified"
    assert locate_quote("depending on the account type ... The minimum deposit", CHUNK.text)[0] == "unverified"


def test_numbers_normalise_non_ascii_digits():
    assert numbers_in("خلال ٢٤ ساعة") == {"24"}
    assert numbers_in("up to 1:2000") == {"1", "2000"}


# ---------- segments ----------

def test_grounded_claim_and_numeric_mismatch():
    segs = [
        Segment(text="Hello!", kind="boilerplate", citations=[]),
        Segment(text="The minimum deposit is 8 USD.", kind="claim",
                citations=[Citation(chunk_id=CHUNK.id, quote="minimum deposit starts from 8 USD")]),
        Segment(text="The minimum deposit is 10 USD.", kind="claim",
                citations=[Citation(chunk_id=CHUNK.id, quote="minimum deposit starts from 8 USD")]),
    ]
    res, score = ground_segments(segs, CHUNKS, {CHUNK.id}, ticket="hi")
    assert [r.status for r in res] == ["not_required", "grounded", "numeric_mismatch"]
    assert score == 0.5
    assert res[1].citations[0].n == 1 and res[1].citations[0].start is not None


def test_claim_without_quote_or_with_unknown_chunk_is_unsupported():
    segs = [
        Segment(text="Withdrawals are free.", kind="claim", citations=[]),
        Segment(text="Deposits are instant.", kind="claim", citations=[Citation(chunk_id="made#up", quote="x y z")]),
    ]
    res, score = ground_segments(segs, CHUNKS, {CHUNK.id}, ticket="")
    assert [r.status for r in res] == ["unsupported", "unsupported"]
    assert res[1].citations[0].status == "unknown_chunk"
    assert score == 0.0


def test_numbers_from_ticket_are_allowed_but_not_in_handoff_otherwise():
    segs = [Segment(text="We see your deposit of 500 USD.", kind="handoff", citations=[])]
    assert ground_segments(segs, CHUNKS, set(), ticket="I deposited 500 USD")[0][0].status == "not_required"
    segs = [Segment(text="A specialist will reply within 24 hours.", kind="handoff", citations=[])]
    assert ground_segments(segs, CHUNKS, set(), ticket="help")[0][0].status == "numeric_mismatch"


# ---------- guardrails ----------

def test_pre_screen_multilingual():
    assert "trading_advice" in pre_screen("Should I buy gold now or wait?")
    assert "trading_advice" in pre_screen("¿Debo comprar o vender EURUSD?")
    assert "trading_advice" in pre_screen("купить или продать биткоин?")
    assert "complaint" in pre_screen("This is a scam, I will contact the regulator")
    assert "complaint" in pre_screen("هذا احتيال")
    assert "kyc_aml" in pre_screen("Why was my verification rejected?")
    assert pre_screen("What is the minimum deposit?") == {}


def test_output_violations():
    assert output_violations("We recommend you buy EURUSD now.")
    assert output_violations("Your account has been approved.")
    assert not output_violations("We offer up to 1:2000 depending on account types.")


# ---------- router ----------

def _route(**kw):
    base = dict(classification=_cls(), pre_flags={}, abstain=False, segments=[], grounding_score=None,
                min_grounding_score=1.0, errors=[])
    return route(**{**base, **kw})


def test_router_fail_closed_on_llm_failure():
    assert _route(classification=None, errors=["boom"]).action == "specialist_review"


def test_router_complaint_from_pre_guard_only():
    d = _route(pre_flags={"complaint": ["scam"]}, abstain=True)
    assert d.action == "specialist_review" and "complaint" in d.reasons


def test_router_abstain_and_draft_ready():
    assert _route(abstain=True).action == "abstain"
    segs, _ = ground_segments(
        [Segment(text="Min is 8 USD.", kind="claim", citations=[Citation(chunk_id=CHUNK.id, quote="starts from 8 USD")])],
        CHUNKS, {CHUNK.id}, "",
    )
    assert _route(segments=segs, grounding_score=1.0).action == "draft_ready"


def test_router_trading_advice_is_declined_not_escalated():
    from app.schemas import SegmentResult
    seg = SegmentResult(text="We can't advise.", kind="decline", citations=[], status="not_required")
    d = _route(classification=_cls(trading_advice_request=True, has_supportable_question=False), segments=[seg])
    assert d.action == "draft_ready" and "trading_advice_declined" in d.reasons


# ---------- KB ----------

def test_chunks_dedupe_withdraw_faq_into_deposit():
    chunks = build_chunks(load_pages())
    shared = [c for c in chunks if len(c.pages) > 1]
    assert shared, "withdraw page duplicates the deposit FAQ"
    assert all(set(c.pages) == {"how-to-deposit", "how-to-withdraw"} for c in shared)
    assert len({c.id for c in chunks}) == len(chunks)


def test_non_claim_may_reuse_numbers_cited_elsewhere_in_reply():
    segs = [
        Segment(text="The minimum deposit is 8 USD.", kind="claim",
                citations=[Citation(chunk_id=CHUNK.id, quote="minimum deposit starts from 8 USD")]),
        Segment(text="If you can't deposit 8 USD, reply and we'll check.", kind="unknown", citations=[]),
    ]
    res, _ = ground_segments(segs, CHUNKS, {CHUNK.id}, ticket="")
    assert [r.status for r in res] == ["grounded", "not_required"]


def test_conditional_process_description_is_not_an_outcome_decision():
    assert not output_violations("Once your account has been verified, you will be ready to trade.")
    assert output_violations("Good news: your account has been verified.")


def test_holding_reply_without_claims_is_abstain():
    from app.schemas import SegmentResult
    segs = [
        SegmentResult(text="Hello.", kind="boilerplate", citations=[], status="not_required"),
        SegmentResult(text="Our help pages don't cover fees; an agent will confirm.", kind="unknown", citations=[], status="not_required"),
    ]
    d = _route(segments=segs)
    assert d.action == "abstain" and "partial_answer" in d.reasons
