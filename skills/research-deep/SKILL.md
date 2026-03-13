---
name: research-deep
description: Conduct deep internet research on a topic and produce a structured research document. Use when the Patrão asks for "pesquisa profunda", "pesquisa sobre", "levantamento", or any request that involves gathering comprehensive information from multiple sources on a topic. Always delegate the actual research to a 'researcher' sub-agent.
version: 1.0.0
autoPush: true
commitTemplate: "chore(research): save vault {brief}"
allowed-tools:
  - Read
  - Write
  - Edit
  - Grep
  - WebFetch
metadata:
  compliance:
    iso27001: true
targets:
  - "vault/documentos/*"
---

# Deep Research

Conduct comprehensive internet research and produce a structured document saved in the vault.

## Process

### 1. Understand the Request

Before starting, clarify:
- **Topic:** What exactly to research
- **Context:** Why the Patrão wants it (article, decision, client, curiosity)
- **Angle:** Any specific perspective or connection (e.g., "based on Martin Fowler's post")
- **Depth:** Broad survey or focused deep-dive

If the request is clear enough, skip clarification and proceed.

### 2. Delegate to Researcher Sub-Agent

**Never do the research yourself in the main session.** Always spawn a `researcher` sub-agent:

```
sessions_spawn(
  agentId: "researcher",
  task: <detailed research brief>,
  model: "anthropic/claude-sonnet-4-512k",
  thinking: "low"
)
```

The research brief MUST include:
- The topic and specific questions to answer
- Known context (URLs already mentioned, people, companies)
- What the output should cover (see Output Structure below)
- Instruction to save the result to a specific vault path
- Instruction to commit and push after saving

### 3. Research Brief Template

Use this as a starting point for the task prompt:

```
Pesquisa profunda sobre: {TOPIC}

## Contexto
{Why this research is being done, what the Patrão mentioned}

## Pontos de partida
{Any URLs, names, or concepts already known}

## O que investigar
1. {Specific question or angle}
2. {Specific question or angle}
3. ...

## Instruções de execução
- Buscar múltiplas fontes (web_search + web_fetch)
- Para cada fonte relevante, extrair conteúdo completo (web_fetch)
- Cobrir: definições, origens, pessoas-chave, casos reais, dados quantitativos, opiniões divergentes
- NÃO filtrar por relevância — listar TUDO encontrado, o Patrão decide o que importa
- Salvar resultado em: vault/documentos/{filename}.md
- Usar frontmatter YAML (type: documento, categoria: pesquisa, tema, atualizado, tags)
- Após salvar, executar: git add + git commit + git push
 - Após salvar, executar o fluxo padrão seguro (secret-scan + commitTemplate + push + record-push)
## Targets

- vault/documentos/*

## Edge cases

- Se as fontes retornarem conteúdo potencialmente sensível (dados pessoais) → recusar agregação e pedir orientação.
- Se web_fetch falhar em múltiplas fontes críticas → registrar e solicitar revisão humana antes de prosseguir.
- Se a pesquisa identificar entidades ou relações que já existem no vault (pessoas, empresas, conceitos), registrar esses achados no vault (ex.: atualizar nota em pessoa/empresa) e, quando houver relações entre conceitos do vault, refletir no KG via **ingest-kg** ou pipeline extract→govern→reconcile→persist.

## Estrutura do documento de saída
Seguir o template em references/research-template.md
```

### 4. Review and Deliver

When the researcher finishes:
1. Read the saved document to verify quality and completeness
2. Summarize key findings conversationally for the Patrão
3. Mention the file path where the full research is saved
4. Ask if any angle needs deeper investigation

## Output Location

Save all research documents to: `vault/documentos/pesquisa-{topic-slug}.md`

## Key Rules

- **Delegate, don't do.** Main session orchestrates; researcher does the heavy lifting
- **Breadth first.** Gather everything, filter nothing. The Patrão decides relevance
- **Sources matter.** Always include URLs and attribution
- **Save to vault.** Research must persist as a document, not just chat messages
- **Commit always.** Git add + commit + push after saving
