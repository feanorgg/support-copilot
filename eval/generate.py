"""Generate ticket texts for eval/specs.yaml. Labels come from the spec, not from the model."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.config import EVAL_DIR, GEN_MODEL
from app.llm import LLMError, chat_json

SPECS_PATH = Path(__file__).parent / "specs.yaml"
TICKETS_PATH = EVAL_DIR / "tickets.jsonl"

GEN_SYSTEM = """\
You write realistic inbound customer-support messages for a retail forex/CFD broker called
Valetax, used to test a support assistant. Write as the customer, in the requested language,
as a chat or email message of 1-5 sentences. Vary style: some short and informal, some with
typos, some with greetings/sign-offs, sometimes an account number or amount. Match the
requested tone. Do not mention test labels, categories or the assistant. Output only the
message in the `text` field."""


class GeneratedTicket(BaseModel):
    text: str


def load_specs() -> list[dict]:
    raw = yaml.safe_load(SPECS_PATH.read_text(encoding="utf-8"))
    return [{**raw["defaults"], **t} for t in raw["tickets"]]


def load_tickets() -> list[dict]:
    if not TICKETS_PATH.exists():
        return []
    return [json.loads(line) for line in TICKETS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_one(spec: dict) -> dict | None:
    tone = {"negative": "frustrated/angry", "positive": "friendly", "neutral": "neutral"}[spec["sentiment"]]
    user = (
        f"Scenario: {spec['scenario']}\nLanguage (ISO 639-1): {spec['language']}\n"
        f"Tone: {tone}. Urgency felt by the customer: {spec['urgency']}."
    )
    try:
        out, _ = chat_json(stage="generate", model=GEN_MODEL, system=GEN_SYSTEM, user=user, schema=GeneratedTicket,
                           temperature=0.9, max_tokens=500)
    except LLMError as exc:  # flaky gateway: skip, a rerun fills the gaps
        print(f"{spec['id']}: FAILED {exc}")
        return None
    return {**spec, "text": out.text.strip()}


def generate(force: bool = False, workers: int = 8) -> list[dict]:
    specs = load_specs()
    existing = {t["id"]: t for t in load_tickets()}
    todo = [s for s in specs if force or s["id"] not in existing]
    with ThreadPoolExecutor(workers) as pool:
        for row in pool.map(_write_one, todo):
            if row is None:
                continue
            existing[row["id"]] = row
            print(f"{row['id']}: {row['text'][:90]}")
    # keep spec order; labels always refreshed from the spec so hand edits to specs.yaml apply
    rows = [{**s, "text": existing[s["id"]]["text"]} for s in specs if s["id"] in existing]
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    TICKETS_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return rows
