#!/usr/bin/env python3
"""VIP Intel — daily collector.

- Reads VIP list from vault/vips/lista-vips.md
- Collects news for YESTERDAY (America/Sao_Paulo) per company via Google News RSS
- Prepares a markdown file: vault/vips/daily/YYYY-MM-DD.md (YYYY-MM-DD = yesterday)
- Maintains dedupe state in vault/_estado/vips-intel-state.json

LinkedIn collection is scaffolded: it expects URLs in state["linkedin_profiles"]["<Person>"]
If URLs are missing, it will leave the section with a TODO line (no extra data).

This script is deterministic and safe: no posting, no interactions.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from pathlib import Path

# Workspace root (this agent's repo) — robust even if cwd changes
WORKSPACE = str(Path(__file__).resolve().parents[3])

# Canonical memory repo (no symlinks). This is the source of truth.
MARCIA_MEMORY_REPO = os.environ.get("MARCIA_MEMORY_REPO", "/srv/marcia-memory")
VAULT = os.path.join(MARCIA_MEMORY_REPO, "vault")
DATA = os.path.join(MARCIA_MEMORY_REPO, "data")

VIP_LIST = os.path.join(VAULT, "vips", "lista-vips.md")
OUT_DIR = os.path.join(VAULT, "vips", "daily")
STATE_PATH = os.path.join(DATA, "vips", "vips-intel-state.json")

TZ_NAME = "America/Sao_Paulo"


def sp_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow()
    return datetime.now(ZoneInfo(TZ_NAME))


def yesterday_range_sp(now: datetime):
    y = (now.date() - timedelta(days=1))
    start = datetime(y.year, y.month, y.day, 0, 0, 0, tzinfo=now.tzinfo)
    end = datetime(y.year, y.month, y.day, 23, 59, 59, tzinfo=now.tzinfo)
    return y.isoformat(), start, end


def load_state():
    if not os.path.exists(STATE_PATH):
        return {
            "seen_news": {},
            "linkedin_profiles": {},
            "last_run": None,
        }
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def parse_vip_list(md_path: str):
    """Parse VIP list with a simple, robust state machine."""
    with open(md_path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]

    section = None
    companies = []
    people = []

    for raw in lines:
        line = raw.strip()
        if line.lower() == "## empresas":
            section = "empresas"
            continue
        if line.lower() == "## pessoas":
            section = "pessoas"
            continue

        if section == "empresas":
            m = re.match(r"^\d+\.\s+(.*)$", line)
            if m:
                companies.append(m.group(1).strip())

        if section == "pessoas":
            if not line:
                continue
            if line.startswith("-"):
                line = line[1:].strip()
            if "—" in line:
                person, company = [p.strip() for p in line.split("—", 1)]
                if person and company:
                    people.append((person, company))

    if not companies:
        raise RuntimeError("Não encontrei empresas em vault/vips/lista-vips.md (seção '## Empresas')")
    if not people:
        raise RuntimeError("Não encontrei pessoas em vault/vips/lista-vips.md (seção '## Pessoas')")

    return companies, people


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    pub: str


def fetch_url(url: str, timeout=30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (OpenClaw VIP Intel)"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def google_news_rss(company: str, y_date: str, state: dict) -> str:
    # Best-effort: constrain to yesterday with after/before.
    # before: today, after: yesterday
    y = y_date
    today = (datetime.fromisoformat(y) + timedelta(days=1)).date().isoformat()

    q_override = (state.get("company_queries") or {}).get(company)
    base_q = q_override or f'"{company}"'
    q = f"({base_q}) after:{y} before:{today}"

    params = {
        "q": q,
        "hl": "pt-BR",
        "gl": "BR",
        "ceid": "BR:pt-419",
    }
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def parse_rss_items(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []
    items = []
    for it in channel.findall("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        source_el = it.find("source")
        source = (source_el.text or "").strip() if source_el is not None and source_el.text else ""
        pub = (it.findtext("pubDate") or "").strip()
        if title and link:
            items.append(NewsItem(title=title, link=link, source=source, pub=pub))
    return items


def dedupe_news(state, company: str, items):
    seen = set(state.get("seen_news", {}).get(company, []))
    out = []
    for it in items:
        if it.link in seen:
            continue
        out.append(it)
    # Update seen with newly selected
    if out:
        state.setdefault("seen_news", {}).setdefault(company, [])
        state["seen_news"][company].extend([it.link for it in out])
        # Cap history per company
        state["seen_news"][company] = state["seen_news"][company][-500:]
    return out


def write_daily_md(date_str: str, companies, company_news, people, linkedin_notes):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{date_str}.md")

    lines = []
    lines.append("---")
    lines.append("type: documento")
    lines.append(f"data: {date_str}")
    lines.append(f"atualizado: {sp_now().date().isoformat()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# VIP Intel — {date_str}")
    lines.append("")

    lines.append("## Empresas")
    lines.append("")
    for c in companies:
        lines.append(f"### {c}")
        items = company_news.get(c, [])
        if not items:
            lines.append("- (sem notícias novas do dia anterior)")
        else:
            for it in items:
                src = f" ({it.source})" if it.source else ""
                lines.append(f"- {it.title}{src} — {it.link}")
        lines.append("")

    lines.append("## Pessoas")
    lines.append("")
    # Only minimal format requested elsewhere applies to lista-vips.md, not this daily file.
    # Here we still keep it lean: person + company, then bullets.
    for person, company in people:
        lines.append(f"### {person} — {company}")
        notes = linkedin_notes.get(person) or []
        if not notes:
            lines.append("- (sem atualização capturada do dia anterior)")
        else:
            for n in notes:
                lines.append(f"- {n}")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    return out_path


def main():
    now = sp_now()
    date_str, _, _ = yesterday_range_sp(now)

    companies, people = parse_vip_list(VIP_LIST)
    state = load_state()

    company_news = {}
    for c in companies:
        try:
            rss = google_news_rss(c, date_str, state)
            xml = fetch_url(rss)
            items = parse_rss_items(xml)
            items = dedupe_news(state, c, items)
            company_news[c] = items
        except Exception as e:
            company_news[c] = []

    # LinkedIn notes: scaffold; will be filled by a browser-capable agent step.
    # For now, keep empty lists to avoid adding unverified info.
    linkedin_notes = {}

    out_path = write_daily_md(date_str, companies, company_news, people, state.get("linkedin_notes", {}))

    state["last_run"] = now.isoformat()
    save_state(state)

    print(f"VIP_INTEL_OK: {out_path}")


if __name__ == "__main__":
    main()
