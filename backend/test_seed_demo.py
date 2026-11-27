import unittest

import app as portal
import seed_demo
from fake_embedder import FakeEmbedder
from postgres_test_support import PostgresTestCase

PASSWORD = "a long demo test password"


class SeedDemoTests(PostgresTestCase):
    def seed(self):
        with portal.get_db() as db:
            return seed_demo.seed(db, PASSWORD, FakeEmbedder())

    def sign_in(self, client, person):
        response = client.post("/api/auth/login", json={"email": person.email, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)

    def test_seed_creates_accounts_that_can_sign_in(self):
        self.assertEqual(self.seed(), (True, 0))
        self.sign_in(portal.app.test_client(), seed_demo.ADVISORS[0])

    def test_second_run_changes_nothing(self):
        self.seed()
        with portal.get_db() as db:
            before = db.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"]
        self.assertEqual(self.seed(), (False, 0))
        with portal.get_db() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"], before)

    def test_demo_advisors_rank_with_review_and_qa_reasons(self):
        self.seed()
        client = portal.app.test_client()
        self.sign_in(client, seed_demo.STUDENTS[0])
        body = client.get("/api/students/recommendations",
                          query_string={"course": "CSC 510", "need": "unit testing with pytest"}).get_json()
        names = [student["name"] for student in body["students"]]
        self.assertEqual(names[0], "Priya Raman")
        self.assertEqual(len(names), len([a for a in seed_demo.ADVISORS if "CSC 510" in a.completed]))
        reason_types = {reason["type"] for reason in body["students"][0]["match"]["reasons"]}
        self.assertTrue({"keyword", "rating", "qa_help"} <= reason_types)

    def test_demo_students_are_not_advisors(self):
        self.seed()
        client = portal.app.test_client()
        self.sign_in(client, seed_demo.STUDENTS[1])
        body = client.get("/api/students/recommendations",
                          query_string={"course": "CSC 510", "need": "anything"}).get_json()
        names = {student["name"] for student in body["students"]}
        self.assertFalse(names & {person.name for person in seed_demo.STUDENTS})


class SeedGuardTests(unittest.TestCase):
    def test_only_local_hosts_count_as_local(self):
        self.assertTrue(seed_demo.is_local("postgresql://u@127.0.0.1:5432/db"))
        self.assertTrue(seed_demo.is_local("postgresql://u@localhost/db"))
        self.assertFalse(seed_demo.is_local("postgresql://u@db.example.supabase.co:5432/postgres"))
        self.assertFalse(seed_demo.is_local(""))

    def test_hosted_database_is_refused_without_flag(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"SUPABASE_DB_URL": "postgresql://u@db.example.supabase.co/postgres"}), \
                mock.patch.object(seed_demo, "load_dotenv"):
            with self.assertRaises(SystemExit) as raised:
                seed_demo.main([])
        self.assertIn("--allow-hosted", str(raised.exception))
