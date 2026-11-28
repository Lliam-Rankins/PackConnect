"""Throwaway PostgreSQL schemas with the project's migrations applied (tests and the M0 eval)."""

from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from database import connect_database
from migrate import MIGRATIONS, migration_sql

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def require_local_database(database_url):
    if not database_url:
        raise RuntimeError("Set TEST_DATABASE_URL to a dedicated local PostgreSQL database.")
    if conninfo_to_dict(database_url).get("host") not in LOCAL_HOSTS:
        raise RuntimeError("Tests require a local PostgreSQL host; never use your live Supabase URL.")


def create_schema(database_url):
    """Create a fresh schema, apply every migration to it and return its name."""
    require_local_database(database_url)
    schema = "test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        # Minimal Supabase-owned roles/Auth table for vanilla PostgreSQL CI.
        for role in ("anon", "authenticated", "service_role"):
            if not db.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                db.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        db.execute("CREATE SCHEMA IF NOT EXISTS auth")
        db.execute("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY)")
        db.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS email text")
        db.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS email_confirmed_at timestamptz")
    with connect_database(database_url, schema) as db:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            db.execute(migration_sql(path).replace("public.", schema + "."), prepare=False)
    return schema


def drop_schema(database_url, schema):
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
