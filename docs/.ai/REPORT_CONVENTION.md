# Convenção de relatórios — Expense Tracker

Toda análise, pesquisa, *trade-off study* ou recomendação produzida pela IA neste projeto deve seguir esta convenção. O objetivo é ter rastreabilidade total entre **decisão registrada → relatório que a justificou → fontes que embasaram o relatório**.

## Local

```
docs/.ai/reports/
└── NNN_NOME_DESCRITIVO/
    ├── NNN_NOME_DESCRITIVO.md     # O relatório
    └── contexts/                  # Fontes de pesquisa web em .md
        ├── 01_<fonte_curta>.md
        ├── 02_<fonte_curta>.md
        └── ...
```

## Regras de numeração

- `NNN` é um índice **monotônico crescente**, com três dígitos.
- Começa em `000`. O próximo é `001`, depois `002`, etc.
- Não há "atalhos" nem reservas: o próximo número disponível é sempre `max(NNN) + 1`.
- O nome `NOME_DESCRITIVO` é em `snake_case`, em português, curto e específico (ex.: `aprimoramento_chatbot`, `analise_queries_backend`, `arquitetura_agentes`).
- O arquivo principal **repete** o nome da pasta: `NNN_NOME_DESCRITIVO.md`.

## Conteúdo mínimo do relatório

Todo `NNN_NOME_DESCRITIVO.md` deve conter, no mínimo:

1. **Título e contexto** — Qual problema/decisão motivou o relatório.
2. **Resumo executivo (TL;DR)** — 5 a 10 linhas, com a recomendação final clara.
3. **Premissas e restrições** — Inclui o cenário do Expense Tracker (Django + HTMX + React islands, Supabase/pgvector, finanças familiares pessoais, pt-BR, PydanticAI provider-agnóstico, TDD obrigatório).
4. **Alternativas avaliadas** — Tabela ou lista com critérios.
5. **Análise** — Comparações, riscos, custos, complexidades.
6. **Recomendação** — Decisão proposta, motivos e próximos passos.
7. **Referências** — Links externos **e** lista dos arquivos de `contexts/` usados.

## Regras para `contexts/`

- Toda fonte web relevante para o relatório deve ser **salva como Markdown** dentro de `contexts/`.
- Nome do arquivo: `NN_<slug_curto>.md` (ex.: `01_pydantic_ai_multiagent_2026.md`).
- Cabeçalho obrigatório:

  ```markdown
  ---
  source_url: https://exemplo.com/artigo
  fetched_at: YYYY-MM-DD
  publisher: <site/autor>
  used_for: <em qual decisão/seção do relatório este texto entrou>
  ---
  ```

- Conteúdo: o texto extraído da página (ou um resumo objetivo) em PT-BR ou no idioma original — desde que o relatório principal traduza/cite o trecho usado.
- Se a fonte for um PDF/artigo científico, salvar o `.md` com a citação completa e os trechos relevantes; o PDF original pode ser referenciado por URL ou DOI.

## Por que essa convenção existe

Decisões de arquitetura (modelo de IA, padrões de agentes, queries de dados, segurança) têm impacto duradouro e precisam ser auditáveis. Sem fontes salvas localmente, links quebram, páginas mudam e a base da decisão se perde. A pasta `contexts/` congela o estado das fontes na data da decisão.

## Exemplo

```
docs/.ai/reports/
└── 000_aprimoramento_chatbot/
    ├── 000_aprimoramento_chatbot.md
    └── contexts/
        ├── 01_pydantic_ai_multiagent_2026.md
        ├── 02_orchestrator_worker_pattern.md
        └── 03_prompt_injection_db_tools.md
```
