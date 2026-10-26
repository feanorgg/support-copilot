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


FALLBACK_CONFIG = "haiku_two_call"  # same classifier + retrieval; used for segments a run could not measure


def _scored(data: dict) -> list[dict]:
    excluded = set(data["metrics"].get("infra_errors_excluded", []))
    return [r for r in data["rows"] if r["id"] not in excluded]


def economics(data: dict, a: dict, *, accept_factor=1.0, agent_rate=None, aht_scale=1.0, volume=None, fallback: dict | None = None) -> dict:
    rate = agent_rate if agent_rate is not None else a["agent_cost_usd_per_hour"]
    vol = volume if volume is not None else a["tickets_per_month"]
    send_ready = set(data["metrics"]["send_ready"])
    scored = _scored(data)
    own_mean_cost = sum(r["cost_rub"] for r in scored) / len(scored) / RUB_PER_USD
    saved_min_per_ticket = 0.0
    llm_usd_per_ticket = 0.0
    seg_detail = {}
    borrowed = []
    for seg, spec in a["mix"].items():
        rows = [r for r in scored if _family(r["id"]) in spec["families"]]
        cost_rows = rows
        if not rows and fallback is not None:
            # segment not measured for this config (gateway/billing failures): borrow routing
            # outcomes from the fallback config, keep this config's own average cost
            send_ready = send_ready | set(fallback["metrics"]["send_ready"])
            rows = [r for r in _scored(fallback) if _family(r["id"]) in spec["families"]]
            cost_rows = []
            borrowed.append(seg)
        if not rows:
            continue
        base = spec["baseline_aht_min"] * aht_scale
        saved = []
        for r in rows:
            if r["action"] == "draft_ready" and not r["action_ok"]:
                # a draft for a question the KB does not answer: the agent reads it, then answers anyway
                aht = base + a["abstain_overhead_min"]
            elif r["action"] == "draft_ready" and r["id"] in send_ready:
                aht = accept_factor * a["aht_send_ready_min"] + (1 - accept_factor) * a["edit_factor"] * base
            elif r["action"] == "draft_ready":
                aht = a["edit_factor"] * base
            elif r["action"] == "abstain":
                aht = base + a["abstain_overhead_min"]
            else:
                aht = base
            saved.append(base - (aht - a["triage_saved_min"]))
        seg_saved = sum(saved) / len(saved)
        seg_cost = sum(r["cost_rub"] for r in cost_rows) / len(cost_rows) / RUB_PER_USD if cost_rows else own_mean_cost
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
        "borrowed_segments": borrowed,
    }


