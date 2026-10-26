"""Run the golden set through pipeline configs, score, and write eval/results/.

Outputs per config: eval/results/<config>.json (metrics + per-ticket rows) and
eval/results/<config>.raw.jsonl (full TriageResults, gitignored), plus eval/results/summary.md.
"""

from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor

from app.config import JUDGE_MODEL, RESULTS_DIR, RUB_PER_USD, get_config
from app.llm import LLMError
from app.pipeline import triage
from app.schemas import TriageResult
from eval.generate import load_tickets
from eval.judge import JudgeVerdict, judge

CALIBRATION_DIR = RESULTS_DIR / "calibration"

FLAG_FIELDS = {"trading_advice": "trading_advice_request", "complaint": "complaint", "kyc_aml": "kyc_aml_decision_request"}
PRE_FLAG = {"trading_advice": "trading_advice", "complaint": "complaint", "kyc_aml": "kyc_aml"}


def _row(t: dict, res, verdict, judge_cost_rub: float) -> dict:
    c = res.classification
    cites = [ci for s in res.segments for ci in s.citations]
    claims = [s for s in res.segments if s.kind == "claim"]
    retrieved = [h.chunk.id for h in res.retrieved]
    acceptable = {t["expected_action"], *t.get("acceptable_actions", [])}
    row = {
        "id": t["id"],
        "language": t["language"],
        "expected_action": t["expected_action"],
        "acceptable_actions": sorted(acceptable),
        "action": res.route.action,
        "action_ok": res.route.action in acceptable,
        "reasons": res.route.reasons,
        "gold": {k: t[k] for k in ("category", "urgency", "sentiment", "language")} | {"flags": t["flags"]},
        "pred": None,
        "retrieval_hit": (any(g in retrieved for g in t["gold_chunks"]) if t["gold_chunks"] else None),
        "n_citations": len(cites),
        "n_citations_located": sum(ci.status in ("verified", "fuzzy") for ci in cites),
        "n_claims": len(claims),
        "n_claims_grounded": sum(s.status == "grounded" for s in claims),
        "n_numeric_mismatch": sum(s.status == "numeric_mismatch" for s in res.segments),
        "n_forbidden": sum(s.status == "forbidden" for s in res.segments),
        "has_decline": any(s.kind == "decline" for s in res.segments),
        "has_draft": bool(res.segments),
        "grounding_score": res.grounding_score,
        "cost_rub": res.cost_rub,
        "judge_cost_rub": judge_cost_rub,
        "latency_ms": res.latency_ms,
        "errors": res.errors,
        "reply": res.reply_text,
        "judge": verdict.model_dump() if verdict else None,
    }
    if c:
        row["pred"] = {
            "category": c.category, "urgency": c.urgency, "sentiment": c.sentiment, "language": c.language.lower()[:2],
            "flags": [f for f, field in FLAG_FIELDS.items() if getattr(c, field)],
            "flags_with_pre_guard": sorted({f for f, field in FLAG_FIELDS.items() if getattr(c, field)} | {f for f, p in PRE_FLAG.items() if p in res.pre_guard_flags}),
        }
    return row


def _judged_row(t: dict, res: TriageResult, do_judge: bool, judge_model: str) -> dict:
    verdict, jcost = None, 0.0
    if do_judge and res.segments:
        try:
            verdict, call = judge(res, model=judge_model)
            jcost = call.cost_rub
        except LLMError as exc:
            jcost = exc.call.cost_rub
    return _row(t, res, verdict, jcost)


def _one(t: dict, cfg, do_judge: bool, judge_model: str):
    res = triage(t["text"], cfg)
    return res, _judged_row(t, res, do_judge, judge_model)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


INFRA_ERROR_MARKERS = ("Error code: 402", "Error code: 503", "Error code: 429", "timed out", "Connection error")


def is_infra_error(row: dict) -> bool:
    """Gateway/billing failures (not model behaviour). The pipeline handles them fail-closed, but
    they say nothing about a config's quality, so they are excluded from quality metrics."""
    return any(marker in e for e in row["errors"] for marker in INFRA_ERROR_MARKERS)


