# Is the support co-pilot worth running at 10,000 tickets/month?

**Yes. Run `haiku_two_call`** (Claude Haiku 5.5 classifies and drafts). It frees **≈454 agent-hours a month** for **≈$7 of LLM spend**: net **≈$3,183/month**, the ≈$6,000 build pays back in **1.9 months**.

## Why it pays

| Per month | |
|---|---|
| Agent time saved (454 h at $8/h) | $3,630 |
| LLM ($0.71 per 1,000 tickets) | −$7 |
| Hosting + 10 engineer-hours of upkeep | −$440 |
| **Net** | **$3,183** |

- The saving comes from the repetitive half of traffic: a send-ready draft cuts a 6-minute ticket to 1.5 minutes of review. Complaints, KYC/AML and out-of-KB tickets still go to people; there the co-pilot only saves triage.
- It stays clearly positive under stress: if agents cost $5/h, net is still **$1,821/month**. Break-even is ≈1,215 tickets/month, so at today's volume the margin is wide and it grows linearly with volume.
- LLM cost is noise: even at the 4.5× gateway overbilling we observed it is 0.9% of the time saved.

## Why this configuration

| Config | Safe¹ | Send-ready drafts² | $/ticket | Net/month |
|---|---|---|---|---|
| `flashlite_cls_haiku_draft` | yes | 82% | $0.0005 | $3,026 |
| `haiku_cls_sonnet_draft`³ | yes | 86% | $0.0101 | $2,970 |
| `haiku_single_call` | yes | 68% | $0.0007 | $2,973 |
| **`haiku_two_call`** | yes | 89% | $0.0007 | $3,183 |

All four are safe, so the choice is draft quality per dollar. `haiku_two_call` has the most send-ready drafts and the highest net. Sonnet drafts are not better here and cost 14× more. Single-call costs the same but abstains on out-of-KB questions only 31% of the time (vs 67%), so agents get more drafts that don't answer the question.

¹ 100% of complaint/KYC/AML/urgent tickets routed to a human, 100% of trading-advice requests declined, 0 hard-rule violations (62 hand-labelled tickets). ² Rated ≥4/5 on groundedness and helpfulness by a judge that is stricter than a Sonnet judge. ³ Out-of-KB tickets not measured (gateway spend limit hit mid-run); outcomes borrowed from `haiku_two_call`.

## What would change the answer

Inputs marked as assumptions in `eval/assumptions.yaml` (ticket mix, handle times, $8/h agent cost) should be replaced with helpdesk data before go-live; the eval set is synthetic. The cheapest further gain is content, not model: ≈30% of tickets ask about fees, payment methods and withdrawal timelines that the four help pages don't cover.
