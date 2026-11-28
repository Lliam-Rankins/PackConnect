"""Run each test in a fresh schema on a dedicated local PostgreSQL instance."""

import os
import unittest

import app as portal
from common.temp_schema import create_schema, drop_schema, require_local_database
from fake_embedder import FakeEmbedder
from test_seeds import seed_students


class PostgresTestCase(unittest.TestCase):
    def setUp(self):
        database_url = os.getenv("TEST_DATABASE_URL")
        require_local_database(database_url)
        self.original_url = portal.app.config.get("SUPABASE_DB_URL")
        portal.app.config["SUPABASE_DB_URL"] = database_url
        self.addCleanup(self.restore_database)
        self.original_embedder = portal.app.config.get("EMBEDDER")
        portal.app.config["EMBEDDER"] = FakeEmbedder()
        self.addCleanup(portal.app.config.__setitem__, "EMBEDDER", self.original_embedder)
        self.schema = create_schema(database_url)
        self.addCleanup(drop_schema, database_url, self.schema)
        portal.app.config["TEST_DB_SCHEMA"] = self.schema
        with portal.get_db() as db:
            seed_students(db)
        portal.initialize_database()

    def restore_database(self):
        portal.app.config["SUPABASE_DB_URL"] = self.original_url
        portal.app.config.pop("TEST_DB_SCHEMA", None)
