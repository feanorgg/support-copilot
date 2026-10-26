# CLAUDE.md

Support-ticket co-pilot for a retail forex/CFD broker (Valetax test task for an AI-engineer role).
Classifies a ticket, drafts a reply grounded in 4 help pages with verbatim, code-verified quotes
(or abstains), and routes to a human when required. Python 3.11, FastAPI, polza.ai as the LLM gateway.

## Commands

```bash
.venv/bin/python -m pytest -q                      # deterministic parts + mocked pipeline; no API key needed
.venv/bin/uvicorn app.api:app --port 8000          # UI at /, API at POST /api/triage
.venv/bin/python -m app.cli triage "<ticket>" [--config NAME] [--json]
.venv/bin/python -m app.cli scrape [--offline]     # refresh data/kb snapshot (--offline re-parses committed HTML)
.venv/bin/python -m app.cli index                  # rebuild data/index (needs key; ~0.003 RUB)
.venv/bin/python -m app.cli generate-eval          # fill missing ticket texts for eval/specs.yaml
.venv/bin/python -m app.cli eval [--config NAME]... [--limit N] [--workers N]
.venv/bin/python -m app.cli calibrate-judge        # Haiku judge vs Sonnet judge on frozen drafts
.venv/bin/python -m app.cli business-case          # writes docs/BUSINESS_CASE.md from eval/results + eval/assumptions.yaml
docker compose up --build                          # same app on :8000 (reads .env)
```

`.env` holds `POLZA_API_KEY` (never commit it). Run Python from the repo root (modules import as `app.*`, `eval.*`).

## Layout and data flow

`app/pipeline.py::triage` is the entry point:
pre-guard (`app/guardrails.py::pre_screen`) → classify (`Classification`) → retrieve (`app/retrieval.py`)
→ draft (`Draft`: ordered segments) → `app/grounding.py::ground_segments` → `app/router.py::route` → `TriageResult`.

- `app/schemas.py`: every LLM output contract and result model. LLM schemas are sent as strict JSON schema (`app/llm.py::strict_schema`): no `ge/le`/defaults, every field required.
- `app/prompts.py`: all prompts, `HARD_RULES` (shared by every mode and the judge), localized `DECLINE_TEMPLATES`.
- `app/config.py`: model ids, RUB prices, `RUB_PER_USD`, thresholds, the `CONFIGS` registry (pipeline configurations compared in eval).
- `app/kb/`: scrape → chunk (1 FAQ item = 1 chunk, identical Q&A across pages merged) → index (`data/index/*`, committed).
- `eval/`: `specs.yaml` (hand-written labels), `generate.py`, `run_eval.py` (metrics, rejudge, judge calibration), `judge.py`, `business_case.py`, `assumptions.yaml`.
- `docs/`: `ARCHITECTURE.md`, `KB_ISSUES.md`, `BUSINESS_CASE.md` (generated, don't hand-edit; change the generator or assumptions).

## Invariants: do not break

1. **Fail closed.** Any exception in triage (LLM, embeddings, invalid JSON after one retry) ends in `specialist_review`, with the partial state (e.g. classification) preserved via `_State`.
2. **Claims need verbatim quotes.** A `claim` segment is `grounded` only if a quote is located in a chunk *that was passed to the model*. Don't loosen `FUZZY_MIN_SCORE` (90) or let unknown chunk ids pass.
3. **No unsupported numbers.** Digits in a claim must appear in its own cited chunks or the ticket; non-claim segments may reuse numbers from any chunk cited in the same reply.
4. **Hard rules are enforced twice**: in prompts and in `guardrails.output_violations`. Pre-guard flags are OR-ed with LLM flags (recall over precision for complaints/KYC/advice).
5. **Router precedence**: specialist_review > abstain > draft_ready. A draft with no `claim` and no `decline` is `abstain` (holding reply only).
6. **Eval labels come from `eval/specs.yaml`, never from model output.** Don't relabel a ticket to match a result; if a label is genuinely ambiguous, add `acceptable_actions` and say why.

## Common changes

- **New KB page**: add it to `KB_PAGES` (+ a short name in `app/kb/chunk.py::PAGE_SHORT`), `cli scrape`, `cli index`, check chunk ids stay unique, add eval specs that need it.
- **New pipeline config**: add a `PipelineConfig` to `CONFIGS` (and prices to `PRICES_RUB_PER_M`), then `cli eval --config NAME` and `cli business-case`.
- **Prompt change**: re-run eval for all configs you compare (drafts change); router/guardrail-only changes are deterministic, so `pytest` + a spot-check is enough.
- After changing routing or grounding rules, add a test in `tests/test_deterministic.py`.

## polza.ai specifics

- Base URL `https://polza.ai/api/v1`, OpenAI SDK compatible; chat + `/embeddings`; cost comes back in `usage.cost_rub` (RUB).
- `response_format: json_schema, strict` works for Haiku 5.5, Sonnet 5, Gemini 2.5 Flash-Lite. `claude-sonnet-5.5` is only offered via an *unofficial* provider without structured output, so don't use it.
- `provider.require_parameters` together with `temperature` + `reasoning: {effort: "none"}` returns 400; it is intentionally not sent.
- The gateway can take 20–60 s+ per call and returns transient 503 `limitsCheckUnavailable`. The client uses a 300 s timeout and few SDK retries, because short timeouts resend still-running (billed) requests. 503 is retried with waits in `_create_with_gateway_retry`.
- The key has a **daily RUB limit** (`GET /api/v1/key`, `app.llm.key_budget`); `cli eval` checks it first. A request reserves ~1 RUB up front, so 402 appears before the limit is literally zero. Keep eval `--workers` ≤ 4.

## Known limitations

Synthetic eval tickets (62); no helpdesk integration or account context; spelled-out numbers escape the numeric check;
Docker image was not built on the dev machine (no Docker there); latency numbers reflect the gateway, not the models.
