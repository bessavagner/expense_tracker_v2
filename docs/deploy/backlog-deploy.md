# Backlog de Deploy — Expense Tracker v2

> **Objetivo:** levar o sistema a produção de forma barata e estável, com servidor no
> **Google Cloud Run**, banco gerenciado no **Supabase**, e disponibilizar um **app Android**
> via **PWA/TWA** (a própria web app empacotada, publicável na Play Store).
>
> Este documento **substitui a estratégia de hospedagem** do antigo `production-roadmap.md`
> (que mirava self-host em `friday` + Cloudflare Tunnel). As partes de *preparação de código*
> (ASGI, HSTS, Supabase) foram absorvidas e atualizadas aqui.

## Decisões fechadas (2026-06-10)

| Tema | Decisão | Consequência |
|------|---------|--------------|
| **App Android** | **PWA → TWA** (Trusted Web Activity, Play Store) | Reusa a web app; **sem** API REST completa nem auth por token. |
| **Hosting** | **Google Cloud Run** (region `southamerica-east1`) | Serverless, escala a zero. Tratar **cold start** e **SSE** explicitamente. |
| **Banco** | **Supabase** Postgres + pgvector (region São Paulo) | Usar **Transaction Pooler (6543)** no app; conexão direta (5432) p/ migrações. |
| **Usuários** | **Login único** (`bessavagner`) | **Sem** escopo multiusuário; esposa usa o mesmo login. Zero mudança no modelo de dados. |
| **API framework** | **Manter DRF** (não migrar p/ Ninja) | Superfície de API pequena e interna; migração não traz ganho. Reavaliar só se virar app nativo. |

## Premissas de arquitetura alvo

```
[Android: TWA / navegador]
        │  HTTPS (expenses.<seu-dominio>)
        ▼
[Cloud Run: container Django ASGI (gunicorn + uvicorn worker)]
        │  Postgres (Transaction Pooler 6543, sslmode=require)
        ▼
[Supabase: Postgres + pgvector + backups]
```

- **Estáticos:** servidos pelo próprio container via **WhiteNoise** (já configurado) — sem bucket separado.
- **Segredos:** **Secret Manager** → injetados como env vars no Cloud Run.
- **Streaming do assistente (SSE):** exige **ASGI**; no Cloud Run, ajustar `timeout` e (opcional) `min-instances=1`.

> **Princípio de processo (não-negociável do projeto):** TDD, worktrees por feature, gates de
> qualidade (ruff + pytest). Cada task de código abaixo só fecha com testes + lint verdes.

---

## Sprint 7 — Prontidão de produção (código & config)
**Meta:** o container roda corretamente em modo produção (ASGI + segurança) localmente apontando para um Postgres "tipo Supabase". 1 PR principal, com testes.
**Dependências:** nenhuma. **Pode começar já.**

| # | Task | Critério de aceite |
|---|------|--------------------|
| 7.1 | **Migrar para ASGI.** Adicionar `uvicorn[standard]` às deps; trocar `CMD` do Dockerfile para `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT} --workers 2 --timeout 300 --access-logfile - --error-logfile -`. | Container sobe via ASGI; chat do assistente responde em **streaming** local; testes existentes verdes. |
| 7.2 | **HSTS + finalizar headers de segurança.** Sob `not DEBUG`: `SECURE_HSTS_SECONDS=31536000`, `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`, `SECURE_HSTS_PRELOAD=True`. Conferir `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT` (já existem). | `manage.py check --deploy` sem warnings críticos. Teste cobrindo headers em modo prod. |
| 7.3 | **Config de banco p/ pooler.** `DATABASE_URL` com Transaction Pooler (6543) + `?sslmode=require`; `CONN_MAX_AGE=0`, `CONN_HEALTH_CHECKS=True` (já estão sob `not DEBUG`). Documentar URL direta (5432) p/ migrações. | App conecta via pooler; doc com as duas URLs em `.env.example`. |
| 7.4 | **`compose.prod.yml`** só com serviço `web` (sem `db`/`redis`), `env_file: .env`, `ports: "127.0.0.1:8080:8080"`, `restart: unless-stopped`, `healthcheck` em `/healthz/`. | `docker compose -f compose.prod.yml up` sobe só o web e passa healthcheck. |
| 7.5 | **Remover Redis** do `docker-compose.yml` (sem uso no código). | Compose sem Redis; nada quebra. |
| 7.6 | **`/healthz/` com checagem de DB.** Estender o `health_check` atual p/ um ping leve no banco (`SELECT 1`), retornando 503 se falhar. | `/healthz/` = 200 com DB ok; 503 se DB cair. Teste cobrindo ambos. |
| 7.7 | **`.env.example` de produção.** Documentar `DEBUG=False`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `PORT`. | `.env.example` completo e comentado. |
| 7.8 | **Migrações fora do `CMD`.** Garantir que migrate é passo explícito (não no boot do container) p/ evitar corrida no Cloud Run. | Container sobe sem rodar migrate automaticamente. |

