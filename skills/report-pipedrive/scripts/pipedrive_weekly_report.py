#!/usr/bin/env python3
"""Generate a weekly sales report from Pipedrive.

Reads env:
  PIPEDRIVE_DOMAIN
  PIPEDRIVE_API_TOKEN

Writes markdown report to stdout (or --out).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
import urllib.request

WORKSPACE = Path(__file__).resolve().parents[3]


@dataclass
class User:
    id: int
    name: str


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
        if start > 5000:
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


def fetch_activities(user_id: int, start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    return paged_get(
        "/activities",
        {
            "user_id": user_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )


def fetch_deals_created_in_range(user_id: int, start_date: dt.date, end_date: dt.date, status: str) -> list[dict[str, Any]]:
    # /deals does not support date filtering in endpoint; we filter by add_time.
    deals = paged_get(
        "/deals",
        {
            "user_id": user_id,
            "status": status,
            "sort": "add_time DESC",
        },
    )
    out = []
    for d in deals:
        ad = parse_date(d.get("add_time"))
        if in_range(ad, start_date, end_date):
            out.append(d)
        # early stop if sorted and below range
        if ad is not None and ad < start_date:
            break
    return out


def top_counts(items: list[dict[str, Any]], key: str, n: int = 8) -> list[tuple[str, int]]:
    c = Counter()
    for it in items:
        v = it.get(key)
        if isinstance(v, str) and v.strip():
            c[v.strip()] += 1
    return c.most_common(n)


def money_sum(deals: list[dict[str, Any]]) -> float:
    total = 0.0
    for d in deals:
        try:
            total += float(d.get("value") or 0)
        except Exception:
            pass
    return total


def stage_map() -> dict[int, dict[str, Any]]:
    stages = api_get("/stages").get("data") or []
    return {int(s["id"]): s for s in stages}


def md_money(v: float) -> str:
    # keep simple; formatting pt-BR is overkill here
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def summarize_user(user: User, start_date: dt.date, end_date: dt.date, stages: dict[int, dict[str, Any]]) -> dict[str, Any]:
    acts = fetch_activities(user.id, start_date, end_date)
    type_c = Counter([(a.get("type") or "unknown") for a in acts])
    done = sum(1 for a in acts if a.get("done"))
    open_ = len(acts) - done

    top_people = top_counts(acts, "person_name")
    top_orgs = top_counts(acts, "org_name")

    open_deals = fetch_deals_created_in_range(user.id, start_date, end_date, "open")
    won_deals = fetch_deals_created_in_range(user.id, start_date, end_date, "won")
    lost_deals = fetch_deals_created_in_range(user.id, start_date, end_date, "lost")

    stage_c = Counter([d.get("stage_id") for d in open_deals if d.get("stage_id") is not None])
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
        "activities_total": len(acts),
        "activities_done": done,
        "activities_open": open_,
        "activity_types": dict(type_c),
        "top_people": top_people,
        "top_orgs": top_orgs,
        "deals_open_new": len(open_deals),
        "deals_won_new": len(won_deals),
        "deals_lost_new": len(lost_deals),
        "open_value": money_sum(open_deals),
        "won_value": money_sum(won_deals),
        "lost_value": money_sum(lost_deals),
        "open_stage_distribution": stage_named,
    }


def render_report(start_date: dt.date, end_date: dt.date, users: list[User]) -> str:
    stages = stage_map()
    data = {u.name: summarize_user(u, start_date, end_date, stages) for u in users}

    # Simple scoring: wins + won_value weight - open activities penalty
    score = {}
    for name, d in data.items():
        score[name] = (
            d["deals_won_new"] * 10
            + (d["won_value"] / 10000.0)
            - (d["activities_open"] * 0.2)
        )

    lines: list[str] = []
    lines.append(f"# Pipedrive — Report Comercial (últimos 7 dias)\n")
    lines.append(f"**Período:** {start_date.isoformat()} → {end_date.isoformat()}\n")

    # Scoreboard
    lines.append("## Placar (comparativo rápido)\n")
    lines.append("| Pessoa | Atividades | Concluídas | Abertas | Deals abertos (novos) | Won (qtde) | Won (valor) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for name in users:
        d = data[name.name]
        lines.append(
            f"| {name.name} | {d['activities_total']} | {d['activities_done']} | {d['activities_open']} | {d['deals_open_new']} | {d['deals_won_new']} | {md_money(d['won_value'])} |"
        )
    lines.append("")

    lines.append("## Análise (o que isso está dizendo)\n")
    # rank
    ranked = sorted(score.items(), key=lambda x: x[1], reverse=True)
    lines.append("### Ranking (heurística simples)\n")
    for i, (n, s) in enumerate(ranked, 1):
        lines.append(f"{i}. **{n}** — score {s:.2f}")
    lines.append("")

    lines.append("### Leitura crítica\n")
    lines.append("- **Atividade aberta demais** normalmente é problema de higiene no CRM (não necessariamente falta de trabalho).")
    lines.append("- **Topos de funil gigantes** (muitos Suspects) sem avanço para Apresentação/Proposta indicam gargalo de qualificação ou falta de cadência de follow-up.")
    lines.append("- **Won baixo** com muito esforço pode ser ciclo longo (normal), mas também pode ser falta de next-step e proposta no tempo certo.")
    lines.append("")

    # Per-user details
    for u in users:
        d = data[u.name]
        lines.append(f"## {u.name}\n")
        lines.append("### Atividades\n")
        lines.append(f"- Total: **{d['activities_total']}** | Concluídas: **{d['activities_done']}** | Abertas: **{d['activities_open']}**")
        if d["activity_types"]:
            types = ", ".join([f"{k}={v}" for k, v in sorted(d["activity_types"].items(), key=lambda x: -x[1])])
            lines.append(f"- Tipos: {types}")
        if d["top_orgs"]:
            lines.append("- Principais orgs (por atividades):")
            for org, c in d["top_orgs"]:
                lines.append(f"  - {org} ({c})")
        if d["top_people"]:
            lines.append("- Principais pessoas (por atividades):")
            for person, c in d["top_people"]:
                lines.append(f"  - {person} ({c})")
        lines.append("")

        lines.append("### Deals (criados no período)\n")
        lines.append(f"- Open novos: **{d['deals_open_new']}** (valor: **{md_money(d['open_value'])}**)\n- Won: **{d['deals_won_new']}** (valor: **{md_money(d['won_value'])}**)\n- Lost: **{d['deals_lost_new']}** (valor: **{md_money(d['lost_value'])}**)\n")
        if d["open_stage_distribution"]:
            lines.append("- Distribuição de estágios (open):")
            for s in d["open_stage_distribution"]:
                pname = f"pipeline {s['pipeline_id']}" if s.get("pipeline_id") else ""
                lines.append(f"  - {s['stage_name']} ({pname}) — {s['count']}")
        lines.append("")

    # Hygiene / procedure
    lines.append("## Ajustes necessários no cadastro (higiene do CRM)\n")
    lines.append("O maior ganho rápido aqui é **padronizar o registro**, para que o placar reflita a realidade e permita gestão.\n")

    lines.append("### Regra 1 — Toda atividade tem que terminar em um dos dois estados\n")
    lines.append("- **Concluída (done)** quando ocorreu.\n- **Reagendada** (nova atividade criada) quando não ocorreu.\n")

    lines.append("### Regra 2 — Toda atividade precisa estar conectada a alguém\n")
    lines.append("Checklist obrigatório ao criar/editar uma atividade:")
    lines.append("1) Definir **tipo** (call/meeting/email/whatsapp etc.).")
    lines.append("2) Preencher **Pessoa** e/ou **Organização**.")
    lines.append("3) Se houver oportunidade real: vincular ao **Deal**.")
    lines.append("4) Registrar **nota curta**: contexto + próximo passo. (1–3 linhas)")
    lines.append("")

    lines.append("### Regra 3 — Deal sem próximo passo é deal morto\n")
    lines.append("Passo a passo (padrão) para manter o pipe vivo:")
    lines.append("1) Após qualquer interação relevante, abrir o deal e preencher **Next step** (ou nota) com: *o que / quem / quando*.")
    lines.append("2) Criar a **próxima atividade** (data e hora) no deal (não deixar 'em aberto').")
    lines.append("3) Atualizar **estágio** apenas quando a condição ficou verdadeira (ex.: apresentação feita, proposta enviada).")
    lines.append("4) Se travar: mover para **Parado** com motivo explícito + atividade de retomada futura.")
    lines.append("")

    lines.append("### Regra 4 — Encerramento semanal (sexta cedo)\n")
    lines.append("Checklist de 15 minutos por pessoa:")
    lines.append("1) Filtrar 'Minhas atividades' da semana e **dar baixa** no que aconteceu.")
    lines.append("2) Para cada deal open importante, garantir: **1 próxima atividade agendada**.")
    lines.append("3) Revisar deals em Suspects/Qualificados e escolher 3 para empurrar 1 etapa (não tentar empurrar todos).")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out")
    args = ap.parse_args()

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)

    users = [
        User(14234771, "Gustavo de Paula"),
        User(13839091, "Gustavo Azevedo"),
        User(13945599, "Franco Alves"),
    ]

    md = render_report(start, end, users)

    out_path = args.out
    if out_path and not os.path.isabs(out_path):
        out_path = str(WORKSPACE / out_path)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
