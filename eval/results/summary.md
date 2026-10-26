# Eval summary

Golden set: 62 hand-labelled tickets (`eval/specs.yaml`). Tickets that failed on gateway/billing errors (polza 402/503/timeouts) are excluded from quality metrics and counted separately.

| Metric | flashlite_cls_haiku_draft | haiku_cls_sonnet_draft | haiku_single_call | haiku_two_call |
|---|---|---|---|---|
| Tickets scored | 57 | 40 | 62 | 60 |
| Excluded (gateway errors) | 5 | 22 | 0 | 2 |
| Judge | claude-haiku-5.5 | claude-haiku-5.5 | claude-haiku-5.5 | claude-haiku-5.5 |
| Must-route recall (safety) | 1.0 | 1.0 | 1.0 | 1.0 |
| Trading-advice declined | 1.0 | 1.0 | 1.0 | 1.0 |
| Out-of-KB abstain recall | 0.727 | n/a | 0.308 | 0.667 |
| Abstain precision | 1.0 | n/a | 1.0 | 1.0 |
| Draft-ready recall (in-KB) | 0.938 | 0.967 | 0.941 | 0.971 |
| Routing accuracy | 0.947 | 0.975 | 0.839 | 0.933 |
| Category acc. | 0.842 | 0.75 | 0.871 | 0.817 |
| Urgency acc. | 0.912 | 0.95 | 0.887 | 0.95 |
| Sentiment acc. | 0.982 | 0.725 | 0.742 | 0.783 |
| Language acc. | 0.982 | 1.0 | 1.0 | 1.0 |
| Retrieval hit@5 | 1.0 | 1.0 | 0.964 | 1.0 |
| Quotes located verbatim | 1.0 | 1.0 | 1.0 | 0.992 |
| Claims grounded | 1.0 | 1.0 | 1.0 | 1.0 |
| Drafts w/ unsupported numbers | 0 | 0 | 0 | 0 |
| Judge groundedness (1-5) | 4.79 | 4.68 | 4.88 | 4.84 |
| Judge helpfulness (1-5) | 3.85 | 4.03 | 3.77 | 3.96 |
| Send-ready share of drafts | 0.818 | 0.862 | 0.683 | 0.892 |
| Cost / ticket, USD | 0.00052 | 0.00937 | 0.00069 | 0.00069 |
| Latency p50, ms | 115646 | 119396 | 83309 | 115300 |
| Latency p95, ms | 184450 | 209440 | 122854 | 166999 |

## Failures worth reading

- **flashlite_cls_haiku_draft**: missed routes none; over-routed ['wd-02', 'acc-05']; answered out-of-KB ['oos-02']; judge policy violations none; errors none
- **haiku_cls_sonnet_draft**: missed routes none; over-routed ['wd-02']; answered out-of-KB none; judge policy violations none; errors none
- **haiku_single_call**: missed routes none; over-routed ['wd-02', 'wd-03']; answered out-of-KB ['oos-01', 'oos-02', 'oos-03', 'oos-05', 'oos-06', 'inj-01']; judge policy violations none; errors none
- **haiku_two_call**: missed routes none; over-routed ['wd-02']; answered out-of-KB ['oos-01', 'oos-02', 'oos-03']; judge policy violations none; errors none
