---
name: recall-kg
description: Recall context from the persistent KG memory using vector retrieval over chunks plus 1–2 hop graph expansion (recursive CTE). Use before answering to enrich context with user-specific entities, decisions, preferences.
version: 1.0.0
autoPush: false
commitTemplate: "chore(kg): n/a"
allowed-tools:
  - Read
  - Grep
metadata:
  compliance:
    iso27001: true
targets: []
---

# Recall KG

## Run

```bash
python3 skills/recall-kg/scripts/recall_kg.py --query "..." --topk 8 --hops 2
```

Output: context_pack JSON (concepts, relations, evidence excerpts, matched chunks).
