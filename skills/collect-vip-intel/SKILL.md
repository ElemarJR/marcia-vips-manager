---
name: collect-vip-intel
description: Coletar inteligência diária de VIPs (empresas e pessoas) a partir da meia-noite (America/Sao_Paulo): (1) notícias do dia anterior por empresa (deduplicadas e com histórico local), (2) atualizações do LinkedIn das pessoas VIP (via automação do Chrome já logado). Gerar arquivo diário no Vault (/srv/marcia-memory/vault/vips/daily/YYYY-MM-DD.md) e produzir resumo do que foi relevante para entrar no briefing da manhã.
version: 1.0.0
autoPush: true
commitTemplate: "chore(vips): daily intel {brief}"
allowed-tools:
  - Read
  - Write
  - Edit
  - Grep
metadata:
  compliance:
    iso27001: true
targets:
  - "/srv/marcia-memory/vault/vips/daily/*"
  - "/srv/marcia-memory/data/vips/vips-intel-state.json"
---

# VIP Intel (diário)

## Fonte de verdade (lista VIP)

- `MARCIA_MEMORY_REPO=/srv/marcia-memory` (canônico)
- Lista VIP: `/srv/marcia-memory/vault/vips/lista-vips.md`
  - Seção **Empresas**: lista numerada com nomes
  - Seção **Pessoas**: linhas `Pessoa — Empresa`

## Saídas

1) Arquivo diário (data do **dia anterior** em SP):
- `/srv/marcia-memory/vault/vips/daily/YYYY-MM-DD.md`

2) Estado (dedupe/histórico):
- `/srv/marcia-memory/data/vips/vips-intel-state.json`

## Execução (batch diário)

### Passo 1: Notícias (determinístico)

Rodar:

```bash
python3 skills/collect-vip-intel/scripts/vip_intel_run.py
```

Regras:
- Usar fuso `America/Sao_Paulo`.
- Buscar **apenas notícias do dia anterior**.
- Evitar repetir notícias já registradas (dedupe via state).

### Passo 2: LinkedIn (Mac Mini, `profile=openclaw`) — **SEMPRE tentar**

Regra: o `collect-vip-intel` **sempre** deve tentar coletar LinkedIn para todas as pessoas VIP.

**Como acessar:** usar o browser do node (Mac Mini) com `profile="openclaw"` (já logado).

Fluxo por pessoa em `/srv/marcia-memory/vault/vips/lista-vips.md` (linha `Pessoa — Empresa — URL`):
- Navegar para o URL.
- Extrair o **último item visível** (link + trecho curto) ou um “headline + data” quando for o que a UI permitir.
- Registrar no arquivo diário em `## Pessoas`.
- Dedupe: não repetir o mesmo `latest_link` já registrado no estado (`/srv/marcia-memory/data/vips/vips-intel-state.json`).

Regras LinkedIn:
- Apenas leitura/coleta. **Nunca** curtir, comentar, seguir, enviar mensagem.
- Se o perfil cair em 404/bloqueio, registrar como “(não foi possível acessar o perfil agora)”.

## Após editar no vault (fluxo seguro)

Se a skill alterar arquivos em `/srv/marcia-memory/vault/vips/` ou `/srv/marcia-memory/data/vips/vips-intel-state.json`: 

```bash
scripts/secret-scan.sh /srv/marcia-memory/vault/vips/ /srv/marcia-memory/data/vips/vips-intel-state.json || (echo "Secret found, abort" && exit 1)
cd /srv/marcia-memory

git add vault/vips/ data/vips/vips-intel-state.json
git commit -m "chore(vips): daily intel <brief>"
git push
scripts/record-push.sh collect-vip-intel $(git rev-parse --short HEAD) vault/vips/* data/vips/vips-intel-state.json
```

## Briefing matinal

O briefing deve ler o arquivo `/srv/marcia-memory/vault/vips/daily/YYYY-MM-DD.md` (ontem) e trazer 3–7 bullets de "o que importa".
