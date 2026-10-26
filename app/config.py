"""Central configuration: paths, models, prices, thresholds and pipeline configs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
KB_RAW_DIR = DATA_DIR / "kb" / "raw"
KB_PAGES_DIR = DATA_DIR / "kb" / "pages"
INDEX_DIR = DATA_DIR / "index"
EVAL_DIR = DATA_DIR / "eval"
RESULTS_DIR = ROOT / "eval" / "results"

POLZA_BASE_URL = os.getenv("POLZA_BASE_URL", "https://polza.ai/api/v1")
POLZA_API_KEY = os.getenv("POLZA_API_KEY", "")

KB_PAGES = {
    "how-to-deposit": "https://valetax.com/how-to-deposit/",
    "how-to-withdraw": "https://valetax.com/how-to-withdraw/",
    "how-to-open-an-account": "https://valetax.com/how-to-open-an-account/",
    "how-to-verify-account": "https://valetax.com/how-to-verify-account/",
}

# polza.ai bills in RUB. Effective rate derived from the catalog: text-embedding-3-small
# is $0.02/1M upstream and 2.33914 RUB/1M on polza -> 116.957 RUB per USD (markup included).
RUB_PER_USD = 116.957

# RUB per 1M tokens, from GET /api/v1/models (top_provider.pricing), snapshot 2026-10-26.
PRICES_RUB_PER_M = {
    "anthropic/claude-haiku-5.5": {"in": 11.6957, "out": 58.4785, "cache_read": 1.16957},
    "anthropic/claude-sonnet-5": {"in": 233.914, "out": 1169.57, "cache_read": 23.3914},
    "google/gemini-2.5-flash-lite": {"in": 5.84785, "out": 23.3914, "cache_read": 0.584785},
    "openai/text-embedding-3-small": {"in": 2.33914, "out": 0.0},
}

EMBED_MODEL = "openai/text-embedding-3-small"
JUDGE_MODEL = "anthropic/claude-haiku-5.5"  # Sonnet-5 judge kept only as a calibration run (eval/results/calibration)
GEN_MODEL = "anthropic/claude-sonnet-5"  # synthetic ticket text generation


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    mode: str  # "two_call" (classify -> draft) or "single_call" (classify+draft in one request)
    classify_model: str
    draft_model: str
    embed_model: str = EMBED_MODEL
    top_k: int = 5
    min_retrieval_score: float = 0.30  # cosine; below this a chunk is not passed to the drafter
    min_grounding_score: float = 1.0  # share of claim segments with a verified quote
    reasoning_effort: str | None = "none"
    extra: dict = field(default_factory=dict)


HAIKU = "anthropic/claude-haiku-5.5"
SONNET = "anthropic/claude-sonnet-5"
FLASH_LITE = "google/gemini-2.5-flash-lite"

CONFIGS: dict[str, PipelineConfig] = {
    c.name: c
    for c in [
        PipelineConfig("haiku_two_call", "two_call", HAIKU, HAIKU),
        PipelineConfig("haiku_single_call", "single_call", HAIKU, HAIKU),
        PipelineConfig("haiku_cls_sonnet_draft", "two_call", HAIKU, SONNET),
        PipelineConfig("flashlite_cls_haiku_draft", "two_call", FLASH_LITE, HAIKU),
    ]
}
DEFAULT_CONFIG = os.getenv("COPILOT_CONFIG", "haiku_two_call")


def get_config(name: str | None = None, **overrides) -> PipelineConfig:
    cfg = CONFIGS[name or DEFAULT_CONFIG]
    return replace(cfg, **overrides) if overrides else cfg