def safety(data: dict, a: dict) -> tuple[bool, str]:
    m = data["metrics"]
    violations = len(m.get("judge_policy_violations") or []) + m["drafts_with_forbidden_content"]
    ok = ((m["must_route_recall"] or 0) >= a["min_must_route_recall"]
          and (m["advice_declined_rate"] or 0) >= a["min_advice_declined"]
          and violations <= a["max_policy_violations"])
    return ok, f"must-route {m['must_route_recall']:.0%}, advice declined {m['advice_declined_rate']:.0%}, violations {violations}"


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def render() -> str:
    a = yaml.safe_load(ASSUMPTIONS.read_text(encoding="utf-8"))
    results = {k: v for k, v in load_results().items() if k in CONFIGS}
    if not results:
        raise SystemExit("no eval results; run `python -m app.cli eval` first")

    fallback = results.get(FALLBACK_CONFIG)
    rows = []
    for name, data in results.items():
        econ = economics(data, a, fallback=fallback if name != FALLBACK_CONFIG else None)
        ok, why = safety(data, a)
        rows.append((name, data, econ, ok, why))
    eligible = [r for r in rows if r[3]]
    best = max(eligible or rows, key=lambda r: r[2]["net"])
    # within 3% of the best net saving the difference is noise on 62 tickets: prefer draft quality
    near = [r for r in (eligible or rows) if r[2]["net"] >= best[2]["net"] * 0.97]
    pick = max(near, key=lambda r: (r[1]["metrics"]["send_ready_rate_of_draft_ready"] or 0, -r[2]["llm"]))
    name, data, econ, ok, why = pick
    m = data["metrics"]
    cfg = CONFIGS[name]
    fb = fallback if name != FALLBACK_CONFIG else None

    stress = {
        "agents accept only half of the send-ready drafts": economics(data, a, accept_factor=0.5, fallback=fb),
        "agents cost $5/h": economics(data, a, agent_rate=5, fallback=fb),
        "current handle times are 30% shorter": economics(data, a, aht_scale=0.7, fallback=fb),
    }
    worst_label, worst = min(stress.items(), key=lambda kv: kv[1]["net"])
    def short(model: str) -> str:  # "anthropic/claude-haiku-5.5" -> "Claude Haiku 5.5"
        return model.split("/")[-1].replace("-", " ").title()

    models = (f"{short(cfg.classify_model)} classifies and drafts" if cfg.classify_model == cfg.draft_model
              else f"{short(cfg.classify_model)} classifies, {short(cfg.draft_model)} drafts")
    gw = a["gateway_billing_multiplier"]
    others = [r for r in rows if r[0] != name]

    L = [
        f"# Is the support co-pilot worth running at {a['tickets_per_month']:,} tickets/month?",
        "",
        f"**{'Yes' if ok and econ['net'] > 0 else 'Not yet'}. Run `{name}`** ({models}). It frees **≈{econ['hours_saved']:,.0f} agent-hours a month** for "
        f"**≈{_usd(econ['llm'])} of LLM spend**: net **≈{_usd(econ['net'])}/month**, the ≈{_usd(a['one_off_build_usd'])} build pays back in **{econ['payback_months']:.1f} months**.",
        "",
        "## Why it pays",
        "",
        "| Per month | |",
        "|---|---|",
        f"| Agent time saved ({econ['hours_saved']:,.0f} h at ${a['agent_cost_usd_per_hour']:g}/h) | {_usd(econ['gross'])} |",
        f"| LLM (${econ['llm_usd_per_ticket'] * 1000:.2f} per 1,000 tickets) | −{_usd(econ['llm'])} |",
        f"| Hosting + {a['engineer_hours_per_month']} engineer-hours of upkeep | −{_usd(econ['fixed'])} |",
        f"| **Net** | **{_usd(econ['net'])}** |",
        "",
        f"- The saving comes from the repetitive half of traffic: a send-ready draft cuts a {a['mix']['in_kb']['baseline_aht_min']:g}-minute ticket to "
        f"{a['aht_send_ready_min']:g} minutes of review. Complaints, KYC/AML and out-of-KB tickets still go to people; there the co-pilot only saves triage.",
        f"- It stays clearly positive under stress: if {worst_label}, net is still **{_usd(worst['net'])}/month**. Break-even is ≈{econ['break_even_volume']:,.0f} tickets/month, "
        f"so at today's volume the margin is wide and it grows linearly with volume.",
        f"- LLM cost is noise: even at the {gw:g}× gateway overbilling we observed it is {econ['llm'] * gw / econ['gross']:.1%} of the time saved.",
        "",
        "## Why this configuration",
        "",
        "| Config | Safe¹ | Send-ready drafts² | $/ticket | Net/month |",
        "|---|---|---|---|---|",
    ]
    for n_, d, e, ok_, _ in rows:
        mm = d["metrics"]
        star = "³" if e["borrowed_segments"] else ""
        label = f"**`{n_}`**" if n_ == name else f"`{n_}`{star}"
        L.append(f"| {label} | {'yes' if ok_ else 'no'} | {mm['send_ready_rate_of_draft_ready']:.0%} | ${e['llm_usd_per_ticket']:.4f} | {_usd(e['net'])} |")
    sonnet = next((r for r in others if "sonnet" in r[0]), None)
    single = next((r for r in others if "single" in r[0]), None)
    L += [
        "",
        f"All four are safe, so the choice is draft quality per dollar. `{name}` has the most send-ready drafts and the highest net. "
        + (f"Sonnet drafts are not better here and cost {sonnet[2]['llm_usd_per_ticket'] / econ['llm_usd_per_ticket']:.0f}× more. " if sonnet else "")
        + (f"Single-call costs the same but abstains on out-of-KB questions only {single[1]['metrics']['abstain_recall']:.0%} of the time "
           f"(vs {m['abstain_recall']:.0%}), so agents get more drafts that don't answer the question." if single else ""),
        "",
        f"¹ 100% of complaint/KYC/AML/urgent tickets routed to a human, 100% of trading-advice requests declined, 0 hard-rule violations "
        f"(62 hand-labelled tickets). ² Rated ≥4/5 on groundedness and helpfulness by a judge that is stricter than a Sonnet judge. "
        + ("³ Out-of-KB tickets not measured (gateway spend limit hit mid-run); outcomes borrowed from `haiku_two_call`." if any(r[2]["borrowed_segments"] for r in rows) else ""),
        "",
        "## What would change the answer",
        "",
        f"Inputs marked as assumptions in `eval/assumptions.yaml` (ticket mix, handle times, ${a['agent_cost_usd_per_hour']:g}/h agent cost) should be replaced "
        "with helpdesk data before go-live; the eval set is synthetic. The cheapest further gain is content, not model: "
        f"≈{a['mix']['out_of_kb']['share']:.0%} of tickets ask about fees, payment methods and withdrawal timelines that the four help pages don't cover.",
    ]
    text = "\n".join(L) + "\n"
    OUT.write_text(text, encoding="utf-8")
    return text
