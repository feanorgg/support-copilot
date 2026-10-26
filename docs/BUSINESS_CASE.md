# Business case: is the co-pilot worth running at 10k tickets/month?

**Yes.** Run **`haiku_two_call`** (two-call: classify with `anthropic/claude-haiku-5.5`, draft with `anthropic/claude-haiku-5.5`). It saves an estimated **454 agent-hours/month (≈$3,630)** for **$7/month of LLM spend** and $440/month to run it: **net ≈$3,183/month**, payback of the $6,000 build in **1.9 months**. Break-even is ≈1,215 tickets/month.

LLM cost is ≈$0.0007/ticket, a rounding error next to agent time, so **the choice of configuration is driven by safety and draft quality, not by token price.** On the golden set it routed 100% of must-route tickets (complaints, KYC/AML, urgent) to a human, declined 100% of trading-advice requests, and 99% of its citations were found verbatim in the KB.

## Configurations compared (measured on the golden set, re-weighted to the production mix)

| Config | Tickets scored | Safety gate | Send-ready drafts | Judge ground./help. | LLM $/ticket | LLM $/month | Agent hours saved | Net $/month |
|---|---|---|---|---|---|---|---|---|
| `flashlite_cls_haiku_draft` | 57/62 | pass (must-route 100%, advice declined 100%, violations 0) | 82% of 33 | 4.79 / 3.85 | $0.0005 | $5 | 434 | $3,026 |
| `haiku_cls_sonnet_draft` | 40/62 * | pass (must-route 100%, advice declined 100%, violations 0) | 86% of 29 | 4.68 / 4.03 | $0.0101 | $101 | 439 | $2,970 |
| `haiku_single_call` | 62/62 | pass (must-route 100%, advice declined 100%, violations 0) | 68% of 41 | 4.88 / 3.77 | $0.0007 | $7 | 427 | $2,973 |
| `haiku_two_call` ✅ | 60/62 | pass (must-route 100%, advice declined 100%, violations 0) | 89% of 37 | 4.84 / 3.96 | $0.0007 | $7 | 454 | $3,183 |

\* `haiku_cls_sonnet_draft`: segment(s) out_of_kb not measured (the gateway's daily spend limit ran out mid-run); routing outcomes borrowed from `haiku_two_call` (same classifier and retrieval), cost is the config's own average.

Tickets that failed on gateway/billing errors are excluded per config; `eval/results/summary.md` has the full metric table.

## Sensitivity (recommended config)

| Scenario | Hours saved | Net $/month |
|---|---|---|
| Base case | 454 | $3,183 |
| Agents accept only half the send-ready drafts | 330 | $2,193 |
| Agent cost $5/h (instead of $8) | 454 | $1,821 |
| Agent cost $15/h | 454 | $6,358 |
| Baseline handle times 30% shorter | 289 | $1,861 |
| Volume x3 (30k tickets/month) | 1,361 | $10,428 |

## How the number is built

- **Measured** (eval, 60 hand-labelled tickets): routing action per ticket, judge scores, cost per ticket from polza.ai billing (`usage.cost_rub` at 116.957 RUB/USD).
- **Assumed** (`eval/assumptions.yaml`, to replace with helpdesk data): 10,000 tickets/month; agent $8.0/h; production mix in_kb 50%, trading_advice 5%, complaint 8%, kyc_aml 7%, out_of_kb 30%; baseline handle times in_kb 6 min, trading_advice 4 min, complaint 15 min, kyc_aml 12 min, out_of_kb 8 min; send-ready draft 1.5 min, edited draft 70% of baseline, triage saves 0.3 min/ticket.
- Minutes saved per ticket by segment: in_kb 4.5 min, trading_advice 2.5 min, complaint 0.3 min, kyc_aml 0.3 min, out_of_kb 1.1 min. Routed and abstained tickets save only triage time: the co-pilot earns its keep on the repetitive in-KB half.
- Running cost: hosting $40 + 10 engineer-hours/month at $40/h.
- Not counted (upside): faster first response, 24/7 drafting, consistent routing of complaints/KYC, KB-gap reports. Not counted (risk): a wrong answer about money; mitigated by human review of every draft, verbatim-quote checks and fail-closed routing.
- **Gateway billing risk:** during eval, polza.ai debited ≈4.5× the sum of per-request `usage.cost_rub` (likely retries/reservations under its 503s; to verify in its transaction log). Even at 4.5× the LLM bill is 0.9% of the agent time saved, so the verdict holds; it is a reason to buy model access directly for production (see ARCHITECTURE → Gateway).

## Biggest lever is content, not model

An assumed 30% of traffic (fees, payment methods, withdrawal timelines, platform) is simply not in the four pages (see `docs/KB_ISSUES.md`). Every topic added to the KB moves its tickets from 'abstain' (≈0.05 min saved) to 'send-ready draft' (≈4.8 min saved). Writing a real withdrawal page (methods, fees, timelines) is worth more than any model upgrade. Open issue: 3 out-of-KB ticket(s) (oos-01, oos-02, oos-03) got an honest partial draft ("not covered, an agent will confirm" plus adjacent cited facts) instead of abstaining; nothing was invented, but the main question stays unanswered. Fix: the drafter states `answers_main_question`, and the router abstains when it is false.
