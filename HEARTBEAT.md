# HEARTBEAT.md — marcia-vips-manager

Objetivo: manter a rotina de VIPs rodando sozinha, para liberar a Márcia principal.

## Rotina diária (SP)

1) **Gerar intel do dia anterior**
- Rodar a skill `collect-vip-intel`.
- Garantir que o output foi gerado em `vault/vips/daily/YYYY-MM-DD.md`.
- Atualizar estado em `vault/_estado/vips-intel-state.json`.

2) **Checklist de qualidade (rápido)**
- Pessoas: tem LinkedIn para todas as pessoas VIP (ou mensagem explícita “aguardando aba anexada”)?
- Empresas: tem pelo menos 1–3 links por empresa quando houver notícia no dia?
- Dedupe ok: sem repetir links do dia anterior.

3) **Resumo para briefing**
- Produzir 3–7 bullets do que importa (mudança de cargo, risco, sinal de compra, crise, resultado, movimento concorrencial).
- Nunca colar a lista bruta no briefing.

## LinkedIn (obrigatório)
- Usar **Mac Mini** via browser do node com `profile="openclaw"` (já logado).

## Limites
- Não curtir/comentar/seguir/enviar mensagem.
- Não enviar email.
- Não agir em grupos.
