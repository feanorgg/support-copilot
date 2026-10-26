"""FastAPI app: POST /api/triage + a single-page agent UI at /."""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.config import CONFIGS, DEFAULT_CONFIG, EVAL_DIR, ROOT, get_config
from app.pipeline import triage
from app.schemas import TriageResult

app = FastAPI(title="Valetax support co-pilot")
STATIC = ROOT / "app" / "static"


class TriageRequest(BaseModel):
    ticket: str = Field(min_length=3, max_length=8000)
    config: str = DEFAULT_CONFIG


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/configs")
def configs():
    return {"default": DEFAULT_CONFIG, "configs": [{"name": c.name, "mode": c.mode, "classify_model": c.classify_model, "draft_model": c.draft_model} for c in CONFIGS.values()]}


@app.get("/api/examples")
def examples():
    """A handful of golden-set tickets to click through in the UI."""
    path = EVAL_DIR / "tickets.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    picked, seen = [], set()
    for r in rows:  # one example per scenario family
        fam = r["id"].split("-")[0]
        if fam not in seen and r.get("text"):
            seen.add(fam)
            picked.append({"id": r["id"], "label": f"{r['id']} ({r['language']})", "text": r["text"]})
    return picked


@app.post("/api/triage", response_model=TriageResult)
async def triage_endpoint(req: TriageRequest):
    if req.config not in CONFIGS:
        raise HTTPException(400, f"unknown config {req.config}")
    return await run_in_threadpool(triage, req.ticket, get_config(req.config))
