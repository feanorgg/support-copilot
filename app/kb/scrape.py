"""Scrape the four Valetax help pages into a reproducible snapshot.

Writes, per page:
  data/kb/raw/<slug>.html     - untouched HTML as fetched
  data/kb/pages/<slug>.json   - structured: title, intro, steps[], faq[{q, a}]
  data/kb/pages/<slug>.md     - human-readable rendering of the same content

The snapshot is committed so indexing/eval are reproducible even if the site changes.
`parse_page` is pure (HTML in, dict out) so it can run on the committed raw HTML offline.
"""

from __future__ import annotations

import json
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

from app.config import KB_PAGES, KB_PAGES_DIR, KB_RAW_DIR

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def parse_page(html: str, slug: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if main is None:
        raise ValueError(f"{slug}: <main> not found, page layout changed?")

    h1 = main.find("h1")
    title = _text(h1) if h1 else slug
    intro_p = h1.find_next("p") if h1 else None
    intro = _text(intro_p) if intro_p else ""

    steps = []
    for item in main.select(".seps-list__item"):
        wrap = item.select_one(".seps-list__content-wrap") or item
        heading = wrap.find(["h2", "h3"])
        if heading is None:
            continue
        body = [_text(p) for p in wrap.find_all("p") if not p.find_parent(class_="seps-list__label")]
        steps.append(" ".join([_text(heading), *[b for b in body if b]]).strip())

    faq = []
    for item in main.select(".accordion__item"):
        q = item.find("h4")
        a = item.select_one(".accordion__text")
        if q is None or a is None or not _text(a):
            continue  # e.g. trailing "All set to trade?" CTA rendered as an empty accordion item
        faq.append({"q": _text(q), "a": _text(a)})

    faq_title = ""
    for h2 in main.find_all("h2"):
        if "question" in _text(h2).lower():
            faq_title = _text(h2)
            break

    return {
        "slug": slug,
        "url": url,
        "title": title,
        "intro": intro,
        "steps": steps,
        "faq_title": faq_title,
        "faq": faq,
        "snapshot_date": date.today().isoformat(),
    }


def render_markdown(page: dict) -> str:
    lines = [f"# {page['title']}", "", f"Source: {page['url']} (snapshot {page['snapshot_date']})", ""]
    if page["intro"]:
        lines += [page["intro"], ""]
    if page["steps"]:
        lines += ["## Steps", ""]
        lines += [f"{i}. {s}" for i, s in enumerate(page["steps"], 1)]
        lines.append("")
    if page["faq"]:
        lines += [f"## {page['faq_title'] or 'FAQ'}", ""]
        for item in page["faq"]:
            lines += [f"### {item['q']}", "", item["a"], ""]
    return "\n".join(lines)


def scrape(offline: bool = False) -> list[dict]:
    """Fetch (or, with offline=True, re-parse committed raw HTML) and write the snapshot."""
    KB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    KB_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    pages = []
    for slug, url in KB_PAGES.items():
        raw_path = KB_RAW_DIR / f"{slug}.html"
        if offline:
            html = raw_path.read_text(encoding="utf-8")
        else:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            html = resp.text
            raw_path.write_text(html, encoding="utf-8")
        page = parse_page(html, slug, url)
        (KB_PAGES_DIR / f"{slug}.json").write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
        (KB_PAGES_DIR / f"{slug}.md").write_text(render_markdown(page), encoding="utf-8")
        pages.append(page)
    return pages


def load_pages() -> list[dict]:
    return [json.loads((KB_PAGES_DIR / f"{slug}.json").read_text(encoding="utf-8")) for slug in KB_PAGES]