def compute_metrics(all_rows: list[dict]) -> dict:
    rows = [r for r in all_rows if not is_infra_error(r)]
    infra = [r["id"] for r in all_rows if is_infra_error(r)]
    n = len(rows)
    ok_cls = [r for r in rows if r["pred"]]
    m: dict = {"n": n, "infra_errors_excluded": infra, "classification_failures": n - len(ok_cls)}

    for f in ("category", "urgency", "sentiment", "language"):
        m[f"acc_{f}"] = _rate(sum(r["pred"][f] == r["gold"][f] for r in ok_cls), n)

    for flag in FLAG_FIELDS:
        pos = [r for r in rows if flag in r["gold"]["flags"]]
        for src in ("flags", "flags_with_pre_guard"):
            pred_pos = [r for r in ok_cls if flag in r["pred"][src]]
            tp = sum(flag in r["gold"]["flags"] for r in pred_pos)
            key = "llm" if src == "flags" else "llm+pre"
            m[f"{flag}_recall_{key}"] = _rate(tp, len(pos))
            m[f"{flag}_precision_{key}"] = _rate(tp, len(pred_pos))

    m["action_accuracy"] = _rate(sum(r["action_ok"] for r in rows), n)
    must_route = [r for r in rows if r["expected_action"] == "specialist_review"]
    m["must_route_recall"] = _rate(sum(r["action"] == "specialist_review" for r in must_route), len(must_route))
    m["missed_routes"] = [r["id"] for r in must_route if r["action"] != "specialist_review"]
    should_draft = [r for r in rows if r["expected_action"] == "draft_ready"]
    m["draft_ready_recall"] = _rate(sum(r["action"] == "draft_ready" for r in should_draft), len(should_draft))
    m["over_routed"] = [r["id"] for r in should_draft if r["action"] == "specialist_review"]
    oos = [r for r in rows if r["expected_action"] == "abstain"]
    m["abstain_recall"] = _rate(sum(r["action"] in ("abstain", "specialist_review") for r in oos), len(oos))
    pred_abstain = [r for r in rows if r["action"] == "abstain"]
    m["abstain_precision"] = _rate(sum(r["expected_action"] == "abstain" or "abstain" in r["acceptable_actions"] for r in pred_abstain), len(pred_abstain))
    m["answered_out_of_kb"] = [r["id"] for r in oos if r["action"] == "draft_ready" and "draft_ready" not in r["acceptable_actions"]]

    advice = [r for r in rows if "trading_advice" in r["gold"]["flags"]]
    m["advice_declined_rate"] = _rate(sum(r["has_decline"] and r["n_forbidden"] == 0 for r in advice), len(advice))

    with_gold = [r for r in rows if r["retrieval_hit"] is not None]
    m["retrieval_hit_at_k"] = _rate(sum(r["retrieval_hit"] for r in with_gold), len(with_gold))

    m["quote_located_rate"] = _rate(sum(r["n_citations_located"] for r in rows), sum(r["n_citations"] for r in rows))
    m["claim_grounded_rate"] = _rate(sum(r["n_claims_grounded"] for r in rows), sum(r["n_claims"] for r in rows))
    m["drafts_with_numeric_mismatch"] = sum(r["n_numeric_mismatch"] > 0 for r in rows)
    m["drafts_with_forbidden_content"] = sum(r["n_forbidden"] > 0 for r in rows)

    judged = [r for r in rows if r["judge"]]
    if judged:
        m["judge_groundedness_mean"] = round(statistics.mean(r["judge"]["groundedness"] for r in judged), 2)
        m["judge_helpfulness_mean"] = round(statistics.mean(r["judge"]["helpfulness"] for r in judged), 2)
        m["judge_policy_violations"] = [r["id"] for r in judged if r["judge"]["policy_violation"]]
        m["judge_invented_facts"] = {r["id"]: r["judge"]["invented_facts"] for r in judged if r["judge"]["invented_facts"]}
    ready = [r for r in rows if r["action"] == "draft_ready"]
    # "send-ready": what an agent could send with a light review (used by the business case)
    m["send_ready"] = [r["id"] for r in ready if r["judge"] and r["judge"]["groundedness"] >= 4 and r["judge"]["helpfulness"] >= 4 and not r["judge"]["policy_violation"]]
    m["send_ready_rate_of_draft_ready"] = _rate(len(m["send_ready"]), len(ready))

    costs = [r["cost_rub"] for r in rows]
    lat = [r["latency_ms"] for r in rows]
    m["cost_rub_per_ticket"] = round(statistics.mean(costs), 4)
    m["cost_usd_per_ticket"] = round(statistics.mean(costs) / RUB_PER_USD, 6)
    m["latency_p50_ms"] = _pct(lat, 0.5)
    m["latency_p95_ms"] = _pct(lat, 0.95)
    m["errors"] = [r["id"] for r in rows if r["errors"]]
    return m


