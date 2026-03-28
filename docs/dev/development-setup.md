# Development Environment Setup

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 20+ with pnpm
- Docker + Docker Compose

## 1. Clone and Install Dependencies

```bash
git clone <repo-url>
cd expense_tracker_v2

# Python dependencies
uv sync

# Frontend dependencies
cd src/backend/frontend
pnpm install
cd ../../..
```

## 2. Environment Variables

Copy the example and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | insecure placeholder | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `CSRF_TRUSTED_ORIGINS` | `http://localhost:8000` | Update port if changed |
| `POSTGRES_DB` | `expense_tracker` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `postgres` | Database password |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Mapped Postgres port |
| `REDIS_PORT` | `6379` | Mapped Redis port |

## 3. Start Infrastructure (Postgres + Redis)

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `$POSTGRES_PORT` (default 5432)
- **Redis 7** on port `$REDIS_PORT` (default 6379)

Ports are configurable via `.env` to avoid conflicts with other local services.

## 4. Database Setup

```bash
cd src/backend
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

## 5. Build Tailwind CSS

```bash
cd src/backend
uv run python manage.py tailwind build
```

For automatic rebuild on template changes during development:

```bash
uv run python manage.py tailwind watch
```

## 6. Running the Dev Servers

### Option A: Manual (two terminals)

**Backend** (Django dev server):

```bash
cd src/backend
uv run python manage.py runserver 0.0.0.0:<PORT>
```

**Frontend** (Vite dev server for React islands HMR):

```bash
cd src/backend/frontend
pnpm dev --port <PORT>
```

The app is accessed through the Django server. The Vite server only serves JS assets for hot module replacement during development.

### Option B: systemd User Services (Linux)

Template service files are provided in `docs/dev/`. To install:

1. Copy and edit the service files, replacing placeholders:

```bash
cp docs/dev/expense-tracker-backend.service ~/.config/systemd/user/
cp docs/dev/expense-tracker-frontend.service ~/.config/systemd/user/
```

2. Edit both files and replace the placeholders:

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{{PROJECT_ROOT}}` | Absolute path to project root | `/home/user/projects/expense_tracker_v2` |
| `{{HOME}}` | Your home directory | `/home/user` |
| `{{UV_BIN}}` | Directory containing `uv` binary | `/home/user/.local/bin` |
| `{{NODE_BIN}}` | Directory containing `node`/`pnpm` | `/home/user/.nvm/versions/node/v20.x.x/bin` |
| `{{PNPM_BIN}}` | Directory containing `pnpm` binary | `/home/user/.nvm/versions/node/v20.x.x/bin` |
| `{{BACKEND_PORT}}` | Port for Django dev server | `8700` |
| `{{FRONTEND_PORT}}` | Port for Vite dev server | `5175` |

3. Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable expense-tracker-backend expense-tracker-frontend
systemctl --user start expense-tracker-backend expense-tracker-frontend
```

4. Useful commands:

```bash
# Check status
systemctl --user status expense-tracker-backend
systemctl --user status expense-tracker-frontend

# View logs
journalctl --user -u expense-tracker-backend -f
journalctl --user -u expense-tracker-frontend -f

# Restart after code changes (Django auto-reloads, but sometimes needed)
systemctl --user restart expense-tracker-backend
```

## 7. Running Tests

```bash
cd src/backend
uv run pytest                    # full suite
uv run pytest assistant/ -v     # single app
uv run pytest -k "test_name"    # single test
```

## 8. Linting

```bash
cd src/backend
uv run ruff check .             # lint
uv run ruff format .            # format
```

## Project Structure

```
expense_tracker_v2/
├── docker-compose.yml          # Postgres + Redis
├── pyproject.toml              # Python dependencies (uv)
├── .env                        # Environment variables (not committed)
├── src/backend/
│   ├── config/                 # Django settings, urls
│   ├── core/                   # User model
│   ├── finances/               # Financial models + views
│   ├── dashboard/              # Dashboard API + views
│   ├── assistant/              # AI assistant (PydanticAI)
│   ├── importer/               # CSV import
│   ├── templates/              # Django templates (HTMX)
│   ├── static/                 # Static files (CSS, images)
│   └── frontend/               # React islands (Vite)
│       ├── src/                # React components
│       ├── package.json
│       └── vite.config.ts
└── docs/
    └── dev/                    # Development setup docs
```
