"""CLI: python -m app.cli <command>."""

from __future__ import annotations

import json

import typer

from app.config import CONFIGS, DEFAULT_CONFIG, get_config

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command()
def scrape(offline: bool = typer.Option(False, help="Re-parse committed raw HTML instead of fetching")):
    """Fetch the 4 Valetax help pages into data/kb (snapshot)."""
    from app.kb.scrape import scrape as run

    for p in run(offline=offline):
        typer.echo(f"{p['slug']}: {len(p['steps'])} steps, {len(p['faq'])} FAQ items")


@cli.command()
def index():
    """Chunk the snapshot and embed it into data/index."""
    from app.kb.index import build_index

    chunks, vectors = build_index()
    typer.echo(f"indexed {len(chunks)} chunks, dim={vectors.shape[1]}")


@cli.command()
def triage(
    ticket: str,
    config: str = typer.Option(DEFAULT_CONFIG, help=f"One of: {', '.join(CONFIGS)}"),
    as_json: bool = typer.Option(False, "--json", help="Print the full TriageResult as JSON"),
):
    """Triage one ticket and print the result."""
    from app.pipeline import triage as run

    res = run(ticket, get_config(config))
    if as_json:
        typer.echo(res.model_dump_json(indent=2))
        return
    c = res.classification
    typer.secho(f"\nACTION: {res.route.action}  reasons={res.route.reasons}", bold=True)
    if c:
        typer.echo(f"category={c.category} urgency={c.urgency} language={c.language} sentiment={c.sentiment}")
        typer.echo(f"flags: advice={c.trading_advice_request} complaint={c.complaint} kyc_aml={c.kyc_aml_decision_request}")
    if res.pre_guard_flags:
        typer.echo(f"pre-guard: {res.pre_guard_flags}")
    typer.echo("\nretrieved: " + ", ".join(f"{h.chunk.id}({h.score:.2f}{'*' if h.cited else ''})" for h in res.retrieved))
    if res.abstain:
        typer.secho(f"\nABSTAIN: {res.abstain_reason}", fg="yellow")
    for s in res.segments:
        marks = "".join(f"[{c.n}{'' if c.status in ('verified', 'fuzzy') else '!'}]" for c in s.citations)
        color = {"grounded": "green", "not_required": None, "unsupported": "red", "numeric_mismatch": "red", "forbidden": "red"}[s.status]
        typer.secho(f"  ({s.kind}/{s.status}) {s.text} {marks}", fg=color)
        for c in s.citations:
            typer.echo(f"      [{c.n}] {c.chunk_id} {c.status}: \"{c.quote}\"")
        for i in s.issues:
            typer.secho(f"      ! {i}", fg="red")
    if res.agent_note:
        typer.echo(f"\nagent note: {res.agent_note}")
    if res.errors:
        typer.secho(f"errors: {res.errors}", fg="red")
    typer.echo(f"\ngrounding={res.grounding_score} cost=${res.cost_usd:.5f} ({res.cost_rub:.3f} RUB) latency={res.latency_ms}ms")


@cli.command("generate-eval")
def generate_eval(force: bool = typer.Option(False, help="Regenerate texts that already exist")):
    """Write ticket texts for eval/specs.yaml into data/eval/tickets.jsonl."""
    from eval.generate import generate

    generate(force=force)


@cli.command("eval")
def run_eval(
    config: list[str] = typer.Option(None, "--config", help="Repeatable; default: all configs"),
    limit: int = typer.Option(0, help="Only the first N tickets (0 = all)"),
    judge: bool = typer.Option(True, help="Run the LLM judge on drafts"),
    workers: int = typer.Option(8),
):
    """Run the golden set through one or more configs and write eval/results/."""
    from eval.run_eval import run

    run(config or list(CONFIGS), limit=limit, judge=judge, workers=workers)


@cli.command("calibrate-judge")
def calibrate_judge(
    config: str = typer.Option("haiku_two_call"),
    reference_model: str = typer.Option("anthropic/claude-sonnet-5"),
):
    """Agreement of the default (Haiku) judge with a reference judge on the same drafts."""
    from eval.run_eval import calibrate_judge as run

    agreement = run(config, reference_model)
    typer.echo(json.dumps({k: v for k, v in agreement.items() if k != "send_ready_disagreements"}, indent=1))


@cli.command("business-case")
def business_case():
    """Render docs/BUSINESS_CASE.md from eval results + eval/assumptions.yaml."""
    from eval.business_case import render

    typer.echo(render())


@cli.command()
def configs():
    """List pipeline configurations."""
    for c in CONFIGS.values():
        typer.echo(json.dumps({"name": c.name, "mode": c.mode, "classify": c.classify_model, "draft": c.draft_model}))


if __name__ == "__main__":
    cli()
