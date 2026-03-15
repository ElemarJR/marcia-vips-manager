#!/usr/bin/env python3
"""Consultoria pipeline weekly overview (read-only).

Generates summary for a given pipeline and date range:
- Deals created in range
- Deals updated in range (touched)
- Stage changes in range (via /deals/{id}/flow)
- Activities in range linked to those deals

Env:
  PIPEDRIVE_DOMAIN
  PIPEDRIVE_API_TOKEN

Usage:
  python3 skills/report-pipedrive/scripts/pipedrive_consultoria_overview.py \
    --pipeline-id 8 --start 2026-03-08 --end 2026-03-14

Outputs markdown to stdout (or --out).
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


TEAM_CONSULTORIA = [
    User(13945599, "Franco Alves"),
    User(13839091, "Gustavo Azevedo"),
    User(14234771, "Gustavo de Paula"),
]


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
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def paged_get(path: str, params: dict[str, Any], hard_limit: int = 20000) -> list[dict[str, Any]]:
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
        if start > hard_limit:
            break
    return out


def parse_dt(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    # Pipedrive times are ISO-ish: 2026-03-14 12:34:56 or 2026-03-14T...
    try:
        s2 = s.replace("T", " ")
        if "+" in s2:
            s2 = s2.split("+")[0]
        if "Z" in s2:
            s2 = s2.replace("Z", "")
        if len(s2) == 10:
            return dt.datetime.fromisoformat(s2 + " 00:00:00")
        return dt.datetime.fromisoformat(s2)
    except Exception:
        return None


def in_range(d: dt.datetime | None, start: dt.datetime, end: dt.datetime) -> bool:
    return d is not None and start <= d <= end


def stage_map() -> dict[int, dict[str, Any]]:
    stages = api_get("/stages").get("data") or []
    return {int(s["id"]): s for s in stages}


def users_map() -> dict[int, str]:
    users = api_get("/users").get("data") or []
    out: dict[int, str] = {}
    for u in users:
        try:
            out[int(u["id"])] = u.get("name") or str(u.get("id"))
        except Exception:
            continue
    return out


def md_money(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def deal_value(d: dict[str, Any]) -> float:
    try:
        return float(d.get("value") or 0)
    except Exception:
        return 0.0


def fetch_deals_in_pipeline(pipeline_id: int, status: str) -> list[dict[str, Any]]:
    # /deals supports pipeline_id filter in Pipedrive; if not, we will fallback to client-side filtering.
    deals = paged_get(
        "/deals",
        {
            "status": status,
            "pipeline_id": pipeline_id,
            "sort": "update_time DESC",
        },
        hard_limit=20000,
    )
    if deals and all(d.get("pipeline_id") == pipeline_id for d in deals if d.get("pipeline_id") is not None):
        return deals
    # fallback filter
    return [d for d in deals if d.get("pipeline_id") == pipeline_id]


def fetch_deal_flow(deal_id: int) -> list[dict[str, Any]]:
    resp = api_get(f"/deals/{deal_id}/flow")
    return resp.get("data") or []


def fetch_activities_for_user(user_id: int, start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    return paged_get(
        "/activities",
        {
            "user_id": user_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        hard_limit=20000,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline-id", type=int, required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--out")
    ap.add_argument("--max-flow", type=int, default=120, help="max deals to inspect flow")
    args = ap.parse_args()

    start_d = dt.date.fromisoformat(args.start)
    end_d = dt.date.fromisoformat(args.end)
    start = dt.datetime.combine(start_d, dt.time.min)
    end = dt.datetime.combine(end_d, dt.time.max)

    stages = stage_map()
    users = users_map()

    # Deals (open + won + lost) in pipeline
    open_deals = fetch_deals_in_pipeline(args.pipeline_id, "open")
    won_deals = fetch_deals_in_pipeline(args.pipeline_id, "won")
    lost_deals = fetch_deals_in_pipeline(args.pipeline_id, "lost")
    all_deals = open_deals + won_deals + lost_deals

    def touched(d: dict[str, Any]) -> bool:
        return in_range(parse_dt(d.get("update_time")), start, end)

    def created(d: dict[str, Any]) -> bool:
        return in_range(parse_dt(d.get("add_time")), start, end)

    touched_deals = [d for d in all_deals if touched(d)]
    created_deals = [d for d in all_deals if created(d)]

    # Stage changes via flow (sample/limited)
    stage_changes: list[dict[str, Any]] = []
    for d in touched_deals[: args.max_flow]:
        deal_id = int(d["id"])
        try:
            flow = fetch_deal_flow(deal_id)
        except Exception:
            continue
        for ev in flow:
            t = parse_dt(ev.get("timestamp"))
            if not in_range(t, start, end):
                continue
            data = ev.get("data") or {}
            field_key = data.get("field_key")
            if field_key not in {"stage_id", "pipeline_id"}:
                continue
            if field_key == "stage_id":
                new = data.get("new_value")
                old = data.get("old_value")
                try:
                    new_i = int(new) if new is not None and str(new).strip() != "" else None
                    old_i = int(old) if old is not None and str(old).strip() != "" else None
                except Exception:
                    new_i, old_i = None, None
                stage_changes.append(
                    {
                        "timestamp": ev.get("timestamp"),
                        "user_id": data.get("user_id"),
                        "deal_id": deal_id,
                        "deal_title": d.get("title"),
                        "org": d.get("org_name"),
                        "person": d.get("person_name"),
                        "old_stage": stages.get(old_i, {}).get("name") if old_i else str(old),
                        "new_stage": stages.get(new_i, {}).get("name") if new_i else str(new),
                    }
                )

    # Activities in range by team, filtered to those deals
    deal_ids = {int(d["id"]) for d in all_deals}
    activities: list[dict[str, Any]] = []
    for u in TEAM_CONSULTORIA:
        try:
            activities.extend(fetch_activities_for_user(u.id, start_d, end_d))
        except Exception:
            continue
    activities = [a for a in activities if a.get("deal_id") and int(a.get("deal_id")) in deal_ids]

    # Summaries
    stage_changes_sorted = sorted(stage_changes, key=lambda x: (x.get("timestamp") or ""))

    # Map deals by id
    deals_by_id = {int(d["id"]): d for d in all_deals}

    def _name_from_user_field(v: Any) -> tuple[int | None, str | None]:
        """Return (id, name) from Pipedrive user-like field.

        Pipedrive may return an int id or an object {id,name,...}.
        """
        if isinstance(v, dict):
            vid = v.get("id") or v.get("value")
            name = v.get("name")
            try:
                vid_i = int(vid) if vid is not None else None
            except Exception:
                vid_i = None
            return vid_i, (str(name) if name else None)
        try:
            return (int(v), None)
        except Exception:
            return (None, None)

    # Executor bucket: who performed the action (activity user, flow data.user_id, deal creator)
    def executor_name_from_user_id(uid: Any) -> str:
        uid_i, name = _name_from_user_field(uid)
        if name:
            return name
        if uid_i is not None and uid_i in users:
            return users[uid_i]
        return f"user_id:{uid_i}" if uid_i is not None else "(sem executor)"

    def executor_bucket(name: str) -> str:
        if name in {"Franco Alves", "Gustavo Azevedo", "Gustavo de Paula"}:
            return name
        return name

    def executor_for_deal_created(d: dict[str, Any]) -> str:
        # Prefer creator_user_id (who created). Fallback to deal owner (user_id)
        return executor_bucket(executor_name_from_user_id(d.get("creator_user_id") or d.get("user_id")))

    def executor_for_activity(a: dict[str, Any]) -> str:
        # user_id is the performer/owner of the activity
        return executor_bucket(executor_name_from_user_id(a.get("user_id") or a.get("user_name")))

    def executor_for_stage_change(ev: dict[str, Any]) -> str:
        return executor_bucket(executor_name_from_user_id(ev.get("user_id")))

    act_done = sum(1 for a in activities if a.get("done"))

    # New deals list
    created_sorted = sorted(created_deals, key=lambda d: d.get("add_time") or "")

    # Markdown
    lines: list[str] = []
    lines.append(f"# Overview — Funil Consultoria/Assessoria (pipeline {args.pipeline_id})")
    lines.append("")
    lines.append(f"**Período:** {start_d.isoformat()} → {end_d.isoformat()}")
    lines.append("")

    # Pre-group by owner
    deals_new_by_exec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deals_touched_by_exec: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for d in created_sorted:
        deals_new_by_exec[executor_for_deal_created(d)].append(d)

    # "tocados" não tem executor claro só por update_time; vamos atribuir ao *owner do deal*
    # para manter a contagem útil, mas mantendo o agrupamento principal por executor.
    for d in touched_deals:
        # touched is a deal property; attribute to deal owner (user_id)
        deals_touched_by_exec[executor_bucket(executor_name_from_user_id(d.get("user_id")))].append(d)

    stage_changes_by_exec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in stage_changes_sorted:
        stage_changes_by_exec[executor_for_stage_change(ev)].append(ev)

    activities_by_exec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in activities:
        activities_by_exec[executor_for_activity(a)].append(a)

    # Executor ordering: prefer consultoria team names first
    preferred = ["Franco Alves", "Gustavo Azevedo", "Gustavo de Paula"]
    execs: list[str] = []
    for p in preferred:
        if p in deals_new_by_exec or p in deals_touched_by_exec or p in stage_changes_by_exec or p in activities_by_exec:
            execs.append(p)
    for o in sorted(set(list(deals_new_by_exec.keys()) + list(deals_touched_by_exec.keys()) + list(stage_changes_by_exec.keys()) + list(activities_by_exec.keys()))):
        if o not in execs:
            execs.append(o)

    lines.append("## Resumo (por executor)")
    lines.append("")
    lines.append("| Executor | Deals novos | Deals tocados* | Mudanças de estágio | Atividades | Ativ. done | Ativ. abertas |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for o in execs:
        acts = activities_by_exec.get(o, [])
        done = sum(1 for a in acts if a.get("done"))
        lines.append(
            f"| {o} | {len(deals_new_by_exec.get(o, []))} | {len(deals_touched_by_exec.get(o, []))} | {len(stage_changes_by_exec.get(o, []))} | {len(acts)} | {done} | {len(acts)-done} |"
        )
    lines.append("")
    lines.append("\n\\*Obs.: *Deals tocados* é por update_time do deal; quando não dá para inferir executor, eu atribuo ao **owner do deal** só para não perder a leitura de volume.\n")

    lines.append("## Detalhe por executor")
    lines.append("")
    for o in execs:
        lines.append(f"### {o}\n")

        lines.append("**Deals novos (criados no período)**")
        nd = deals_new_by_exec.get(o, [])
        if not nd:
            lines.append("- (nenhum)")
        else:
            for d in sorted(nd, key=lambda d: d.get("add_time") or "")[:30]:
                sid = d.get("stage_id")
                sname = stages.get(int(sid), {}).get("name") if sid is not None else "(sem estágio)"
                lines.append(
                    f"- {d.get('add_time','')[:16]} — **{d.get('title')}** — {d.get('org_name') or ''} — estágio: {sname} — valor: {md_money(deal_value(d))}"
                )
            if len(nd) > 30:
                lines.append(f"- … (+{len(nd)-30} outros)")
        lines.append("")

        lines.append("**Mudanças de estágio (quando mudou de etapa)**")
        sc = stage_changes_by_exec.get(o, [])
        if not sc:
            lines.append("- (nenhuma)")
        else:
            for ev in sorted(sc, key=lambda x: (x.get("timestamp") or ""))[:80]:
                lines.append(
                    f"- {ev['timestamp'][:16]} — **{ev['deal_title']}** ({ev.get('org') or ''}) — {ev.get('old_stage')} → **{ev.get('new_stage')}**"
                )
            if len(sc) > 80:
                lines.append(f"- … (+{len(sc)-80} outras)")
        lines.append("")

        lines.append("**Atividades (ligadas aos deals do funil)**")
        acts = activities_by_exec.get(o, [])
        if not acts:
            lines.append("- (nenhuma)")
        else:
            activities_sorted = sorted(acts, key=lambda a: (a.get("due_date") or "", a.get("due_time") or ""))
            for a in activities_sorted[:60]:
                when = (a.get("due_date") or "") + (" " + (a.get("due_time") or "") if a.get("due_time") else "")
                done = "done" if a.get("done") else "open"
                lines.append(
                    f"- {when.strip()} — [{done}] {a.get('type') or ''} — {a.get('subject') or ''} — deal: {a.get('deal_title') or a.get('deal_id')}"
                )
            if len(activities_sorted) > 60:
                lines.append(f"- … (+{len(activities_sorted)-60} outras)")
        lines.append("")

    md = "\n".join(lines).strip() + "\n"

    if args.out:
        out_path = args.out
        if not os.path.isabs(out_path):
            out_path = str(WORKSPACE / out_path)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(md, encoding="utf-8")
    else:
        print(md)

    return 0
    lines.append("")
    if not created_sorted:
        lines.append("- (nenhum)")
    else:
        for d in created_sorted[:30]:
            sid = d.get("stage_id")
            sname = stages.get(int(sid), {}).get("name") if sid is not None else "(sem estágio)"
            lines.append(
                f"- {d.get('add_time','')[:16]} — **{d.get('title')}** — {d.get('org_name') or ''} — estágio: {sname} — valor: {md_money(deal_value(d))}"
            )
        if len(created_sorted) > 30:
            lines.append(f"- … (+{len(created_sorted)-30} outros)")
    lines.append("")

    lines.append("## Movimentações de estágio (quando mudou de etapa)")
    lines.append("")
    if not stage_changes_sorted:
        lines.append("- (nenhuma detectada / ou sem permissões de flow)")
    else:
        for ev in stage_changes_sorted[:80]:
            lines.append(
                f"- {ev['timestamp'][:16]} — **{ev['deal_title']}** ({ev.get('org') or ''}) — {ev.get('old_stage')} → **{ev.get('new_stage')}**"
            )
        if len(stage_changes_sorted) > 80:
            lines.append(f"- … (+{len(stage_changes_sorted)-80} outras)")
    lines.append("")

    lines.append("## Atividades (ligadas aos deals do funil)")
    lines.append("")
    if not activities:
        lines.append("- (nenhuma)")
    else:
        # show a compact list
        activities_sorted = sorted(activities, key=lambda a: (a.get("due_date") or "", a.get("due_time") or ""))
        for a in activities_sorted[:60]:
            when = (a.get("due_date") or "") + (" " + (a.get("due_time") or "") if a.get("due_time") else "")
            done = "done" if a.get("done") else "open"
            lines.append(
                f"- {when.strip()} — {a.get('user_name') or ''} — [{done}] {a.get('type') or ''} — {a.get('subject') or ''} — deal: {a.get('deal_title') or a.get('deal_id')}"
            )
        if len(activities_sorted) > 60:
            lines.append(f"- … (+{len(activities_sorted)-60} outras)")
    lines.append("")

    md = "\n".join(lines).strip() + "\n"

    if args.out:
        out_path = args.out
        if not os.path.isabs(out_path):
            out_path = str(WORKSPACE / out_path)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(md, encoding="utf-8")
    else:
        print(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
