"""Shared advisor eligibility SQL, plus the matching migration's schema objects."""

import unittest

import app as portal
from common.advisor_sql import COMPLETED_COURSE_KEY, advisor_conditions
from postgres_test_support import PostgresTestCase

VECTOR = "extensions.vector"


class AdvisorConditionsTests(unittest.TestCase):
    def test_no_viewer_no_course_only_requires_registration(self):
        conditions, params, codes = advisor_conditions(None, "")
        self.assertEqual(len(conditions), 1)
        self.assertEqual((params, codes), ([], []))

    def test_viewer_adds_two_way_block_filter_with_two_params(self):
        conditions, params, _ = advisor_conditions(7, "")
        self.assertEqual(len(conditions), 2)
        self.assertIn("student_blocks", conditions[1])
        self.assertEqual(params, [7, 7])

    def test_known_course_matches_normalized_key_only(self):
        conditions, params, codes = advisor_conditions(None, " csc-510 ")
        self.assertEqual(codes, ["CSC510"])
        self.assertEqual(params, [["CSC510"]])
        self.assertIn(COMPLETED_COURSE_KEY, conditions[-1])

    def test_unknown_course_adds_title_matched_codes(self):
        _, _, codes = advisor_conditions(None, "Software Engineering")
        self.assertEqual(codes[0], "SOFTWAREENGINEERING")
        self.assertIn("CSC510", codes[1:])

    def test_param_order_is_viewer_then_course(self):
        conditions, params, codes = advisor_conditions(3, "CSC 510")
        self.assertEqual(params, [3, 3, codes])
        self.assertEqual(sum(c.count("%s") for c in conditions), 3)


class SearchParityTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.client = portal.app.test_client()
        self.ids = {}
        with portal.get_db() as db:
            for table in ("accounts", "completed_courses", "students"):
                db.execute(f"DELETE FROM {table}")
            for name in ("Ada", "Blake", "Casey"):
                sid = db.execute("""INSERT INTO students (name, program, year, willing_to_advise)
                                    VALUES (%s, 'CS', 'Second Year', true) RETURNING id""", (name,)).fetchone()["id"]
                self.ids[name] = sid
                db.execute("INSERT INTO accounts (student_id, email, password_hash) VALUES (%s,%s,'x')",
                           (sid, f"{name.lower()}@example.test"))
                db.execute("INSERT INTO completed_courses (student_id, course_code) VALUES (%s,'CSC 510')", (sid,))
            db.execute("INSERT INTO student_blocks (blocker_id, blocked_id) VALUES (%s,%s)",
                       (self.ids["Blake"], self.ids["Ada"]))

    def search(self, viewer=None, **query):
        with self.client.session_transaction() as session:
            session.clear()
            if viewer:
                session["student_id"] = self.ids[viewer]
        return self.client.get("/api/students/search", query_string=query).get_json()

    def test_blocked_pair_hidden_in_both_directions_only_for_involved_viewers(self):
        names = lambda body: sorted(s["name"] for s in body["students"])
        self.assertEqual(names(self.search("Ada", course="CSC510")), ["Ada", "Casey"])
        self.assertEqual(names(self.search("Blake", course="CSC510")), ["Blake", "Casey"])
        self.assertEqual(names(self.search(None, course="CSC510")), ["Ada", "Blake", "Casey"])

    def test_title_search_matches_catalog_codes_and_reports_them(self):
        body = self.search(course="Software Engineering")
        self.assertEqual(len(body["students"]), 3)
        self.assertIn("CSC510", body["course_codes"])

    def test_unknown_course_returns_no_students_but_echoes_code(self):
        body = self.search(course="ZZZ 999")
        self.assertEqual(body, {"students": [], "course_codes": ["ZZZ999"]})


class MatchingSchemaTests(PostgresTestCase):
    def student(self, **fields):
        with portal.get_db() as db:
            return db.execute("INSERT INTO students (name, program, year, advice_topics, bio) VALUES ('Zed','CS','Second Year',%s,%s) RETURNING id",
                              (fields.get("topics", ""), fields.get("bio", ""))).fetchone()["id"]

    def test_search_vector_is_generated_and_follows_updates(self):
        sid = self.student(topics="databases", bio="enjoys hiking")
        with portal.get_db() as db:
            q = "SELECT search_vector @@ plainto_tsquery('english', %s) AS hit FROM students WHERE id=%s"
            self.assertTrue(db.execute(q, ("database", sid)).fetchone()["hit"])
            self.assertFalse(db.execute(q, ("compilers", sid)).fetchone()["hit"])
            db.execute("UPDATE students SET advice_topics='compilers' WHERE id=%s", (sid,))
            self.assertTrue(db.execute(q, ("compilers", sid)).fetchone()["hit"])
            self.assertIn("'compil':1A",
                          db.execute("SELECT search_vector::text AS v FROM students WHERE id=%s", (sid,)).fetchone()["v"])

    def test_embeddings_store_384_dim_vectors_and_rank_by_cosine(self):
        near, far = self.student(), self.student()
        unit = lambda i: "[" + ",".join("1" if j == i else "0" for j in range(384)) + "]"
        with portal.get_db() as db:
            for sid, vec in ((near, unit(0)), (far, unit(1))):
                db.execute(f"""INSERT INTO profile_embeddings (student_id, field, embedding, model, source_hash)
                               VALUES (%s,'bio',%s::{VECTOR},'m','h')""", (sid, vec))
            rows = db.execute(f"""
                SELECT student_id, 1 - (embedding OPERATOR(extensions.<=>) %s::{VECTOR}) AS sim
                FROM profile_embeddings ORDER BY sim DESC""", (unit(0),)).fetchall()
        self.assertEqual([r["student_id"] for r in rows], [near, far])
        self.assertAlmostEqual(rows[0]["sim"], 1.0)
        self.assertAlmostEqual(rows[1]["sim"], 0.0)

    def test_embeddings_reject_unknown_field_and_wrong_dimension(self):
        import psycopg
        sid = self.student()
        for field, vec in (("hobbies", None), ("bio", "[1,2,3]")):
            with self.subTest(field=field), self.assertRaises(psycopg.Error), portal.get_db() as db:
                db.execute(f"""INSERT INTO profile_embeddings (student_id, field, embedding, model, source_hash)
                               VALUES (%s,%s,%s::{VECTOR},'m','h')""", (sid, field, vec))

    def test_embeddings_cascade_when_student_deleted(self):
        sid = self.student()
        with portal.get_db() as db:
            db.execute("INSERT INTO profile_embeddings (student_id, field, model, source_hash) VALUES (%s,'bio','m','h')", (sid,))
            db.execute("DELETE FROM students WHERE id=%s", (sid,))
            self.assertEqual(db.execute("SELECT count(*) AS n FROM profile_embeddings").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
