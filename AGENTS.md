# AGENTS.md — marcia-vips-manager

## Saída (sempre)
- Relatório diário em: `vault/vips/daily/YYYY-MM-DD.md`

## Formato do relatório
1) Resumo executivo (5 bullets)
2) VIPs — Pessoas (por pessoa)
   - O que mudou / o que postou / sinais
   - Link do perfil (LinkedIn) + links de evidências
3) VIPs — Empresas (por empresa)
   - Notícias/press releases/regulatório/resultados
   - Risco/Oportunidade + 1 sugestão de ação
4) Itens para follow-up (lista curta)
5) Fontes (lista completa)

## Bio do Patrão (atualização contínua)
- Arquivo canônico: `vault/bio-do-elemar.md`.
- Se durante o monitoramento surgir um fato novo relevante sobre o Patrão (nova relação com VIP, mudança de contexto, preferência), atualizar o arquivo, o campo `atualizado` no frontmatter, e fazer commit+push.

## Fontes recomendadas (prioridade)
- **Primárias**: site da empresa, releases oficiais, reguladores.
- **LinkedIn**: para pessoas e sinais de empresa.
- **Notícias**: usar 2+ fontes quando for controverso.

## Acesso ao LinkedIn (Mac Mini, profile=openclaw)
- Para dados de pessoas (cargo atual, histórico, posts, movimentações): usar **LinkedIn**.
- Quando precisar navegar UI: usar o **Mac Mini** via browser do node com `profile="openclaw"` (já logado).
- Regras de segurança:
  - Apenas leitura/coleta. Nunca curtir, comentar, seguir, enviar mensagem.
  - Se houver bloqueio/404, registrar “(não foi possível acessar o perfil agora)”.
- Registrar no relatório: link do perfil + data/hora (SP) da observação.
