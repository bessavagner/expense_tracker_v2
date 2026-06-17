# Migração do sync jarvis↔friday: de rsync para git (GitHub privado)

O sync mão-única por rsync (`sync-to-friday.sh` + `et-sync-friday.service`) foi
substituído por um hub git no GitHub privado
`git@github.com:bessavagner/expense_tracker_v2`. Agora dá pra editar **nas duas
máquinas**: commit + push de um lado, `git pull` do outro.

A automação que o script fazia (migrate / uv sync / pnpm install / restart) virou
**git hook** versionado em `scripts/git-hooks/`, ativado por `core.hooksPath`.

## No jarvis (já feito)

- Repo privado criado, `origin` apontando pro GitHub, branches e tags empurradas.
- `core.hooksPath=scripts/git-hooks` configurado.
- `et-sync-friday.service` parado e desabilitado (rsync aposentado).

## Na friday (rodar quando ela voltar à rede)

Hoje a friday tem só a árvore de arquivos (sem `.git` — o rsync excluía). Converta
em clone do GitHub **sem perder o `.env` local**:

```bash
cd /home/bessa/Documents/projetos
# 1. preserva o .env por-máquina (ALLOWED_HOSTS/CSRF da friday)
cp expense_tracker_v2/src/backend/.env /tmp/friday.env 2>/dev/null || true

# 2. clona ao lado e migra o .env de volta
git clone git@github.com:bessavagner/expense_tracker_v2.git expense_tracker_v2_git
cp /tmp/friday.env expense_tracker_v2_git/src/backend/.env 2>/dev/null || true

# 3. troca o diretório antigo pelo clone
mv expense_tracker_v2 expense_tracker_v2.rsync-bak
mv expense_tracker_v2_git expense_tracker_v2
cd expense_tracker_v2

# 4. ativa os hooks versionados
git config core.hooksPath scripts/git-hooks

# 5. recria deps/artefatos locais (não vêm no git: .venv, node_modules)
uv sync
(cd src/backend/frontend && pnpm install)
```

> Alternativa sem mover diretórios: `git init` dentro do dir atual,
> `git remote add origin ...`, `git fetch`, `git reset --hard origin/main`.
> Mais arriscado (sobrescreve working tree) — o clone ao lado é mais seguro.

### Frontend (mount.js) na friday — importante

`src/backend/static/frontend/mount.js` é **git-tracked** e buildado/commitado na
máquina onde o `.tsx` foi editado. Por isso, na friday:

- **Mantenha o vite watch DESLIGADO por padrão.** O `mount.js` chega pronto pelo
  pull; o Django serve o artefato commitado. Se a vite ficar rodando, ela
  reescreve o `mount.js` e suja o working tree → `git pull` passa a falhar.

  ```bash
  systemctl --user disable --now expense-tracker-frontend.service
  ```

- **Só para editar frontend na friday:** ligue a vite temporariamente
  (`systemctl --user start expense-tracker-frontend.service`), edite, então
  `pnpm build` → `git add` o `mount.js` → commit → push. Depois desligue a vite.

O backend (`expense-tracker-backend.service`, Django :8700) continua com
auto-reload de `.py` via StatReloader — sem mudança.

## Fluxo diário

- **jarvis → friday:** edita no jarvis, `git commit`, `git push`; na friday
  `git pull` (o hook roda migrate/uv sync/pnpm conforme o que mudou).
- **friday → jarvis:** edita na friday, commit, push; no jarvis `git pull`.
- Mexeu em `.tsx`? Builde e commite o `mount.js` na mesma máquina antes do push.
- Migrations/deps são aplicadas automaticamente pelo hook no `pull`.

## Banco de dados

O git **não** versiona o DB. A cópia de dados continua via
`scripts/copy-db-to-friday.sh` (pg_dump | psql), quando quiser espelhar dados.
