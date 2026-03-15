---
name: report-pipedrive
description: Consulta e relatórios do Pipedrive via API (somente leitura). Use quando precisar de informação comercial, pipeline, deals, relatório semanal ou diagnóstico do CRM. Nunca editar/escrever no Pipedrive salvo pedido explícito do Patrão.
version: 1.0.0
autoPush: true
commitTemplate: "chore(pipedrive): {brief}"
allowed-tools:
  - Read
  - Write
  - Edit
  - Grep
metadata:
  compliance:
    iso27001: true
targets:
  - "vault/documentos/comercial/*"
---

# Report Pipedrive

Acesso ao Pipedrive **somente via API** (leitura/consulta/relatórios). Credenciais em `~/.openclaw/secrets.env`: `PIPEDRIVE_DOMAIN`, `PIPEDRIVE_API_TOKEN`.

## Quando usar

- Patrão perguntar sobre pipeline, deals, atividades, relatório comercial.
- Gerar relatório semanal (padrão: sexta; cron ou sob demanda).
- Diagnóstico de higiene do CRM (atividades abertas, deals sem next step).
- Racional de resposta (MEMORY.md): informação comercial não encontrada no Vault/KG → usar esta skill para consultar API.

Se a operação usar ou cruzar informações que estão no vault (ex.: deals com empresas/pessoas do vault), atualizar o vault com o resultado (novos dados, correções, metadados) e em seguida executar o fluxo de commit+push.

## Scripts

Executar a partir da raiz do workspace.

### pipedrive.py — consultas pontuais (JSON)

```bash
python3 skills/report-pipedrive/scripts/pipedrive.py me
python3 skills/report-pipedrive/scripts/pipedrive.py pipelines
python3 skills/report-pipedrive/scripts/pipedrive.py stages
python3 skills/report-pipedrive/scripts/pipedrive.py deals-recent [--limit N]
```

### pipedrive_weekly_report.py — relatório resumido (7 dias)

Saída: markdown (stdout ou `--out`).

```bash
python3 skills/report-pipedrive/scripts/pipedrive_weekly_report.py [--days 7] [--out vault/documentos/comercial/pipedrive-report-YYYY-MM-DD.md]
```

### pipedrive_weekly_report_deep.py — relatório detalhado (7 dias)

Foco: atividades, assuntos, propostas, top deals. Exige `--out`.

```bash
python3 skills/report-pipedrive/scripts/pipedrive_weekly_report_deep.py [--days 7] --out vault/documentos/comercial/pipedrive-report-deep-YYYY-MM-DD.md
```

## Após salvar relatório no vault

Quando a execução gravar relatório no vault (ex.: `--out vault/documentos/comercial/pipedrive-report-YYYY-MM-DD.md`):

```bash
scripts/secret-scan.sh vault/documentos/comercial/* || (echo "Secret found, abort" && exit 1)
cd /srv/marcia-memory

git add vault/documentos/comercial/
git commit -m "chore(pipedrive): report"
git push
scripts/record-push.sh report-pipedrive $(git rev-parse --short HEAD) vault/documentos/comercial/*
```

O push ocorre quando há escrita em paths versionados (vault/documentos/comercial/*).

## Regra operacional

**Nunca editar/escrever dados no Pipedrive** (somente leitura/consulta/relatórios), a menos que o Patrão peça explicitamente. Ver MEMORY.md § Pipedrive.

## Relatório semanal (cron)

Se houver cron de relatório semanal (ex.: sexta de manhã), acionar esta skill: rodar `pipedrive_weekly_report.py` ou `pipedrive_weekly_report_deep.py`, salvar em `vault/documentos/comercial/` e enviar/entregar conforme fluxo combinado.
