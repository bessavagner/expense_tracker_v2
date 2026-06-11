# Roadmap de Produção — Expense Tracker v2

**Alvo:** rodar em produção na máquina `friday` (Ubuntu + Docker, atrás de NAT),
banco no **Supabase**, acesso de **qualquer lugar** via HTTPS, **usuário único** (`bessavagner`).

## Arquitetura alvo

```
[seu navegador, qualquer rede]
        │  HTTPS (expenses.seu-dominio)
        ▼
[Cloudflare] ── Tunnel ──► [friday: cloudflared] ──► 127.0.0.1:8080
                                                         │
                                              [container Django/ASGI (gunicorn+uvicorn)]
                                                         │  Postgres + pgvector (TLS)
                                                         ▼
                                                   [Supabase]
```

- **App**: container Docker em `friday`, escutando só em `127.0.0.1:8080` (nunca exposto direto à internet).
- **Acesso remoto**: **Cloudflare Tunnel** (grátis, sem abrir portas no roteador, dá HTTPS + domínio). Opcional: **Cloudflare Access** (OTP por e-mail) como porteiro extra — ideal para 1 usuário.
- **Banco**: Supabase (Postgres gerenciado + pgvector + backups).
- **Segredos**: `.env` em `friday` (fora do git).

Alternativa de acesso: **Tailscale** (só seus dispositivos, zero exposição pública) — mais privado, porém exige o cliente em cada dispositivo. Cloudflare Tunnel é melhor para "de qualquer navegador".

---

## Fase 0 — Decisões (pré-requisitos)
- [ ] Você tem/quer um **domínio no Cloudflare**? (necessário para URL estável + Cloudflare Access). Sem domínio dá pra testar com *quick tunnel* efêmero, mas não serve para uso fixo.
- [ ] Conta **Supabase** (free serve para 1 usuário; atenção: free **pausa** após inatividade → cold start. Always-on = plano pago).
- [ ] Migrar os dados atuais (1881 lançamentos já importados localmente) para o Supabase? Opções na Fase 2.

## Fase 1 — Ajustes de código/config (1 PR, com testes)
1. **ASGI para o streaming do assistente** (principal mudança):
   - Adicionar `uvicorn[standard]` às deps.
   - Trocar o `CMD` do Dockerfile para servir `config.asgi:application`:
     `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT} --workers 2 --timeout 300 --access-logfile - --error-logfile -`
   - Garante SSE/async corretos (hoje roda `config.wsgi` com `gthread`).
2. **HSTS** (faltando): sob `not DEBUG`, `SECURE_HSTS_SECONDS=31536000`, `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`, `SECURE_HSTS_PRELOAD=True`. (`SECURE_PROXY_SSL_HEADER` já existe — essencial atrás do Tunnel.)
3. **Banco/Supabase**: usar o **Transaction Pooler** (porta 6543) na `DATABASE_URL` do app, com `?sslmode=require`; manter `CONN_MAX_AGE=0` (já é o default quando `not DEBUG`). Migrações rodam via **conexão direta/Session Pooler (5432)** (o transaction pooler não suporta tudo). Documentar ambas as URLs.
4. **compose de produção** (`compose.prod.yml`): só o serviço `web` (sem `db`/`redis` locais), `env_file: .env`, `restart: unless-stopped`, `ports: "127.0.0.1:8080:8080"`, `healthcheck` em `/healthz/`.
5. **Remover Redis** do compose (sem uso no código).
6. **`.env.example`**: adicionar vars de prod (`DEBUG=False`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `LLM_MODEL`, `LLM_API_KEY`).
7. **Migrações no deploy**: passo explícito (`docker compose run --rm web python manage.py migrate`), não no `CMD` (evita corrida).

## Fase 2 — Supabase
1. Criar projeto (região mais próxima — ex. São Paulo).
2. Habilitar extensão **pgvector** (Dashboard → Database → Extensions, ou `create extension vector;`).
3. Pegar as connection strings (Transaction Pooler 6543 e direta/Session 5432).
4. Rodar **migrações** contra o Supabase (`DATABASE_URL` direta).
5. Criar o superusuário `bessavagner` com senha forte.
6. **Dados**: escolher um:
   - (a) **Re-importar** via `import_csv --user bessavagner --dir .data/imports` apontando para o Supabase (mais limpo; você já tem o comando e os CSVs) + `seed_data` para os tetos.
   - (b) **pg_dump/pg_restore** do banco local (5433) para o Supabase (preserva tudo, inclusive ajustes feitos na UI).

## Fase 3 — Deploy em `friday`
1. `git clone` (ou pull) do repo em `friday`.
2. Criar `.env` de produção (segredos; **fora do git**).
3. `docker compose -f compose.prod.yml build`.
4. `docker compose -f compose.prod.yml run --rm web python manage.py migrate`.
5. `docker compose -f compose.prod.yml up -d`.
6. Validar localmente em friday: `curl localhost:8080/healthz/` → 200.

## Fase 4 — Acesso remoto (Cloudflare Tunnel)
1. Instalar `cloudflared` em friday; `cloudflared tunnel login`.
2. Criar tunnel; rotear hostname (`expenses.seu-dominio`) → `http://localhost:8080`.
3. Instalar como serviço: `cloudflared service install` (sobe no boot).
4. Ajustar no `.env`: `ALLOWED_HOSTS=expenses.seu-dominio`, `CSRF_TRUSTED_ORIGINS=https://expenses.seu-dominio`; restart do container.
5. (Recomendado) **Cloudflare Access**: política permitindo só o seu e-mail (OTP) → camada extra sobre o login do Django.
   - *Alternativa:* Tailscale (`tailscale up`) e acessar via IP/MagicDNS da tailnet — sem exposição pública.

## Fase 5 — Hardening & operação
- [ ] `DEBUG=False`, `SECRET_KEY` forte e novo (gerar), `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` corretos.
- [ ] **Rotacionar** chaves que vazaram em logs (OpenAI/SECRET_KEY) — já trocou a OpenAI; trocar SECRET_KEY em prod.
- [ ] Backups: Supabase faz automático (retenção limitada no free) → opcional `pg_dump` cron em friday para um destino seguro.
- [ ] Auto-start: `restart: unless-stopped` (container) + cloudflared como serviço → sobrevive a reboot.
- [ ] Deploy/atualização: script `deploy.sh` (`git pull && build && migrate && up -d`).
- [ ] Monitoramento simples: cron `curl /healthz/` ou health check do Cloudflare.
- [ ] Logs: `docker logs` / journald.

## Fase 6 — Verificação ponta-a-ponta
- [ ] Acessar `https://expenses.seu-dominio` de uma rede externa (ex. 4G no celular).
- [ ] Login OK; dashboard com dados; criar/editar lançamento.
- [ ] **Assistente (chat SSE) responde em streaming** — valida o ASGI da Fase 1.
- [ ] HTTPS válido, sem mixed content; cookies `Secure`.

---

## Riscos / pontos de atenção
- **ASGI** é a mudança de código mais importante (sem ela, o chat streaming sofre sob carga).
- **Supabase free pausa** por inatividade → primeiro acesso lento; avaliar plano pago se incomodar.
- **Domínio** é necessário para Tunnel estável + Cloudflare Access (quick tunnels são efêmeros).
- Escolher estratégia de **dados** (re-import vs dump/restore) antes de virar a chave.