---

## Sprint 8 — Supabase (banco gerenciado)
**Meta:** banco de produção no Supabase, com schema migrado e dados reais carregados.
**Dependências:** 7.1–7.3 (config de banco/migrações pronta).

| # | Task | Critério de aceite |
|---|------|--------------------|
| 8.1 | **Criar projeto Supabase** (region São Paulo). Avaliar free vs paid (free **pausa** por inatividade → cold start do DB). | Projeto criado; região correta. |
| 8.2 | **Habilitar pgvector** (`create extension vector;` ou Dashboard → Extensions). | Extensão ativa; migração de embeddings aplica. |
| 8.3 | **Pegar connection strings** (Transaction Pooler 6543 + direta/Session 5432). Guardar no gestor de segredos (não no git). | Strings testadas com `psql`. |
| 8.4 | **Rodar migrações** contra o Supabase via URL direta (5432). | `migrate` 100% aplicado; `showmigrations` limpo. |
| 8.5 | **Criar superusuário** `bessavagner` com senha forte. | Login OK no `/admin/`. |
| 8.6 | **Migrar dados reais** (1881 lançamentos). Escolher: **(a)** re-import via `import_csv --user bessavagner --dir .data/imports` + `seed_data` (tetos), **mais limpo**; ou **(b)** `pg_dump`/`pg_restore` do local (preserva ajustes de UI). | Dados conferem (contagem + spot-check no dashboard). |
| 8.7 | **Validar backups.** Confirmar política de backup do Supabase e retenção do plano. | Documentado; teste de restore opcional. |

---

## Sprint 9 — Deploy no Cloud Run (CI/CD)
**Meta:** app no ar em URL HTTPS estável, com deploy automatizado por push.
**Dependências:** Sprints 7 e 8.

| # | Task | Critério de aceite |
|---|------|--------------------|
| 9.1 | **Projeto GCP + Artifact Registry.** Criar projeto, habilitar APIs (Run, Artifact Registry, Secret Manager, Cloud Build), repositório de imagens. | `gcloud` autenticado; repo criado. |
| 9.2 | **Ajustar Dockerfile p/ Cloud Run.** Confirmar `$PORT=8080`, usuário não-root, `CMD` ASGI (da 7.1). Build local da imagem final OK. | Imagem builda e roda localmente respeitando `$PORT`. |
| 9.3 | **Secret Manager.** Subir `SECRET_KEY` (novo/rotacionado), `DATABASE_URL`, `LLM_API_KEY`, etc.; mapear como env vars no serviço. | Segredos referenciados pelo serviço; nada sensível em texto plano. |
| 9.4 | **Deploy do serviço.** `gcloud run deploy` em `southamerica-east1` com: `--min-instances=1` (mata cold start; avaliar custo), `--max-instances` baixo, `--cpu/--memory` enxutos, `--timeout=300` (SSE), `--concurrency` ajustado p/ ASGI. | Serviço responde `/healthz/` = 200 publicamente. |
| 9.5 | **Job de migração.** Criar **Cloud Run Job** (ou execução one-off) que roda `migrate` com a URL direta — desacoplado do serviço web. | `migrate` roda sob demanda no deploy, sem corrida. |
| 9.6 | **Domínio + SSL.** Mapear `expenses.<seu-dominio>` ao serviço; ajustar `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`. | HTTPS válido no domínio custom; cookies `Secure`. |
| 9.7 | **Pipeline GitHub Actions.** Workflow: build → push p/ Artifact Registry → `gcloud run deploy` (+ job de migrate) em push na `main`. Usar Workload Identity Federation (sem chave JSON longa). | Push na `main` publica nova revisão automaticamente. |
| 9.8 | **Smoke test de produção.** Validar: login, dashboard com dados, criar/editar lançamento, e **assistente em streaming SSE** no Cloud Run. | Checklist ponta-a-ponta verde a partir de rede externa (4G). |

---

## Sprint 10 — PWA (instalável)
**Meta:** a web app vira um PWA instalável, responsivo, com shell offline.
**Dependências:** Sprint 9 (precisa de HTTPS estável). Front-end pode ser adiantado em paralelo.

