#!/usr/bin/env bash
# Reage às mudanças trazidas por um pull/checkout, replicando a automação que
# antes vivia no sync-to-friday.sh. Recebe a lista de arquivos alterados ($1).
#
#   - */migrations/*.py        -> manage.py migrate
#   - pyproject.toml / uv.lock -> uv sync + restart backend
#   - package.json / lock      -> pnpm install
#
# NÃO rebuilda o frontend: mount.js é artefato git-tracked, buildado e commitado
# na máquina onde o .tsx foi editado (ver reference_frontend_build_artifacts).
# Por isso, na friday, mantenha o vite watch DESLIGADO por padrão — o mount.js
# chega pronto pelo pull. Só ligue a vite quando for editar frontend ali.
set -uo pipefail

changed="${1:-}"
[ -z "$changed" ] && exit 0

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT" || exit 0

# Ambiente: uv em ~/.local/bin, node via nvm (igual ao que o script ssh fazia).
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1
export PATH="$HOME/.local/bin:$PATH"

run() { echo "[hook] $*"; "$@"; }

if grep -qE '/migrations/[^/]+\.py$' <<<"$changed"; then
  echo "[hook] migrations alteradas -> manage.py migrate"
  (cd src/backend && uv run python manage.py migrate --noinput) || echo "[hook] migrate falhou"
fi

if grep -qE '(^|/)(pyproject\.toml|uv\.lock)$' <<<"$changed"; then
  echo "[hook] deps Python -> uv sync + restart backend"
  uv sync 2>&1 | tail -3 || echo "[hook] uv sync falhou"
  systemctl --user restart expense-tracker-backend.service 2>/dev/null || true
fi

if grep -qE '(^|/)(package\.json|pnpm-lock\.yaml)$' <<<"$changed"; then
  echo "[hook] deps frontend -> pnpm install"
  (cd src/backend/frontend && pnpm install) 2>&1 | tail -3 || echo "[hook] pnpm install falhou"
fi

exit 0
