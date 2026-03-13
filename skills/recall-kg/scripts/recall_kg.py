#!/usr/bin/env python3
"""Recall from KG memory.

Steps:
1) Embed query
2) Top-k chunk search by cosine similarity
3) Map matched chunks -> evidence -> entities (best-effort)
4) Expand 1-2 hops in relations via recursive CTE
5) Re-rank by recency/confidence (v1: simple score)

Note: vector search is performed in Python (no sqlite vector extension required).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'kg-lib'))

from kg_lib import connect, ensure_schema, embed_text, cosine_sim, EMBED_DIMS


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--query', required=True)
    ap.add_argument('--topk', type=int, default=8)
    ap.add_argument('--hops', type=int, default=2)
    return ap.parse_args()


def main():
    args = parse_args()
    conn = connect()
    ensure_schema(conn)
    cur = conn.cursor()

    qemb = embed_text(args.query)

    # Load candidate chunks (accepted only)
    cur.execute("SELECT id, kind, ref_type, ref_id, text, embedding, confidence, created_at FROM chunks WHERE status='accepted'")
    rows = cur.fetchall()

    scored: List[Tuple[float, dict]] = []
    for r in rows:
        emb = r['embedding']
        if not emb:
            continue
        sim = cosine_sim(qemb, emb)
        conf = float(r['confidence'] or 0.5)
        score = sim * 0.8 + conf * 0.2
        scored.append((score, dict(r)))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = []
    for _, d in scored[: args.topk]:
        d = dict(d)
        # embedding is bytes; remove from JSON output
        d.pop('embedding', None)
        top.append(d)

    # Graph expansion: start from concepts mentioned in evidence linked to matched sources (best-effort)
    # For v1 we expand from any concept with evidence referencing the same source_id as the chunk.
    seed_concepts = set()
    for ch in top:
        if ch.get('ref_type') == 'source':
            sid = ch.get('ref_id')
            cur.execute("SELECT entity_id FROM evidence WHERE entity_type='concept' AND source_id=?", (sid,))
            seed_concepts.update([x['entity_id'] for x in cur.fetchall()])

    # recursive expansion (hops)
    expanded_concepts = set(seed_concepts)
    expanded_relations = []

    if seed_concepts and args.hops > 0:
        placeholders = ",".join(["?"] * len(seed_concepts))
        # recursive CTE expand both directions up to hops
        q = f"""
        WITH RECURSIVE
        seeds(id) AS (VALUES {','.join(['(?)']*len(seed_concepts))}),
        walk(src, pred, dst, depth) AS (
          SELECT r.src_concept_id, r.predicate, r.dst_concept_id, 1
          FROM relations r
          JOIN seeds s ON s.id = r.src_concept_id OR s.id = r.dst_concept_id
          WHERE r.status='accepted'
          UNION ALL
          SELECT r2.src_concept_id, r2.predicate, r2.dst_concept_id, w.depth+1
          FROM relations r2
          JOIN walk w ON w.dst = r2.src_concept_id OR w.src = r2.dst_concept_id
          WHERE r2.status='accepted' AND w.depth < ?
        )
        SELECT src, pred, dst, depth FROM walk;
        """
        params = list(seed_concepts) + [args.hops]
        cur.execute(q, params)
        for row in cur.fetchall():
            expanded_relations.append(dict(row))
            expanded_concepts.add(row['src'])
            expanded_concepts.add(row['dst'])

    # fetch concepts
    concepts = []
    if expanded_concepts:
        placeholders = ",".join(["?"] * len(expanded_concepts))
        cur.execute(
            f"SELECT id, namespace, canonical_name, description, confidence, status, updated_at FROM concepts WHERE id IN ({placeholders})",
            list(expanded_concepts),
        )
        concepts = [dict(r) for r in cur.fetchall()]

    # fetch relations details
    relations = []
    if expanded_relations:
        # map by (src,pred,dst)
        for er in expanded_relations:
            cur.execute(
                "SELECT id, src_concept_id, predicate, dst_concept_id, qualifiers_json, confidence, status, updated_at FROM relations WHERE src_concept_id=? AND predicate=? AND dst_concept_id=? AND status='accepted' LIMIT 1",
                (er['src'], er['pred'], er['dst']),
            )
            rr = cur.fetchone()
            if rr:
                relations.append(dict(rr))

    context_pack = {
        'query': args.query,
        'chunks': top,
        'seed_concepts': sorted(seed_concepts),
        'concepts': concepts,
        'relations': relations,
    }

    conn.close()
    print(json.dumps(context_pack, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
