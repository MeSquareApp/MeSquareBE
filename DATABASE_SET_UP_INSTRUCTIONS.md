## Database Setup & Migrations (Alembic + Supabase)

We use SQLAlchemy 2.0 for our database models and Alembic to manage schema migrations. Our database is hosted on Supabase and accessed asynchronously using the `asyncpg` driver. The project uses [uv](https://docs.astral.sh/uv/) to manage the virtual environment and dependencies.

### 1. Prerequisites
Ensure your `.env` file contains the correct Supabase connection string configured for async access (check pinned message on discord for the connection string). It should have the following format:

```env
database_url="postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres"
```

### 2. Ensure Alembic Is Installed
Alembic is a **dev dependency** (declared under `[dependency-groups]` in `pyproject.toml`, not the main `dependencies`). If it is missing from your virtual environment, add it with:

```bash
uv add --dev alembic
```

Verify it is available before running migrations:

```bash
uv run alembic --version
```

> **Note:** Always invoke Alembic through `uv run alembic ...`. This guarantees the command uses the project's `.venv` instead of a global Python/Anaconda installation that may have a different (or missing) Alembic version. Do **not** rely on `source .venv/bin/activate` + bare `alembic` if your terminal may resolve to another environment.

### 3. Migration Workflow
Whenever you create new tables or modify existing ones in the `app/models/` directory, follow these steps to push the changes to Supabase:

**Step 1: Check the current migration state**
See which migrations are applied and what your local head is:
```bash
uv run alembic current
uv run alembic history
```

**Step 2: Generate a new migration script**
After writing or updating your Python models, auto-generate the migration file:
```bash
uv run alembic revision --autogenerate -m "Brief description of your changes"
```
*Always review the newly generated file inside `alembic/versions/` before applying it.* Autogenerate detects model-vs-DB differences, so if the live database has drifted from the migrations, the generated script may contain unexpected drops or type changes.

For fixes that autogenerate cannot detect (e.g., data corrections, renaming enum labels, converting units), create an empty migration and write the SQL manually:
```bash
uv run alembic revision -m "Description of manual change"
```

**Step 3: Apply the migration to Supabase**
Execute the migration to build or update the tables in the remote database:
```bash
uv run alembic upgrade head
```
If a migration fails partway, Alembic wraps each migration in a transaction (transactional DDL on Postgres), so failed changes are rolled back and the revision is not recorded — fix the script and re-run.

### 4. Helpful Commands
* **Undo the last applied migration:** 
  ```bash
  uv run alembic downgrade -1
  ```
* **View the migration history:** 
  ```bash
  uv run alembic history
  ```
* **Check the currently applied revision:**
  ```bash
  uv run alembic current
  ```
* **Regenerate a bad migration:** delete the file from `alembic/versions/` (only if it has *not* been applied) and re-run the revision command.

### 5. Caveats & Gotchas
* **Schema drift:** The shared live database has drifted from migrations before (e.g., columns or enum labels created outside Alembic). If a migration fails with a type/cast error, inspect the actual DB state first (e.g., via `information_schema.columns` or `pg_enum`) rather than trusting `alembic history` alone.
* **Autogenerate is not a diff of intent:** it is a diff of *current models vs. current DB*. Reviewed, manual edits to generated files are expected and encouraged (e.g., to add `postgresql_using` casts or data backfills).
* **Downgrades:** keep a working `downgrade()` in every migration so teammates can roll back cleanly.