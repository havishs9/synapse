"""Apply supabase/migrations/*.sql to the database in SUPABASE_DB_URL, in order, each in one transaction.

Applied versions are recorded in supabase_migrations.schema_migrations (the table the Supabase CLI uses), so
`supabase db push` would see them as applied too.
  .venv/bin/python scripts/db_migrate.py            apply pending migrations
  .venv/bin/python scripts/db_migrate.py --status   list applied and pending
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402

MIGRATIONS = ROOT / "supabase" / "migrations"


def main() -> int:
    import psycopg
    url = config.env("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is empty in .env", file=sys.stderr)
        return 1
    files = sorted(MIGRATIONS.glob("*.sql"))
    with psycopg.connect(url, connect_timeout=15) as c:
        c.execute("create schema if not exists supabase_migrations")
        c.execute("create table if not exists supabase_migrations.schema_migrations "
                  "(version text primary key, statements text[], name text)")
        c.commit()
        applied = {r[0] for r in c.execute("select version from supabase_migrations.schema_migrations")}
        for f in files:
            version, _, name = f.stem.partition("_")
            if version in applied:
                print(f"applied   {f.name}")
                continue
            if "--status" in sys.argv:
                print(f"pending   {f.name}")
                continue
            sql = f.read_text()
            with c.transaction():
                c.execute(sql)
                c.execute("insert into supabase_migrations.schema_migrations (version, statements, name) "
                          "values (%s, %s, %s)", (version, [sql], name))
            print(f"applied   {f.name} (now)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
