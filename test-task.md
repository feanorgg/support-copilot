Overview

Build a support-ticket co-pilot for a retail forex/CFD broker, measure it, and make the business case for running it, in two phases: ship fast, then scale.

Timebox: 3–5 hours. Mocks and stubs are fine where you explain what the real version would do.

Submit: a link to your Git repository.

Next step: a 60-minute technical call where you walk us through your decisions.

Scenario

The support team answers repetitive questions about deposits, withdrawals, account opening and verification. Your co-pilot processes each incoming ticket and must:

Classify it: category, urgency, language, sentiment.

Draft a reply grounded in the knowledge base, with citations to the pages used, or abstain when the knowledge base does not cover it.

Route to a human reviewer whenever required.

Two phases

Phase 1 — Ship ASAP: get the co-pilot running for support agents as soon as possible.

Phase 2 — Scale up: keep it working as ticket volume grows (around 10,000 tickets per month today) and the knowledge base and SOPs expand.

Rules and data

Hard rules for the co-pilot

Never give trading advice: no buy/sell recommendations, signals, price targets or leverage suggestions. Detect these requests and decline politely.

Never decide a complaint, KYC or AML outcome. Draft and route to a person.

Never invent policy, fees or timelines. Cite the knowledge base or say it is unknown.

Data

Knowledge base: four public Valetax help pages — 
How to deposit, 
How to withdraw, 
How to open an account, 
How to verify account. Use them as they are, including gaps, overlaps and inconsistencies.

Constraints

Python preferred; any LLM provider. Build it with Claude Code or another agentic coding tool.

A minimal CLI or simple web page is enough for any UI.

Business case in numbers

The business case must answer one question on one page: is this worth running at our volume, and with which configuration?
