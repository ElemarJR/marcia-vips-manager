#!/usr/bin/env python3
"""Deep weekly commercial report from Pipedrive.

Focus: activities (topics/clients), proposals, pipeline hotspots.

Env:
  PIPEDRIVE_DOMAIN
  PIPEDRIVE_API_TOKEN

Output: Markdown.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlencode
import urllib.request

WORKSPACE = Path(__file__).resolve().parents[3]


@dataclass
class User:
    id: int
    name: str


STOPWORDS = set(
    "a o os as um uma uns umas de da do das dos para por com sem em no na nos nas e ou que "
    "é foi ser estar está estão eu você vc vocês nós nosso nossa seu sua seus suas "
    "pra pro pq porque como mais menos muito pouca pouco já ainda também".split()
)


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    domain = os.environ.get("PIPEDRIVE_DOMAIN")
    token = os.environ.get("PIPEDRIVE_API_TOKEN")
    if not domain or not token:
        raise SystemExit("Missing PIPEDRIVE_DOMAIN or PIPEDRIVE_API_TOKEN")

    base = f"https://{domain}/api/v1"
    params = dict(params or {})
    params["api_token"] = token
    url = f"{base}{path}?{urlencode(params)}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def paged_get(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    start = 0
    out: list[dict[str, Any]] = []
    while True:
        p = dict(params)
        p["start"] = start
        p.setdefault("limit", 500)
        resp = api_get(path, p)
        data = resp.get("data") or []
        out.extend(data)
        pag = (resp.get("additional_data") or {}).get("pagination") or {}
        if not pag.get("more_items_in_collection"):
            break
        start = pag.get("next_start", start + len(data))
        if start > 20000:
            break
    return out


def parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def in_range(d: dt.date | None, start: dt.date, end: dt.date) -> bool:
    return d is not None and start <= d <= end


def stage_map() -> dict[int, dict[str, Any]]:
    stages = api_get("/stages").get("data") or []
    return {int(s["id"]): s for s in stages}


def md_money(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tokenize(text: str) -> list[str]:
    # Strip HTML-ish noise that often appears in Pipedrive notes
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&nbsp;", " ", text, flags=re.I)
    text = re.sub(r"&[a-z]+;", " ", text, flags=re.I)

    text = text.lower()
    text = re.sub(r"[^a-z0-9áàâãéèêíìîóòôõúùûç_\- ]+", " ", text)
    toks = [t.strip() for t in text.split() if t.strip()]
    toks = [t for t in toks if t not in STOPWORDS and len(t) >= 3]
    # drop common html leftovers
    toks = [t for t in toks if t not in {"div", "style", "color", "rgb", "nbsp"}]
    return toks


def topics_from_activities(acts: Iterable[dict[str, Any]]) -> list[tuple[str, int]]:
    c = Counter()
    for a in acts:
        subj = (a.get("subject") or "")
        note = (a.get("note") or "")
        for t in tokenize(subj + " " + note):
            c[t] += 1
    return c.most_common(20)


def fetch_activities(user_id: int, start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    return paged_get(
        "/activities",
        {
            "user_id": user_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )


def fetch_deals(user_id: int, status: str) -> list[dict[str, Any]]:
    return paged_get(
        "/deals",
        {
            "user_id": user_id,
            "status": status,
            "sort": "update_time DESC",
        },
    )


def deals_touched_in_range(deals: list[dict[str, Any]], start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    out = []
    for d in deals:
        ud = parse_date(d.get("update_time"))
        if in_range(ud, start_date, end_date):
            out.append(d)
        # early stop (sorted desc)
        if ud is not None and ud < start_date:
            break
    return out


def deals_created_in_range(deals: list[dict[str, Any]], start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    out = []
    for d in deals:
        ad = parse_date(d.get("add_time"))
        if in_range(ad, start_date, end_date):
            out.append(d)
        if ad is not None and ad < start_date:
            break
    return out


def deal_value(d: dict[str, Any]) -> float:
    try:
        return float(d.get("value") or 0)
    except Exception:
        return 0.0


def top_counts(items: list[dict[str, Any]], key: str, n: int = 10) -> list[tuple[str, int]]:
    c = Counter()
    for it in items:
        v = it.get(key)
        if isinstance(v, str) and v.strip():
            c[v.strip()] += 1
    return c.most_common(n)


def summarize_user(user: User, start_date: dt.date, end_date: dt.date, stages: dict[int, dict[str, Any]]) -> dict[str, Any]:
    acts = fetch_activities(user.id, start_date, end_date)
    type_c = Counter([(a.get("type") or "unknown") for a in acts])
    done = sum(1 for a in acts if a.get("done"))
    open_ = len(acts) - done

    # clients from activities
    top_orgs_acts = top_counts(acts, "org_name")
    top_people_acts = top_counts(acts, "person_name")

    # topics from subject/note
    topics = topics_from_activities(acts)

    # deals: open/won/lost (touched in range)
    open_all = fetch_deals(user.id, "open")
    won_all = fetch_deals(user.id, "won")
    lost_all = fetch_deals(user.id, "lost")

    open_touched = deals_touched_in_range(open_all, start_date, end_date)
    won_touched = deals_touched_in_range(won_all, start_date, end_date)
    lost_touched = deals_touched_in_range(lost_all, start_date, end_date)

    open_created = deals_created_in_range(open_all, start_date, end_date)

    # proposals heuristic: stage contains 'Proposta' OR activity subject/note contains 'proposta'
    proposal_stage_ids = {sid for sid, s in stages.items() if "proposta" in (s.get("name") or "").lower()}
    open_in_proposal = [d for d in open_all if d.get("stage_id") in proposal_stage_ids]

    proposal_mentions = 0
    for a in acts:
        if re.search(r"\bpropost", (a.get("subject") or "") + " " + (a.get("note") or ""), re.I):
            proposal_mentions += 1

    # top deals by value (open touched)
    top_deals = sorted(open_touched, key=deal_value, reverse=True)[:10]
    top_deals_slim = []
    for d in top_deals:
        sid = d.get("stage_id")
        s = stages.get(int(sid)) if sid is not None else None
        top_deals_slim.append(
            {
                "title": d.get("title"),
                "org": d.get("org_name"),
                "person": d.get("person_name"),
                "value": deal_value(d),
                "stage": (s.get("name") if s else str(sid)),
                "next_activity_date": d.get("next_activity_date"),
                "next_activity_subject": d.get("next_activity_subject"),
                "link": d.get("url"),
            }
        )

    stage_c = Counter([d.get("stage_id") for d in open_touched if d.get("stage_id") is not None])
    stage_named = []
    for sid, cnt in stage_c.most_common():
        s = stages.get(int(sid)) if sid is not None else None
        stage_named.append(
            {
                "stage_id": sid,
                "stage_name": (s.get("name") if s else str(sid)),
                "pipeline_id": (s.get("pipeline_id") if s else None),
                "count": cnt,
            }
        )

    return {
        "activities": {
            "total": len(acts),
            "done": done,
            "open": open_,
            "types": dict(type_c),
            "top_orgs": top_orgs_acts,
            "top_people": top_people_acts,
            "topics": topics,
            "proposal_mentions": proposal_mentions,
        },
        "deals": {
            "open_created": len(open_created),
            "open_touched": len(open_touched),
            "open_value_touched": sum(deal_value(d) for d in open_touched),
            "open_in_proposal": len(open_in_proposal),
            "won_touched": len(won_touched),
            "won_value_touched": sum(deal_value(d) for d in won_touched),
            "lost_touched": len(lost_touched),
            "lost_value_touched": sum(deal_value(d) for d in lost_touched),
            "stage_distribution_touched": stage_named,
            "top_deals": top_deals_slim,
        },
    }


def render(start_date: dt.date, end_date: dt.date, users: list[User]) -> str:
    stages = stage_map()
    data = {u.name: summarize_user(u, start_date, end_date, stages) for u in users}

    lines: list[str] = []
    lines.append("# Pipedrive — Report Comercial (deep) — últimos 7 dias")
    lines.append("")
    lines.append(f"**Período:** {start_date.isoformat()} → {end_date.isoformat()}")
    lines.append("")

    lines.append("## Placar")
    lines.append("")
    lines.append("| Pessoa | Atividades | Concluídas | Abertas | Deals tocados | Valor (deals tocados) | Won (qtde) | Won (valor) | Deals em Proposta |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for u in users:
        d = data[u.name]
        a = d["activities"]
        dl = d["deals"]
        lines.append(
            f"| {u.name} | {a['total']} | {a['done']} | {a['open']} | {dl['open_touched']} | {md_money(dl['open_value_touched'])} | {dl['won_touched']} | {md_money(dl['won_value_touched'])} | {dl['open_in_proposal']} |"
        )
    lines.append("")

    lines.append("## Principais assuntos (a partir de subject/note das atividades)")
    lines.append("")
    for u in users:
        topics = data[u.name]["activities"]["topics"]
        top = ", ".join([f"{t}({c})" for t, c in topics[:12]]) if topics else "(sem dados)"
        lines.append(f"- **{u.name}:** {top}")
    lines.append("")

    lines.append("## Ajustes de cadastro (o que está quebrando a visibilidade)")
    lines.append("")
    lines.append("### Procedimento padrão (passo a passo) — após qualquer reunião/call/whats")
    lines.append("1) Abrir a **atividade** e marcar **Done** (se ocorreu) ou **Reagendar** (se não ocorreu).")
    lines.append("2) Garantir vínculo: **Pessoa** e/ou **Organização** preenchidas.")
    lines.append("3) Se for oportunidade: vincular ao **Deal**.")
    lines.append("4) No Deal, registrar **Next step (o que/quem/quando)** e criar a **próxima atividade**.")
    lines.append("5) Se o deal travou: mover para **Parado** com motivo + data de retomada.")
    lines.append("")

    # per-user
    for u in users:
        d = data[u.name]
        a = d["activities"]
        dl = d["deals"]
        lines.append(f"## {u.name}")
        lines.append("")
        lines.append("### Clientes com quem falou (pela atividade registrada)")
        if a["top_orgs"]:
            for org, c in a["top_orgs"][:10]:
                lines.append(f"- {org} ({c})")
        else:
            lines.append("- (sem orgs preenchidas nas atividades)")
        lines.append("")

        lines.append("### Volume e disciplina")
        lines.append(f"- Atividades: {a['total']} (done={a['done']}, abertas={a['open']})")
        lines.append(f"- Tipos: {', '.join([f'{k}={v}' for k,v in sorted(a['types'].items(), key=lambda x:-x[1])])}")
        lines.append(f"- Menções a proposta (em atividades): {a['proposal_mentions']}")
        lines.append("")

        lines.append("### Pipeline (deals tocados na semana)")
        lines.append(f"- Deals open tocados: {dl['open_touched']} (valor total: {md_money(dl['open_value_touched'])})")
        lines.append(f"- Won tocados: {dl['won_touched']} ({md_money(dl['won_value_touched'])})")
        lines.append(f"- Lost tocados: {dl['lost_touched']} ({md_money(dl['lost_value_touched'])})")
        lines.append(f"- Deals em estágio de Proposta (open, global): {dl['open_in_proposal']}")
        if dl["stage_distribution_touched"]:
            lines.append("- Distribuição por estágio (open tocados):")
            for s in dl["stage_distribution_touched"][:10]:
                pid = s.get("pipeline_id")
                pname = f"pipeline {pid}" if pid is not None else ""
                lines.append(f"  - {s['stage_name']} ({pname}) — {s['count']}")
        lines.append("")

        lines.append("### Top deals por valor (open tocados)")
        if dl["top_deals"]:
            for td in dl["top_deals"]:
                nexts = td.get("next_activity_date") or "(sem próxima atividade)"
                lines.append(f"- {td['org']} — {td['title']} — **{md_money(td['value'])}** — estágio: {td['stage']} — next: {nexts}")
        else:
            lines.append("- (nenhum deal open tocado na semana)")
        lines.append("")

        lines.append("### O que ajustar (checklist específico)")
        if a["open"] > 0:
            lines.append(f"- **Zerar {a['open']} atividades abertas**: concluir ou reagendar (sem backlog).")
        if not a["top_orgs"]:
            lines.append("- **Atividades sem org/pessoa**: padronizar preenchimento (senão não dá para saber 'com quem falou').")
        # next activity missing heuristic via top_deals missing next
        missing_next = sum(1 for td in dl["top_deals"] if not td.get("next_activity_date"))
        if missing_next:
            lines.append(f"- **{missing_next} top-deals sem próxima atividade**: criar next-step + agendar follow-up.")
        if a["open"] == 0 and missing_next == 0:
            lines.append("- Mantém: higiene boa. Próximo passo é aumentar avanço de estágio (qualificar/proposta).")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)

    users = [
        User(14234771, "Gustavo de Paula"),
        User(13839091, "Gustavo Azevedo"),
        User(13945599, "Franco Alves"),
    ]

    md = render(start, end, users)
    out_path = args.out
    if not os.path.isabs(out_path):
        out_path = str(WORKSPACE / out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
