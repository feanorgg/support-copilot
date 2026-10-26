# Knowledge-base issues (snapshot 2026-10-26)

The four help pages are used as they are. Below is what we found while snapshotting them and
how the co-pilot handles each issue. Eval tickets that exercise an issue are listed in brackets
(ids from `eval/specs.yaml`).

## Overlaps

| # | Issue | Handling |
|---|---|---|
| O1 | **How to Withdraw duplicates How to Deposit.** Its 9 FAQ items are character-for-character the deposit FAQ ("Got a question on Depositing and Withdrawing funds?"). | Chunker merges identical Q&A into one chunk listing both pages (`pages`, `urls`), so duplicates don't crowd the top-k and the UI links to both pages. 20 unique chunks instead of 29. |
| O2 | Document requirements live only on *How to Open an Account*, not on *How to Verify Account*. | Retrieval is cross-page; verification questions retrieve the open-account FAQ [ver-02, acc-05]. |

## Inconsistencies

| # | Issue | Handling |
|---|---|---|
| I1 | **Withdraw page steps are deposit steps**: "Enter your account details and amount to *deposit*", "Start Trading!". | The `withdraw#steps` chunk is kept verbatim (we don't edit the source). Drafts that cite it are what an agent should double-check; flagged in the prompt's conflict rule [wd-04]. |
| I2 | "Deposits are instant!" vs "You will be able to view your updated account balance within 60 minutes." (same answer). | Prompt rule: state the more conservative version, cite it, add an `agent_note` about the conflict [dep-03, dep-08]. |
| I3 | "Opening a live account allows you to begin trading immediately" vs "Account opening and document verification will be completed within 48 hours." | Same conservative-plus-note rule [acc-06]. |
| I4 | Minimum deposit: "starts from 8 USD, depending on the account type" (deposit FAQ) vs "It will depend on the account type… view details here" (open-account FAQ, no number, links to a page outside the KB). | Both chunks retrievable; the number is citable only from the deposit FAQ [dep-01, dep-07, acc-07]. |
| I5 | Withdraw page intro says withdrawals are "easy and instant", while the FAQ talks about a 'pending' queue, approvals, and "within 24 hours". | No timeline is stated; the co-pilot must not promise "instant" [wd-01, wd-03, oos-03]. |
| I6 | Typos in source text ("insifficient", "request in in queue", "no swap is credited"). | Quotes must be verbatim, so the model must copy typos; a fuzzy match (≥ 90) tolerates the model "fixing" them and is shown amber in the UI. |

## Gaps (not covered: the co-pilot must say "unknown", not invent)

- **Fees** for deposits or withdrawals: not mentioned anywhere [oos-01].
- **Payment methods**: none are named (cards, bank wire, e-wallets, crypto) [oos-02, oos-09, oos-11].
- **Withdrawal processing time**: only "if not received within 24 hours, contact support" [oos-03].
- **Verification**: no timeline on the verify page, no reasons for rejection, no list of accepted documents beyond "proof of identification and proof of address" [kyc-*].
- Account types, spreads, platforms (MT4/MT5), password reset, bonuses, IB/partners, regulation, country restrictions: all referenced or linked ("here") but outside the KB [oos-04 … oos-12].
- Step screenshots carry information as images (`deposit-screen-step-2.webp` …) that is not in the text.

## Hard-rule tension inside the KB

- *"What leverage settings should I select?"* is an FAQ item. It states a fact ("we offer up to 1:2000 depending on account types") and defers the choice to the client's strategy. The co-pilot may quote the maximum as a fact [acc-08] but must decline "which leverage should I use" [adv-02, mix-02]. `guardrails.output_violations` blocks "we recommend … leverage / 1:N" phrasing in drafts.

## What the real fix is (Phase 2)

These are content problems, not model problems. The co-pilot's `agent_note` and abstain logs
should feed a weekly KB-gap report to the content owner (top abstained topics, conflicting
chunks cited); the fastest win is a real withdrawal page with methods, fees and timelines.
