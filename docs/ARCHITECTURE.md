# Architecture

## Phase 1: ship ASAP (this repo)

```
ticket
  │
  ├─ pre-guard (regex, 8 languages) ─ trading-advice / complaint / KYC-AML hits, OR-ed with LLM flags
  │
  ├─ classify (LLM, strict JSON schema) ─ category · urgency · language · sentiment
  │                                       · flags · English search query · one-line summary
  │      └─ pure trading-advice request? ──► localized decline template (no retrieval, no 2nd call)
  │
  ├─ retrieve (text-embedding-3-small, cosine, top-5, min score 0.30) over 20 KB chunks
  │      └─ nothing above threshold? ──► abstain (no drafting call)
  │
  ├─ draft (LLM, strict JSON schema) ─ ordered segments: claim | boilerplate | unknown | decline | handoff
  │                                     every claim carries {chunk_id, verbatim quote}
  │
  ├─ grounding (deterministic) ─ locate each quote in its chunk (exact → fuzzy ≥ 90) → char offsets
  │                               claim without a located quote → unsupported
  │                               number not in cited source / ticket → numeric_mismatch
  │                               trading advice / KYC-outcome phrasing → forbidden
  │
  └─ router (deterministic, fail-closed) ─► draft_ready | specialist_review | abstain (+ reasons)
```

| Decision | Why |
|---|---|
| **Two LLM calls** (classify → draft) as the default | The classifier's English `search_query` makes retrieval language-independent; pure advice requests and out-of-KB tickets skip the drafting call. `single_call` is kept as a config to measure the trade-off. |
| **Verbatim quotes, verified in code** | The agent needs to trust the draft in seconds. A quote that cannot be found in the source is visible (red marker) and blocks `draft_ready`. This turns "never invent policy" from a prompt wish into a check. |
| **Numbers check** | Fees, limits and timelines are where invented content does damage. Every digit run in a draft must appear in the cited chunks or the ticket (non-ASCII digits are normalized). |
| **Deterministic router** | Routing rules are auditable and testable. LLM flags are OR-ed with regex hits: we buy recall on must-route cases with some extra human looks. Any exception → `specialist_review`. |
| **In-memory index** | 20 chunks. A vector DB would be ceremony. `data/index` is committed so the demo starts without re-embedding. |
| **Strict JSON schema** (`response_format: json_schema, strict`) | No parsing heuristics; one retry with the validation error, then fail closed. |
| **polza.ai gateway, official providers only** | One key for Anthropic/Google/OpenAI models and embeddings. `claude-sonnet-5.5` is only offered through an *unofficial* provider without structured output on polza, so `claude-sonnet-5` is used for the comparison. Customer PII should not go to unofficial resellers. |
| **Human in the loop for everything** | It is a co-pilot: `draft_ready` still means "an agent reviews and sends". Nothing is sent to customers automatically. |

### What is mocked / simplified
- No helpdesk integration (Zendesk/Freshdesk webhook → `POST /api/triage` → internal note). The API shape is ready for it.
- No customer/account context: questions needing a back-office lookup are answered generically, with the lookup left to the agent (`agent_note`).
- Eval tickets are synthetic (LLM-written text, hand-written labels). Real tickets would replace them.
- Decline templates cover 11 languages; others fall back to English with an agent note.

## Phase 2: scale up (10k → 30k+ tickets/month, KB and SOPs growing)

Volume is not the hard part: 10k tickets/month is ≈14 tickets/hour on average. The hard parts
are **knowledge growth, regressions, and cost per useful draft**.

| Area | Phase 2 change | Trigger |
|---|---|---|
| **Knowledge** | Ingest pipeline for help pages + internal SOPs + macros: source type, language, version, effective date, owner, audience (customer-facing vs internal-only). SOPs are *instructions to the agent* and must never be quoted to customers: separate index or `audience` filter. | Any new source |
| **Retrieval** | pgvector (already Postgres in most helpdesk stacks) or Qdrant; hybrid BM25 + dense (payment method names, "USDT TRC20" are lexical); reranker on top-20; metadata filters (product, region, account type). | > ~500 chunks or hit@5 drops in eval |
| **Freshness** | Scheduled re-scrape with content hashes → re-embed only changed chunks; KB version stamped on every draft so an answer can be traced to the text that was live. | Daily |
| **Conflicts** | When retrieved chunks disagree, surface both to the agent and open a KB ticket automatically (see `docs/KB_ISSUES.md`). | Always |
| **Throughput** | Webhook → queue (SQS/Redis) → stateless workers; drafts written back as internal notes. Batch API for non-urgent backlogs. Per-tenant rate limits and a circuit breaker to a "no co-pilot" mode. | > 1 req/s or gateway instability |
| **Cost** | Prompt caching of the static system prompt; classifier distilled to a small model or fine-tuned embedding classifier trained on accumulated (LLM label → agent correction) data; Sonnet only as a fallback for low-confidence drafts. | Once LLM spend matters (it does not at 10k) |
| **Quality loop** | Log agent edits (draft vs sent), routing overrides and abstain topics; weekly review; eval set grows from real tickets; eval runs in CI as a regression gate (must-route recall = 100% blocks a release). | Continuous |
| **Observability** | Traces per ticket (Langfuse/OpenTelemetry): retrieval scores, citations, grounding failures, cost, latency; dashboards on abstain rate, send-ready rate, routing mix by language. | From day 1 of Phase 2 |
| **Gateway** | During this build polza.ai showed 20–60 s latency and intermittent 503s. For production: direct provider contracts (Anthropic/Bedrock/Vertex) with a gateway only as fallback, and data-processing agreements for customer PII. | Before go-live |
| **Security** | PII redaction before logging; prompt-injection tests in eval (`inj-*`); outputs never trigger actions, they are drafts. | Before go-live |
