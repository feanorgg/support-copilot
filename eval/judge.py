"""LLM-as-judge for drafted replies (groundedness, helpfulness, hard-rule violations).

Default judge is Haiku 5.5 (cheap enough to run on every config). Its agreement with a Sonnet 5
judge on the same drafts is measured in eval/results/calibration/. Caveat: judges share a model
family with the drafters; compare configs relatively. Deterministic grounding checks are the
primary signal.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import JUDGE_MODEL
from app.llm import chat_json
from app.prompts import HARD_RULES
from app.schemas import LLMCall, TriageResult

JUDGE_SYSTEM = f"""\
You audit draft replies written by a support co-pilot for a forex/CFD broker. You get the
customer ticket, the knowledge-base excerpts the co-pilot was allowed to use, and the draft.

Score:
- groundedness 1-5: 5 = every factual statement is supported by the excerpts; 1 = key facts
  invented or contradicted. Generic courtesy and "we will check / not covered" statements do
  not count against groundedness.
- helpfulness 1-5: 5 = answers everything the excerpts allow, clear, correct language, a support
  agent could send it as-is; 1 = useless or wrong.
- invented_facts: list any fees, limits, timelines, methods or policies NOT in the excerpts.
- policy_violation: true if the draft breaks any hard rule below.

{HARD_RULES}"""


class JudgeVerdict(BaseModel):
    # no ge/le: min/max keywords are not supported by every provider's strict mode
    groundedness: int = Field(description="1-5")
    helpfulness: int = Field(description="1-5")
    invented_facts: list[str]
    policy_violation: bool
    rationale: str


def judge(res: TriageResult, model: str = JUDGE_MODEL) -> tuple[JudgeVerdict, LLMCall]:
    excerpts = "\n".join(f"<excerpt>\n{h.chunk.text}\n</excerpt>" for h in res.retrieved if h.passed_to_llm) or "(none)"
    user = f"<ticket>\n{res.ticket}\n</ticket>\n\n<excerpts>\n{excerpts}\n</excerpts>\n\n<draft>\n{res.reply_text}\n</draft>"
    return chat_json(stage="judge", model=model, system=JUDGE_SYSTEM, user=user, schema=JudgeVerdict, max_tokens=800)
