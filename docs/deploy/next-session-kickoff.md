# Kickoff — próxima sessão: "backlog maior" (CI/CD, PWA→Android, hardening)

> Cole o conteúdo abaixo (ou aponte a sessão nova para este arquivo) para continuar o projeto.

Você vai continuar o projeto expense_tracker_v2 (Django 6 + HTMX + React islands,
finanças pessoais, pt-BR). Objetivo desta sessão: avançar o "backlog maior" de
produção — CI/CD, PWA→app Android, e hardening.

## Antes de qualquer coisa, leia (nesta ordem)
1. A memória do projeto (carregada automaticamente em MEMORY.md), em especial:
   - `project_status.md` — estado atual, o que está pronto e deployado
   - `reference_deploy.md` — fatos de deploy (GCP, Supabase, gotchas)
   - `reference_local_db.md` — testes/dev usam pgvector na porta 5433 (container), não o Postgres do sistema
   - `feedback_tdd_worktrees.md` — TDD e worktrees são NÃO-negociáveis
   - `project_architecture.md`
2. `docs/deploy/backlog-deploy.md` — o BACKLOG MESTRE (Sprints 7–12). É o mapa.
3. `docs/superpowers/specs/` e `docs/superpowers/plans/` — padrão de spec/plan do projeto.

## Estado atual (2026-06-12)
- App NO AR no Google Cloud Run, revision `expense-tracker-00005-74b`.
  URL: https://expense-tracker-654941182076.southamerica-east1.run.app
  (há também a URL legada `...c4xqrkvzia-rj.a.run.app` — AMBAS precisam estar em `ALLOWED_HOSTS`).
- Banco: Supabase Postgres + pgvector (região São Paulo). Dados reais carregados.
- `main` HEAD = `29cc999`. NÃO há remote git (deploy é via `gcloud run deploy --source`, não git push).
- Pronto e deployado: cockpit mensal (renda/sistemáticos/vencimentos/parcelamentos por mês),
  fix do assistente (ferramentas de sistemáticos + guardrails), e o design system "ledger"
  (paleta teal, fontes Fraunces/Hanken/IBM Plex Mono, mono money via filtro `{{ x|money }}`,
  dark mode auto + toggle no navbar, logout, hierarquia do dashboard, renda agrupada).

## O que falta no backlog maior (detalhes em `docs/deploy/backlog-deploy.md`)
- **Sprint 9 (resto):** CI/CD GitHub Actions (build→Artifact Registry→deploy via Workload Identity
  Federation), Job de migração no Cloud Run, Dockerfile non-root. (Configurar remote GitHub também.)
- **Sprint 10: PWA** — web app manifest, service worker (app shell offline), ícones maskable,
  auditoria de instalabilidade (Lighthouse), QA mobile. [Maior prioridade do usuário: destrava o app Android.]
- **Sprint 11: TWA / Play Store** — Bubblewrap, `/.well-known/assetlinks.json`, Play Console
  (taxa única ~US$25), trilha de teste interno (usuário + esposa). Precisa de um DOMÍNIO (hoje não há;
  decidir: usar a URL `*.run.app` ou registrar domínio).
- **Sprint 12: hardening** — Sentry, uptime check, backups testados, revisão de custo
  (`min-instances=0` hoje → cold start), runbook/rollback, rate-limit no login.

## Follow-ups menores abertos
- **Bug cosmético:** a proposta do assistente às vezes renderiza texto levemente duplicado
  ("Encontrei… Confirma? Encontrei… Confirma?"). Investigar streaming/markdown no React ChatWidget
  (`src/backend/frontend/src/cards/ChatWidget.tsx`) ou no fluxo SSE (`assistant/views.py`).
- **Cache em DEV:** assets servidos sem hash em `:8001` → o navegador segura CSS/mount.js;
  precisa "Empty cache and hard reload". Em prod não ocorre (WhiteNoise ManifestStaticFilesStorage hasheia).
  Opcional: adicionar cache-buster em dev.
- **Limpeza:** pode haver um worktree `.claude/worktrees/monthly-cockpit` e um servidor dev em `:8001`
  ainda de pé de sessões anteriores.

## Convenções OBRIGATÓRIAS do projeto
- **TDD:** teste que falha primeiro, depois implementação. Trabalhe em git worktree.
- **Testes:** `uv run pytest` (precisa do container pgvector na porta 5433 — `docker compose up -d db`).
  Classes de teste começam com `Test`; funções `test_`. Lint: `uv run ruff check src/backend` (line-length 100).
- **Frontend:** Tailwind v4 + DaisyUI v5 (tema "ledger" em `static/css/input.css`);
  rebuild CSS com `python manage.py tailwind build`. React via Vite — pnpm **PINADO em 10.23.0**,
  `pnpm install --frozen-lockfile` no diretório `src/backend/frontend`, build sai em `static/frontend/`.
  Dinheiro em templates usa o filtro `|money` (mono); cores de chart em `src/backend/frontend/src/theme.ts`.
- **Deploy:**
  ```
  gcloud run deploy expense-tracker --source <repo> --project expense-tracker-482807 \
    --region southamerica-east1 --allow-unauthenticated --min-instances 0 --timeout 300 \
    --cpu 1 --memory 1Gi --port 8080 \
    --set-secrets "SECRET_KEY=django-secret-key:latest,DATABASE_URL=database-url:latest,LLM_API_KEY=llm-api-key:latest" \
    --set-env-vars "^@^DEBUG=False@ALLOWED_HOSTS=<host1>,<host2>@CSRF_TRUSTED_ORIGINS=https://<host1>,https://<host2>"
  ```
  (o `^@^` é necessário porque os valores têm vírgulas; manter AMBAS as URLs senão dá 400 DisallowedHost).
- **Segredos** vivem no Secret Manager (não no git) e em `.env` local (gitignored). NUNCA commitar segredos.

## Como conduzir
Comece confirmando com o usuário qual sprint atacar primeiro (recomendo **Sprint 10 PWA**, que destrava o app Android).
Para features, use brainstorming → spec (`docs/superpowers/specs/`) → plano (`docs/superpowers/plans/`) → TDD.
Para tarefas de infra/deploy, confirme com o usuário antes de criar recursos na nuvem ou redeployar produção
(ele usa a tabela de produção no dia a dia).
</content>