| # | Task | Critério de aceite |
|---|------|--------------------|
| 10.1 | **Web App Manifest.** `manifest.webmanifest` com `name`, `short_name`, `start_url`, `display: standalone`, `theme_color`, `background_color`. | Manifest servido e válido. |
| 10.2 | **Ícones + splash.** Conjunto de ícones (192/512, maskable) e meta tags. | Lighthouse reconhece ícones; instalável sem warnings. |
| 10.3 | **Service Worker.** Cache do app shell + estáticos (estratégia cache-first p/ assets, network-first p/ dados); página de fallback offline. | App abre offline (shell + dados em cache); writes exigem rede (ok). |
| 10.4 | **Auditoria de instalabilidade.** Rodar Lighthouse PWA; corrigir pendências (HTTPS, manifest, SW, viewport). | Score PWA "installable" verde. |
| 10.5 | **QA mobile responsivo.** Passada de UX em telas de celular (dashboard, formulários, chat). Reusar `qa-screenshots`/Playwright. | Sem quebras de layout no viewport mobile. |

---

## Sprint 11 — TWA / publicação na Play Store
**Meta:** app Android instalável (você e esposa) a partir do PWA.
**Dependências:** Sprint 10.

| # | Task | Critério de aceite |
|---|------|--------------------|
| 11.1 | **Projeto Bubblewrap/PWABuilder.** Gerar projeto TWA a partir do manifest; configurar `applicationId`, `host`, ícones. | Projeto TWA builda um AAB assinado. |
| 11.2 | **Digital Asset Links.** Servir `/.well-known/assetlinks.json` no domínio (rota Django ou WhiteNoise) com o fingerprint da chave de assinatura. | Verificação de domínio passa; app abre sem barra de URL. |
| 11.3 | **Conta Play Console.** Criar conta dev (taxa única ~US$25); ficha do app, política de privacidade simples. | App no console em rascunho. |
| 11.4 | **Trilha de teste interno.** Subir AAB na trilha *Internal testing*; adicionar você + esposa como testers. | Ambos instalam pela Play Store. |
| 11.5 | **Validação em dispositivo.** Login, dashboard, criar lançamento e assistente funcionando no app. | Checklist verde nos 2 celulares. |

---

## Sprint 12 — Hardening, observabilidade & operação
**Meta:** rodar com confiança — monitorar, fazer backup, controlar custo e ter rollback.
**Dependências:** Sprint 9 (idealmente após 11).

| # | Task | Critério de aceite |
|---|------|--------------------|
| 12.1 | **Rotacionar segredos.** Gerar `SECRET_KEY` novo p/ prod; confirmar que chave LLM exposta em logs antigos foi trocada. | Segredos de prod distintos dos de dev; nada vazado no git. |
| 12.2 | **Monitoramento de erros.** Integrar Sentry (tier free) no Django. | Exceções aparecem no Sentry. |
| 12.3 | **Logs + uptime.** Logs estruturados no Cloud Logging; Uptime Check batendo em `/healthz/`. | Alerta dispara se cair. |
| 12.4 | **Backups verificados.** Confirmar backup automático do Supabase; (opcional) `pg_dump` agendado p/ destino externo + **teste de restore**. | Restore testado pelo menos uma vez. |
| 12.5 | **Revisão de custo.** Medir custo real (Cloud Run `min-instances`, egress, Supabase free vs paid p/ evitar pausa do DB). Ajustar `min-instances`/plano. | Custo mensal estimado documentado e aceitável. |
| 12.6 | **Runbook + rollback.** `deploy.sh`/doc com: deploy, rollback p/ revisão anterior (`gcloud run services update-traffic`), migrate, restore. | Runbook em `docs/deploy/`. |
| 12.7 | **(Opcional) Rate limit / WAF.** Cloudflare na frente do domínio, ou `django-ratelimit` no login. | Login protegido contra brute force. |

---

## Caminho crítico & paralelização

```
S7 (código) ──► S8 (Supabase) ──► S9 (Cloud Run) ──► S12 (operação)
                                       │
                                       └──► S10 (PWA) ──► S11 (Play Store)
```

- **S7** pode começar imediatamente (independente de infra).
- **S10 (front PWA)** pode ser adiantada em paralelo a S8/S9; só *fecha* quando há HTTPS estável (S9).
- **S8 e S9.1–9.3** (criar GCP/Supabase) podem rodar em paralelo após S7.

## Riscos / pontos de atenção

- **SSE no Cloud Run:** cold start (scale-to-zero) atrasa a 1ª resposta e pode cortar streams longos. Mitigar com `--min-instances=1` e `--timeout` adequado (custo extra pequeno).
- **Supabase free pausa** por inatividade → 1º acesso lento. Avaliar plano pago se incomodar.
- **Pooler vs migrações:** o Transaction Pooler (6543) não suporta tudo; **migrar pela conexão direta (5432)**.
- **Domínio** é necessário p/ TWA (Digital Asset Links exige host estável e HTTPS).
- **Gatilho p/ reabrir Django Ninja:** só se evoluir para **app nativo** (API REST tipada + auth por token). No cenário PWA atual, manter DRF.
</content>
</invoke>
