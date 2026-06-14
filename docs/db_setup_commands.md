# Database Setup — Command Log

The exact commands executed to stand up the database layer (Postgres + Pagila + Alembic
migrations), in order. Run from the repo root. Commands are shown in their cross-platform form;
Windows/PowerShell equivalents are noted where they differ.

> Environment used: Windows 11, PowerShell, Docker Desktop, uv 0.7.17, Python 3.13.5.

---

## 0. Preflight checks (read-only)

```bash
docker info                 # confirm the Docker engine is running
docker compose version      # confirm Compose CLI is available
uv --version
```

On Windows the Docker engine was not running, so Docker Desktop was launched first:

```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
# wait ~30-60s for the engine; re-run `docker info` until it responds
```

## 1. Python project + dependencies

There was a bare `.venv` but no `pyproject.toml`, so a minimal `pyproject.toml` was created first
(`[project]` with `requires-python = ">=3.12"`, empty `dependencies`). Then:

```bash
uv add alembic "psycopg[binary]" sqlalchemy
uv add python-dotenv
```

This created `uv.lock` and installed into `.venv`. On a fresh clone the equivalent is simply:

```bash
uv sync
```

## 2. Download the Pagila dump

```bash
mkdir -p db/pagila
curl -fL --retry 3 -o db/pagila/01-schema.sql https://raw.githubusercontent.com/devrimgunduz/pagila/master/pagila-schema.sql
curl -fL --retry 3 -o db/pagila/02-data.sql   https://raw.githubusercontent.com/devrimgunduz/pagila/master/pagila-data.sql
```

PowerShell `mkdir -p` equivalent: `New-Item -ItemType Directory -Force -Path db\pagila`.
Files are prefixed `01-`/`02-` so the container's init hook runs schema before data.

## 3. Configure connection string

Appended to `.env` (gitignored):

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pagila
```

PowerShell used: `Add-Content -Path .env -Value 'DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pagila'`
(then fixed a missing trailing newline so it landed on its own line).

## 4. Start Postgres + auto-restore Pagila

`docker-compose.yml` mounts `./db/pagila` into `/docker-entrypoint-initdb.d`, so Pagila loads
automatically on the first boot of an empty data volume.

```bash
docker compose up -d
docker compose ps                                   # wait until STATUS shows "(healthy)"
docker inspect -f '{{.State.Health.Status}}' pagila-db
```

Sanity-check the restore:

```bash
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -tA -c "SELECT count(*) FROM film;"      # 1000
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -tA -c "SELECT count(*) FROM customer;"  # 599
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -tA -c "SELECT title FROM film WHERE title ILIKE '%alien%';"
```

## 5. Initialize and configure Alembic

```bash
uv run alembic init migrations
```

Then edited `migrations/env.py` to read `DATABASE_URL` from `.env` via `python-dotenv`
(`load_dotenv()` + `config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])`),
keeping the credential out of `alembic.ini`.

## 6. Create the two migrations

```bash
uv run alembic revision -m "add film.streaming_available"      # -> 8aa820a28c1a
uv run alembic revision -m "create streaming_subscription"     # -> d309a0b6a0a4 (chained)
```

Then filled in the generated files under `migrations/versions/`:

- **`8aa820a28c1a`** — `op.add_column('film', streaming_available BOOLEAN NOT NULL DEFAULT FALSE)`
  + backfill `UPDATE film SET streaming_available = TRUE WHERE title ILIKE '%alien%' OR film_id <= 50`.
- **`d309a0b6a0a4`** — `op.create_table('streaming_subscription', ...)` (FK -> `customer`) + index on
  `customer_id` + seed one active `Premium` row for `customer_id = 1`.

## 7. Apply and verify

```bash
uv run alembic upgrade head
uv run alembic current        # -> d309a0b6a0a4 (head)
```

Verification queries:

```bash
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -c "\d film"
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -c "SELECT title, streaming_available FROM film WHERE title ILIKE '%alien%';"
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -c "\d streaming_subscription"
docker exec -e PGPASSWORD=postgres pagila-db psql -U postgres -d pagila -c "SELECT * FROM streaming_subscription WHERE customer_id = 1;"
```

## 8. Verify reversibility (round-trip)

```bash
uv run alembic downgrade base   # drops both objects cleanly (Pagila untouched)
uv run alembic upgrade head     # re-applies both migrations + seed
```

---

## Re-restore from scratch

The init scripts only run on an empty volume:

```bash
docker compose down -v          # drop the pgdata volume
docker compose up -d            # fresh Pagila restore
uv run alembic upgrade head     # re-apply migrations
```
