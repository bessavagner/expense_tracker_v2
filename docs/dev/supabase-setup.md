# Supabase Setup Guide with pgvector

This guide walks through setting up Supabase for the expense tracker project, with pgvector extension enabled for vector embeddings.

## Creating a Supabase Project

1. Go to [supabase.com](https://supabase.com) and sign up or log in
2. Click "New Project" and select the free tier
3. Fill in project details:
   - Project Name: e.g., "expense-tracker"
   - Database Password: Generate a strong password (save this)
   - Region: Choose the region closest to your deployment location
4. Wait for the project to initialize (usually 1-2 minutes)

## Enabling pgvector Extension

The pgvector extension enables vector similarity search, required for AI features.

1. In the Supabase dashboard, navigate to **SQL Editor**
2. Click "New Query"
3. Paste and execute the following SQL:

```sql
CREATE EXTENSION vector;
```

4. Confirm the extension is enabled by running:

```sql
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

You should see "vector" in the results.

## Connection String Format

Supabase provides two connection options. **Always use the transaction mode pooler (port 6543)** for Cloud Run deployments.

### Standard Format

```
postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
```

### Breakdown

- **postgres**: Username (default user)
- **[ref]**: Your Supabase project reference ID (visible in project settings)
- **[password]**: Your database password (set during project creation)
- **aws-0-[region]**: Regional endpoint (e.g., `aws-0-us-east-1` for US East)
- **6543**: Supavisor transaction mode pooler port (essential for Cloud Run)
- **postgres**: Database name

### Finding Your Connection Details

1. In Supabase dashboard, go to **Settings** → **Database**
2. Scroll to "Connection String"
3. Select "Transaction pooling" from the dropdown
4. Copy the connection string (it will be in the correct format above)

## Port 6543 - Supavisor Transaction Mode

The transaction mode pooler (port 6543) is critical for serverless deployments like Cloud Run:

- **Transaction pooling**: Creates a lightweight connection pool per database transaction
- **Stateless**: Allows scalable, serverless deployments without persistent connections
- **Low overhead**: Minimal resource consumption compared to session pooling
- **Session pooling (port 5432)**: Use only for long-running applications with persistent connections

## Setting the DATABASE_URL Environment Variable

1. Copy your connection string from Supabase (transaction mode, port 6543)
2. Set the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL="postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres"
```

For Cloud Run, set this in the service's environment variables via the console or `gcloud` CLI.

## Running Migrations

Once `DATABASE_URL` is set, apply all migrations:

```bash
DATABASE_URL="postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres" uv run python manage.py migrate
```

Or if `DATABASE_URL` is already exported:

```bash
uv run python manage.py migrate
```

This will:
1. Create all necessary tables and indexes
2. Run any pending migrations
3. Initialize the database schema

## Connection Pooling Configuration

The project's Django settings already handle connection pooling correctly:

### In Non-DEBUG Mode (Production)

```python
CONN_MAX_AGE = 0
```

This setting:
- Closes database connections after each HTTP request
- Essential for transaction-mode pooling on Supavisor
- Prevents connection exhaustion in serverless environments
- Works seamlessly with Cloud Run's request-based scaling

### In DEBUG Mode (Development)

Connection pooling is not strictly required for local development, but using the same configuration ensures consistency.

## Troubleshooting

### Connection Refused
- Verify the connection string includes port **6543** (transaction mode)
- Check that Supabase project is running (visible in dashboard)
- Ensure firewall rules allow outbound connections to Supabase

### "pgvector" Extension Not Found
- Confirm pgvector was created with `CREATE EXTENSION vector;`
- Check extension list: `SELECT * FROM pg_extension;`
- Verify you're on the correct database

### Too Many Connections
- Verify `CONN_MAX_AGE=0` is set in Django settings
- Check that old connections are being closed
- Monitor active connections: `SELECT count(*) FROM pg_stat_activity;`

## Next Steps

1. Create custom tables for the application schema
2. Set up authentication (Supabase Auth or external provider)
3. Configure row-level security (RLS) policies for multi-tenant access
4. Test vector similarity search with sample embeddings