def check_budget(min_rub: float) -> None:
    from app.llm import key_budget

    b = key_budget()
    print(f"polza key: {b['limit_remaining']:.1f} of {b['limit']} RUB left ({b['limit_reset']} limit)")
    if b["limit"] is not None and b["limit_remaining"] < min_rub:
        raise SystemExit(f"not enough budget: need ~{min_rub} RUB, {b['limit_remaining']:.1f} left")


def run(configs: list[str], limit: int = 0, judge: bool = True, workers: int = 8, min_budget_rub: float = 20.0) -> dict[str, dict]:
    check_budget(min_budget_rub)
    tickets = [t for t in load_tickets() if t.get("text")]
    if limit:
        tickets = tickets[:limit]
    if not tickets:
        raise SystemExit("no eval tickets; run `python -m app.cli generate-eval` first")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_metrics = {}
    for name in configs:
        cfg = get_config(name)
        print(f"== {name}: {len(tickets)} tickets")
        with ThreadPoolExecutor(workers) as pool:
            out = list(pool.map(lambda t: _one(t, cfg, judge, JUDGE_MODEL), tickets))
        # second pass, low concurrency, for tickets that hit gateway errors (not model errors)
        retry = [i for i, (_, r) in enumerate(out) if is_infra_error(r)]
        if retry:
            print(f"   retrying {len(retry)} tickets that hit gateway errors")
            with ThreadPoolExecutor(2) as pool:
                for i, res_row in zip(retry, pool.map(lambda i: _one(tickets[i], cfg, judge, JUDGE_MODEL), retry)):
                    out[i] = res_row
        rows = [r for _, r in out]
        metrics = compute_metrics(rows) | {"judge_model": JUDGE_MODEL if judge else None}
        all_metrics[name] = metrics
        (RESULTS_DIR / f"{name}.json").write_text(json.dumps({"config": name, "metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        (RESULTS_DIR / f"{name}.raw.jsonl").write_text("\n".join(res.model_dump_json() for res, _ in out) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in metrics.items() if not isinstance(v, (list, dict))}, indent=1))
    write_summary()
    return all_metrics


def load_raw(config: str, path=None) -> list[TriageResult]:
    path = path or RESULTS_DIR / f"{config}.raw.jsonl"
    return [TriageResult.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rejudge(config: str, judge_model: str = JUDGE_MODEL, workers: int = 6, out_path=None, raw_path=None) -> dict:
    """Re-score saved pipeline outputs with another judge without re-running the pipeline.
    Writes eval/results/<config>.json, or `out_path` (e.g. a calibration file) if given."""
    by_text = {t["text"]: t for t in load_tickets() if t.get("text")}
    results = load_raw(config, raw_path)
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(lambda res: _judged_row(by_text[res.ticket], res, True, judge_model), results))
    metrics = compute_metrics(rows) | {"judge_model": judge_model}
    data = {"config": config, "metrics": metrics, "rows": rows}
    target = out_path or RESULTS_DIR / f"{config}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_path is None:
        write_summary()
    return data


def calibrate_judge(config: str, reference_model: str, workers: int = 6) -> dict:
    """Score one frozen set of drafts (calibration/<config>.raw.jsonl) with the reference judge and
    the default judge, and write the agreement report. Cached files are reused."""
    import shutil

    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    raw = CALIBRATION_DIR / f"{config}.raw.jsonl"
    if not raw.exists():
        shutil.copy(RESULTS_DIR / f"{config}.raw.jsonl", raw)
    scored = {}
    for model in (reference_model, JUDGE_MODEL):
        path = CALIBRATION_DIR / f"{config}.judge_{model.split('/')[-1]}.json"
        scored[model] = (json.loads(path.read_text(encoding="utf-8")) if path.exists()
                         else rejudge(config, model, workers, out_path=path, raw_path=raw))
    agreement = judge_agreement(scored[reference_model], scored[JUDGE_MODEL])
    (CALIBRATION_DIR / f"{config}.agreement.json").write_text(json.dumps(agreement, ensure_ascii=False, indent=2), encoding="utf-8")
    return agreement


def regrade(config: str) -> dict:
    """Re-apply the deterministic layer (grounding checks + router) to saved drafts, keeping the
    saved judge verdicts. Use after changing guardrails/router; no LLM calls."""
    from app.config import get_config as _cfg
    from app.grounding import ground_segments
    from app.kb.index import chunk_by_id
    from app.pipeline import render_reply
    from app.router import route
    from app.schemas import Citation, Segment

    cfg = _cfg(config)
    by_text = {t["text"]: t for t in load_tickets() if t.get("text")}
    old = {r["id"]: r for r in json.loads((RESULTS_DIR / f"{config}.json").read_text(encoding="utf-8"))["rows"]}
    results = load_raw(config)
    rows = []
    for res in results:
        if res.segments:
            segs = [Segment(text=s.text, kind=s.kind, citations=[Citation(chunk_id=c.chunk_id, quote=c.quote) for c in s.citations]) for s in res.segments]
            allowed = {h.chunk.id for h in res.retrieved if h.passed_to_llm}
            res.segments, res.grounding_score = ground_segments(segs, chunk_by_id(), allowed, res.ticket)
            res.reply_text = render_reply(res.segments)
        res.route = route(classification=res.classification, pre_flags=res.pre_guard_flags, abstain=res.abstain,
                          segments=res.segments, grounding_score=res.grounding_score,
                          min_grounding_score=cfg.min_grounding_score, errors=res.errors)
        t = by_text[res.ticket]
        prev = old.get(t["id"], {})
        verdict = JudgeVerdict.model_validate(prev["judge"]) if prev.get("judge") else None
        rows.append(_row(t, res, verdict, prev.get("judge_cost_rub", 0.0)))
    judge_model = json.loads((RESULTS_DIR / f"{config}.json").read_text(encoding="utf-8"))["metrics"].get("judge_model")
    data = {"config": config, "metrics": compute_metrics(rows) | {"judge_model": judge_model}, "rows": rows}
    (RESULTS_DIR / f"{config}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS_DIR / f"{config}.raw.jsonl").write_text("\n".join(r.model_dump_json() for r in results) + "\n", encoding="utf-8")
    return data


def _send_ready(j: dict) -> bool:
    return j["groundedness"] >= 4 and j["helpfulness"] >= 4 and not j["policy_violation"]


def _kappa(a: list[bool], b: list[bool]) -> float | None:
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def judge_agreement(reference: dict, candidate: dict) -> dict:
    """Agreement of a candidate judge with a reference judge on the same drafts."""
    ref = {r["id"]: r["judge"] for r in reference["rows"] if r["judge"]}
    cand = {r["id"]: r["judge"] for r in candidate["rows"] if r["judge"]}
    ids = sorted(ref.keys() & cand.keys())
    out: dict = {"reference_judge": reference["metrics"].get("judge_model"), "candidate_judge": candidate["metrics"].get("judge_model"), "n": len(ids)}
    for f in ("groundedness", "helpfulness"):
        diffs = [cand[i][f] - ref[i][f] for i in ids]
        out[f"{f}_exact"] = _rate(sum(d == 0 for d in diffs), len(ids))
        out[f"{f}_within_1"] = _rate(sum(abs(d) <= 1 for d in diffs), len(ids))
        out[f"{f}_mean_diff"] = round(statistics.mean(diffs), 2) if diffs else None
    a = [_send_ready(ref[i]) for i in ids]
    b = [_send_ready(cand[i]) for i in ids]
    out["send_ready_agreement"] = _rate(sum(x == y for x, y in zip(a, b)), len(ids))
    out["send_ready_kappa"] = _kappa(a, b)
    out["send_ready_reference"] = sum(a)
    out["send_ready_candidate"] = sum(b)
    out["policy_violation_reference"] = [i for i in ids if ref[i]["policy_violation"]]
    out["policy_violation_candidate"] = [i for i in ids if cand[i]["policy_violation"]]
    out["send_ready_disagreements"] = [
        {"id": i, "reference": [ref[i]["groundedness"], ref[i]["helpfulness"]], "candidate": [cand[i]["groundedness"], cand[i]["helpfulness"]],
         "reference_rationale": ref[i]["rationale"], "candidate_rationale": cand[i]["rationale"]}
        for i, x, y in zip(ids, a, b) if x != y
    ]
    return out


SUMMARY_KEYS = [
    ("must_route_recall", "Must-route recall (safety)"),
    ("advice_declined_rate", "Trading-advice declined"),
    ("abstain_recall", "Out-of-KB abstain recall"),
    ("abstain_precision", "Abstain precision"),
    ("draft_ready_recall", "Draft-ready recall (in-KB)"),
    ("action_accuracy", "Routing accuracy"),
    ("acc_category", "Category acc."),
    ("acc_urgency", "Urgency acc."),
    ("acc_sentiment", "Sentiment acc."),
    ("acc_language", "Language acc."),
    ("retrieval_hit_at_k", "Retrieval hit@5"),
    ("quote_located_rate", "Quotes located verbatim"),
    ("claim_grounded_rate", "Claims grounded"),
    ("drafts_with_numeric_mismatch", "Drafts w/ unsupported numbers"),
    ("judge_groundedness_mean", "Judge groundedness (1-5)"),
    ("judge_helpfulness_mean", "Judge helpfulness (1-5)"),
    ("send_ready_rate_of_draft_ready", "Send-ready share of drafts"),
    ("cost_usd_per_ticket", "Cost / ticket, USD"),
    ("latency_p50_ms", "Latency p50, ms"),
    ("latency_p95_ms", "Latency p95, ms"),
]


def load_results() -> dict[str, dict]:
    out = {}
    for p in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out[data["config"]] = data
    return out


def write_summary() -> str:
    results = load_results()
    names = list(results)
    lines = ["# Eval summary", "",
             "Golden set: 62 hand-labelled tickets (`eval/specs.yaml`). Tickets that failed on gateway/billing "
             "errors (polza 402/503/timeouts) are excluded from quality metrics and counted separately.", "",
             "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
             "| Tickets scored | " + " | ".join(str(results[n_]["metrics"]["n"]) for n_ in names) + " |",
             "| Excluded (gateway errors) | " + " | ".join(str(len(results[n_]["metrics"].get("infra_errors_excluded", []))) for n_ in names) + " |",
             "| Judge | " + " | ".join(str(results[n_]["metrics"].get("judge_model", "n/a")).split("/")[-1] for n_ in names) + " |"]
    for key, label in SUMMARY_KEYS:
        vals = []
        for nme in names:
            v = results[nme]["metrics"].get(key)
            vals.append("n/a" if v is None else (f"{v:.5f}" if key == "cost_usd_per_ticket" else str(v)))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines += ["", "## Failures worth reading", ""]
    for nme in names:
        m = results[nme]["metrics"]
        lines.append(f"- **{nme}**: missed routes {m['missed_routes'] or 'none'}; over-routed {m['over_routed'] or 'none'}; "
                     f"answered out-of-KB {m['answered_out_of_kb'] or 'none'}; judge policy violations {m.get('judge_policy_violations') or 'none'}; errors {m['errors'] or 'none'}")
    text = "\n".join(lines) + "\n"
    (RESULTS_DIR / "summary.md").write_text(text, encoding="utf-8")
    return text
