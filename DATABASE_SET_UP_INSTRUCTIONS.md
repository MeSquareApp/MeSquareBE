## Database Setup & Migrations (Alembic + Supabase)

We use SQLAlchemy 2.0 for our database models and Alembic to manage schema migrations. Our database is hosted on Supabase and accessed asynchronously using the `asyncpg` driver.

### 1. Prerequisites
Ensure your `.env` file contains the correct Supabase connection string configured for async access (check pinned message on discord for the connection string). It should have the following format:

```env
database_url="postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres"
```

### 2. Migration Workflow
Whenever you create new tables or modify existing ones in the `app/models/` directory, follow these steps to push the changes to Supabase:

**Step 1: Activate the virtual environment**
Ensure you are operating inside the isolated project environment to access the correct dependencies.
```bash
source .venv/bin/activate
```

**Step 2: Generate a new migration script**
After writing or updating your Python models, auto-generate the migration file. 
*(Note: We use the `python -m alembic` prefix instead of the standalone `alembic` command to guarantee the terminal uses our virtual environment, bypassing any global Python/Anaconda conflicts).*
```bash
python -m alembic revision --autogenerate -m "Brief description of your changes"
```
*Always briefly review the newly generated file inside the `alembic/versions/` folder to verify the schema changes are correct before applying them.*

**Step 3: Apply the migration to Supabase**
Execute the migration to build or update the tables in the remote database.
```bash
python -m alembic upgrade head
```

### 3. Helpful Commands
* **Undo the last applied migration:** 
  ```bash
  python -m alembic downgrade -1
  ```
* **View the migration history:** 
  ```bash
  python -m alembic history
  ```