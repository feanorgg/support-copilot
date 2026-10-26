# Valetax support co-pilot

A co-pilot for support agents at a retail forex/CFD broker. For each incoming ticket it:

1. **classifies** it: category, urgency, language, sentiment, plus trading-advice / complaint / KYC-AML flags;
2. **drafts a reply grounded in the help center** where every factual sentence carries a *verbatim quote* from the source, verified in code and highlighted in the UI. If the help pages don't cover the question, it **abstains**;
3. **routes** the ticket: `draft_ready` (agent reviews and sends), `specialist_review` (complaints, KYC/AML, urgent, unsafe or ungrounded draft, any failure), or `abstain` (agent answers manually).

Knowledge base: the four public Valetax help pages (deposit, withdraw, open account, verify), used as they are, gaps and contradictions included ([docs/KB_ISSUES.md](docs/KB_ISSUES.md)).

| Document | What's in it |
|---|---|
| [docs/BUSINESS_CASE.md](docs/BUSINESS_CASE.md) | **One page: is it worth running at 10k tickets/month, and with which configuration** |
| [eval/results/summary.md](eval/results/summary.md) | Eval results for 4 configurations on 62 hand-labelled tickets |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Phase 1 design decisions, what is mocked, Phase 2 scale-up plan |
| [docs/KB_ISSUES.md](docs/KB_ISSUES.md) | Overlaps, inconsistencies and gaps found in the help pages, and how each is handled |

## Quick start

```bash
cp .env.example .env          # set POLZA_API_KEY (polza.ai, OpenAI-compatible gateway)
docker compose up --build     # → http://localhost:8000
```

Without Docker:

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.api:app --port 8000
```

The KB snapshot and the vector index are committed, so the app starts without scraping or re-embedding.

### CLI

```bash
python -m app.cli triage "What's the minimum deposit and how long until it shows up?"
python -m app.cli triage "Should I buy gold today?" --config haiku_single_call --json
python -m app.cli scrape            # re-fetch the 4 pages into data/kb (snapshot)
python -m app.cli index             # chunk + embed into data/index
python -m app.cli generate-eval     # LLM writes ticket texts for eval/specs.yaml (labels are hand-written)
python -m app.cli eval              # all configs → eval/results/ (+ summary.md)
python -m app.cli calibrate-judge   # Haiku judge vs Sonnet judge on the same drafts
python -m app.cli business-case     # → docs/BUSINESS_CASE.md
pytest                              # deterministic parts + pipeline with a mocked LLM
```

In Docker: `docker compose run --rm app python -m app.cli <command>`.

## The agent UI

Three panes: **ticket** (classification badges, routing decision with reasons, cost/latency per call) · **draft** (each sentence underlined by grounding status, `[n]` markers per source) · **sources** (the cited help-center excerpt with the quoted span highlighted; a link opens the Valetax page scrolled to that exact text via a text fragment; retrieved-but-unused excerpts are listed under them). "Copy clean reply" copies the text without markers.

Marker colours: green = quote found verbatim, amber = near-verbatim (fuzzy ≥ 90, e.g. the model fixed a typo in the source), red `!` = quote not found in the source, which blocks `draft_ready`.

## How it works

```
ticket → pre-guard (regex) → classify (LLM, JSON schema) → retrieve (embeddings, top-5)
       → draft (LLM, segments + verbatim quotes) → grounding checks (code) → router (code)
```

- **Two calls by default.** The classifier also writes an English search query, so retrieval works for Arabic/Thai/Hindi tickets. Pure trading-advice requests get a localized decline template, and tickets with nothing relevant in the KB abstain without a drafting call.
- **"Never invent policy" is a check, not just a prompt line.** Every claim needs a quote that is found in the cited chunk. Every number in the draft must appear in the cited sources or in the ticket itself (Arabic-Indic and other digits are normalized). A violation routes the ticket to a specialist.
- **Fail closed.** Any LLM/gateway error, invalid JSON after one retry, or guard hit → `specialist_review`. Regex pre-guards are OR-ed with the LLM flags: some recall on must-route cases is bought with extra human looks.
- **Hard rules** (no trading advice, never decide complaint/KYC/AML outcomes, never invent fees/timelines) live in one place ([app/prompts.py](app/prompts.py)) and are enforced again on the output ([app/guardrails.py](app/guardrails.py)).

## Configurations compared

| Config | Mode | Classify | Draft |
|---|---|---|---|
| `haiku_two_call` | classify → draft | Claude Haiku 5.5 | Claude Haiku 5.5 |
| `haiku_single_call` | one call | — | Claude Haiku 5.5 |
| `haiku_cls_sonnet_draft` | classify → draft | Claude Haiku 5.5 | Claude Sonnet 5 |
| `flashlite_cls_haiku_draft` | classify → draft | Gemini 2.5 Flash-Lite | Claude Haiku 5.5 |

Embeddings: `openai/text-embedding-3-small`. Judge: Claude Haiku 5.5, calibrated against a Claude Sonnet 5 judge on the same drafts ([eval/results/calibration/](eval/results/calibration/)).

## Eval method

- 62 tickets in 11 languages ([eval/specs.yaml](eval/specs.yaml)). **Labels are hand-written per scenario**; an LLM only writes the ticket text, so the labels don't depend on the models under test. The set over-weights hard cases (complaints, KYC, trading advice, out-of-KB, prompt injection) on purpose; the business case re-weights results by an assumed production mix.
- Metrics: must-route recall (the safety metric), advice-decline rate, abstain precision/recall, routing accuracy, per-field classification accuracy, retrieval hit@5, quote-located rate, claim-grounded rate, drafts with unsupported numbers, LLM-judge groundedness/helpfulness, cost/ticket, latency.

## Limitations

- **Synthetic tickets**: real ticket exports would replace them; the label set is small (62), so differences of one or two tickets between configs are noise.
- **Gateway latency**: during the build polza.ai answered in 20–60 s per call with intermittent 503s. Measured latency (p50 > 2 min/ticket) reflects the gateway, not the models (see ARCHITECTURE → Phase 2 → Gateway).
- No helpdesk integration or customer/account context; account-specific questions get a generic answer plus an `agent_note` on what to check.
- Spelled-out numbers ("twenty-four hours") are not caught by the numeric check; the LLM judge covers them in eval.
- Docker files are provided but were not built on the development machine (no Docker available there); the app was run from a local venv.
