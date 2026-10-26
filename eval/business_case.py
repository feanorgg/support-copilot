"""One-page business case: eval results (measured) x eval/assumptions.yaml (assumed) -> docs/BUSINESS_CASE.md."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config import CONFIGS, ROOT, RUB_PER_USD
from eval.run_eval import load_results

ASSUMPTIONS = Path(__file__).parent / "assumptions.yaml"
OUT = ROOT / "docs" / "BUSINESS_CASE.md"


def _family(ticket_id: str) -> str:
    return ticket_id.split("-")[0]


def economics(data: dict, a: dict, *, accept_factor=1.0, agent_rate=None, aht_scale=1.0, volume=None) -> dict:
    rate = agent_rate if agent_rate is not None else a["agent_cost_usd_per_hour"]
    vol = volume if volume is not None else a["tickets_per_month"]
    send_ready = set(data["metrics"]["send_ready"])
    saved_min_per_ticket = 0.0
    llm_usd_per_ticket = 0.0
    seg_detail = {}
    for seg, spec in a["mix"].items():
        rows = [r for r in data["rows"] if _family(r["id"]) in spec["families"]]
        if not rows:
            continue
        base = spec["baseline_aht_min"] * aht_scale
        saved = []
        for r in rows:
            if r["action"] == "draft_ready" and r["id"] in send_ready:
                aht = accept_factor * a["aht_send_ready_min"] + (1 - accept_factor) * a["edit_factor"] * base
            elif r["action"] == "draft_ready":
                aht = a["edit_factor"] * base
            elif r["action"] == "abstain":
                aht = base + a["abstain_overhead_min"]
            else:
                aht = base
            saved.append(base - (aht - a["triage_saved_min"]))
        seg_saved = sum(saved) / len(saved)
        seg_cost = sum(r["cost_rub"] for r in rows) / len(rows) / RUB_PER_USD
        saved_min_per_ticket += spec["share"] * seg_saved
        llm_usd_per_ticket += spec["share"] * seg_cost
        seg_detail[seg] = {"saved_min": seg_saved, "llm_usd": seg_cost, "n": len(rows)}

    fixed = a["hosting_usd_per_month"] + a["engineer_hours_per_month"] * a["engineer_cost_usd_per_hour"]
    hours_saved = vol * saved_min_per_ticket / 60
    gross = hours_saved * rate
    llm = vol * llm_usd_per_ticket
    net = gross - llm - fixed
    per_ticket_margin = saved_min_per_ticket / 60 * rate - llm_usd_per_ticket
    return {
        "hours_saved": hours_saved, "gross": gross, "llm": llm, "fixed": fixed, "net": net,
        "saved_min_per_ticket": saved_min_per_ticket, "llm_usd_per_ticket": llm_usd_per_ticket,
        "payback_months": (a["one_off_build_usd"] / net) if net > 0 else None,
        "break_even_volume": (fixed / per_ticket_margin) if per_ticket_margin > 0 else None,
        "segments": seg_detail,
    }


def safety(data: dict, a: dict) -> tuple[bool, str]:
    m = data["metrics"]
    violations = len(m.get("judge_policy_violations") or []) + m["drafts_with_forbidden_content"]
    ok = (m["must_route_recall"] or 0) >= a["min_must_route_recall"] and violations <= a["max_policy_violations"]
    return ok, f"must-route recall {m['must_route_recall']}, policy violations {violations}"


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def render() -> str:
    a = yaml.safe_load(ASSUMPTIONS.read_text(encoding="utf-8"))
    results = {k: v for k, v in load_results().items() if k in CONFIGS}
    if not results:
        raise SystemExit("no eval results; run `python -m app.cli eval` first")

    rows = []
    for name, data in results.items():
        econ = economics(data, a)
        ok, why = safety(data, a)
        rows.append((name, data, econ, ok, why))
    eligible = [r for r in rows if r[3]]
    best = max(eligible or rows, key=lambda r: r[2]["net"])
    # prefer the cheapest config within 3% of the best net saving: simpler to run, less spend at risk
    near = [r for r in (eligible or rows) if r[2]["net"] >= best[2]["net"] * 0.97]
    pick = min(near, key=lambda r: r[2]["llm"])
    name, data, econ, ok, why = pick
    m = data["metrics"]
    cfg = CONFIGS[name]

    sens = [
        ("Base case", economics(data, a)),
        ("Agents accept only half the send-ready drafts", economics(data, a, accept_factor=0.5)),
        (f"Agent cost $5/h (instead of ${a['agent_cost_usd_per_hour']:.0f})", economics(data, a, agent_rate=5)),
        ("Agent cost $15/h", economics(data, a, agent_rate=15)),
        ("Baseline handle times 30% shorter", economics(data, a, aht_scale=0.7)),
        ("Volume x3 (30k tickets/month)", economics(data, a, volume=a["tickets_per_month"] * 3)),
    ]

    verdict = "Yes" if ok and econ["net"] > 0 else "Not yet"
    headline = (
        f"**{verdict}.** Run **`{name}`** ({cfg.mode.replace('_', '-')}: classify with `{cfg.classify_model}`, draft with `{cfg.draft_model}`). "
        f"It saves an estimated **{econ['hours_saved']:,.0f} agent-hours/month (≈{_usd(econ['gross'])})** for **{_usd(econ['llm'])}/month of LLM spend** "
        f"and {_usd(econ['fixed'])}/month to run it: **net ≈{_usd(econ['net'])}/month**"
    )
    headline += (
        f", payback of the {_usd(a['one_off_build_usd'])} build in **{econ['payback_months']:.1f} months**."
        if econ["payback_months"] else ", no payback at these assumptions."
    )
    if econ["break_even_volume"]:
        headline += f" Break-even is ≈{econ['break_even_volume']:,.0f} tickets/month."
    L = [
        "# Business case: is the co-pilot worth running at 10k tickets/month?",
        "",
        headline,
        "",
        f"LLM cost is ≈${econ['llm_usd_per_ticket']:.4f}/ticket, a rounding error next to agent time, so **the choice of configuration is driven by safety and draft quality, not by token price.** "
        f"On the golden set it routed {m['must_route_recall']:.0%} of must-route tickets (complaints, KYC/AML, urgent) to a human, declined {m['advice_declined_rate']:.0%} of trading-advice requests, "
        f"and {m['quote_located_rate']:.0%} of its citations were found verbatim in the KB.",
        "",
        "## Configurations compared (measured on the golden set, re-weighted to the production mix)",
        "",
        "| Config | Safety gate | Send-ready drafts | Judge ground./help. | LLM $/ticket | LLM $/month | Agent hours saved | Net $/month |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n_, d, e, ok_, why_ in rows:
        mm = d["metrics"]
        L.append(
            f"| `{n_}`{' ✅' if n_ == name else ''} | {'pass' if ok_ else 'FAIL'} ({why_}) | {mm['send_ready_rate_of_draft_ready']:.0%} of {sum(r['action']=='draft_ready' for r in d['rows'])} | "
            f"{mm.get('judge_groundedness_mean', 'n/a')} / {mm.get('judge_helpfulness_mean', 'n/a')} | ${e['llm_usd_per_ticket']:.4f} | {_usd(e['llm'])} | {e['hours_saved']:,.0f} | {_usd(e['net'])} |"
        )
    L += [
        "",
        "## Sensitivity (recommended config)",
        "",
        "| Scenario | Hours saved | Net $/month |",
        "|---|---|---|",
    ]
    L += [f"| {label} | {e['hours_saved']:,.0f} | {_usd(e['net'])} |" for label, e in sens]
    seg_line = ", ".join(f"{k} {v['saved_min']:.1f} min" for k, v in econ["segments"].items())
    L += [
        "",
        "## How the number is built",
        "",
        f"- **Measured** (eval, {m['n']} hand-labelled tickets): routing action per ticket, judge scores, cost per ticket from polza.ai billing (`usage.cost_rub` at {RUB_PER_USD} RUB/USD).",
        f"- **Assumed** (`eval/assumptions.yaml`, to replace with helpdesk data): {a['tickets_per_month']:,} tickets/month; agent ${a['agent_cost_usd_per_hour']}/h; production mix "
        + ", ".join(f"{k} {v['share']:.0%}" for k, v in a["mix"].items())
        + "; baseline handle times " + ", ".join(f"{k} {v['baseline_aht_min']:g} min" for k, v in a["mix"].items()) + "; "
        f"send-ready draft {a['aht_send_ready_min']} min, edited draft {a['edit_factor']:.0%} of baseline, triage saves {a['triage_saved_min']} min/ticket.",
        f"- Minutes saved per ticket by segment: {seg_line}. Routed and abstained tickets save only triage time: the co-pilot earns its keep on the repetitive in-KB half.",
        f"- Running cost: hosting {_usd(a['hosting_usd_per_month'])} + {a['engineer_hours_per_month']} engineer-hours/month at ${a['engineer_cost_usd_per_hour']}/h.",
        "- Not counted (upside): faster first response, 24/7 drafting, consistent routing of complaints/KYC, KB-gap reports. Not counted (risk): a wrong answer about money; mitigated by human review of every draft, verbatim-quote checks and fail-closed routing.",
        "",
        "## Biggest lever is content, not model",
        "",
        f"{len(m['answered_out_of_kb']) if m['answered_out_of_kb'] else 'No'} out-of-KB answers slipped through; about 30% of traffic (fees, methods, timelines, platform) is simply not in the four pages (see `docs/KB_ISSUES.md`). "
        "Every topic added to the KB moves tickets from 'abstain' (≈0.3 min saved) to 'draft' (≈4 min saved). That is worth more than any model upgrade.",
    ]
    text = "\n".join(L) + "\n"
    OUT.write_text(text, encoding="utf-8")
    return text
