"""Profile embeddings follow profile saves, survive embedder failures and are swept later."""

import unittest

import app as portal
from fake_embedder import FakeEmbedder
from matching import profile_vectors
from postgres_test_support import PostgresTestCase


class RecordingEmbedder(FakeEmbedder):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.passages = []

    def embed_passages(self, texts):
        self.passages.append(list(texts))
        return super().embed_passages(texts)


class ProfileVectorTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.embedder = RecordingEmbedder()
        portal.app.config["EMBEDDER"] = self.embedder
        self.client = portal.app.test_client()
        with portal.get_db() as db:  # seeded profiles are unembedded; keep sweeps focused
            db.execute("DELETE FROM completed_courses")
            db.execute("DELETE FROM students")

    def register(self, **changes):
        payload = dict(name="Robin", email="robin@example.test", password="a long test password",
                       program="MS Computer Science", year="First Year", willing_to_advise=True,
                       bio="I love distributed systems.", interests="Compilers",
                       completed_courses=["CSC 510"])
        payload.update(changes)
        response = self.client.post("/api/auth/register", json=payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        student_id = response.get_json()["student"]["id"]
        with self.client.session_transaction() as session:
            session["student_id"] = student_id
        return student_id

    def update(self, student_id, **changes):
        payload = dict(name="Robin", program="MS Computer Science", year="First Year",
                       bio="I love distributed systems.", interests="Compilers", skills="", advice_topics="",
                       completed_courses=["CSC 510"])
        payload.update(changes)
        response = self.client.put(f"/api/students/{student_id}", json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["student"]

    def rows(self, student_id):
        with portal.get_db() as db:
            rows = db.execute("""
                SELECT field, chunk, embedding IS NOT NULL AS embedded, model, source_hash, attempts, last_error_at
                FROM profile_embeddings WHERE student_id = %s""", (student_id,)).fetchall()
        return {row["field"]: row for row in rows if row["chunk"] == 0}

    def chunk_counts(self, student_id):
        with portal.get_db() as db:
            rows = db.execute("""SELECT field, count(*) AS n FROM profile_embeddings
                                 WHERE student_id = %s GROUP BY field""", (student_id,)).fetchall()
        return {row["field"]: row["n"] for row in rows}

    def pending(self, model_name=FakeEmbedder.model_name):
        with portal.get_db() as db:
            return profile_vectors.pending_student_ids(db, model_name)

    def test_fields_follow_scoring_weights(self):
        self.assertEqual(profile_vectors.FIELDS, ("advice_topics", "skills", "interests", "bio"))

    def test_register_embeds_non_empty_fields_in_one_batch(self):
        student_id = self.register()
        rows = self.rows(student_id)
        self.assertEqual(set(rows), {"bio", "interests"})
        self.assertTrue(all(row["embedded"] and row["attempts"] == 0 for row in rows.values()))
        self.assertEqual(rows["bio"]["model"], FakeEmbedder.model_name)
        self.assertEqual(rows["bio"]["source_hash"],
                         profile_vectors.source_hash(FakeEmbedder.model_name, "I love distributed systems."))
        self.assertEqual(self.embedder.passages, [["Compilers", "I love distributed systems"]])
        self.assertEqual(self.pending(), [])

    def test_update_embeds_only_changed_fields_and_skips_unchanged_saves(self):
        student_id = self.register()
        self.embedder.passages.clear()
        self.update(student_id, skills="Python, SQL")
        self.assertEqual(self.embedder.passages, [["Python", "SQL"]])
        self.update(student_id, skills="Python, SQL")
        self.assertEqual(self.embedder.passages, [["Python", "SQL"]])
        self.update(student_id, skills="Python, SQL", bio="Now into databases.")
        self.assertEqual(self.embedder.passages[-1], ["Now into databases"])
        self.assertEqual(set(self.rows(student_id)), {"bio", "interests", "skills"})

    def test_emptied_field_row_is_deleted(self):
        student_id = self.register()
        self.update(student_id, interests="   ")
        self.assertEqual(set(self.rows(student_id)), {"bio"})
        self.assertEqual(self.pending(), [])

    def test_failing_embedder_still_saves_profile_and_sweep_fills_it_later(self):
        self.embedder.fail = True
        with self.assertLogs("matching.profile_vectors", "WARNING") as logs:
            student_id = self.register()
        self.assertNotIn("distributed", "".join(logs.output))
        profile = self.client.get(f"/api/students/{student_id}").get_json()["student"]
        self.assertEqual(profile["bio"], "I love distributed systems.")
        self.assertEqual(profile["completed_courses"], ["CSC 510"])
        rows = self.rows(student_id)
        self.assertEqual(set(rows), {"bio", "interests"})
        self.assertTrue(all(not r["embedded"] and r["attempts"] == 1 and r["last_error_at"] for r in rows.values()))
        self.assertEqual(self.pending(), [student_id])

        self.embedder.fail = False
        self.assertEqual(profile_vectors.sweep(portal.get_db, self.embedder), (1, 0))
        rows = self.rows(student_id)
        self.assertTrue(all(r["embedded"] and r["attempts"] == 0 and r["last_error_at"] is None
                            for r in rows.values()))
        self.assertEqual(self.pending(), [])

    def test_sweep_gives_up_after_max_attempts_until_text_changes(self):
        self.embedder.fail = True
        with self.assertLogs("matching.profile_vectors", "WARNING"):
            student_id = self.register()
            for _ in range(profile_vectors.MAX_ATTEMPTS - 1):
                self.assertEqual(profile_vectors.sweep(portal.get_db, self.embedder), (0, 1))
        self.assertEqual({r["attempts"] for r in self.rows(student_id).values()}, {profile_vectors.MAX_ATTEMPTS})
        self.assertEqual(self.pending(), [])
        self.assertEqual(profile_vectors.sweep(portal.get_db, self.embedder), (0, 0))

        self.embedder.fail = False
        calls = self.embedder.passage_calls
        self.update(student_id)  # same text: still given up
        self.assertEqual(self.embedder.passage_calls, calls)
        self.update(student_id, bio="Fresh text.")
        self.assertTrue(self.rows(student_id)["bio"]["embedded"])
        self.assertFalse(self.rows(student_id)["interests"]["embedded"])

    def test_multi_phrase_field_creates_one_chunk_per_phrase_in_one_batch(self):
        student_id = self.register(interests="Compilers; Graphics, compilers")
        self.assertEqual(self.chunk_counts(student_id), {"bio": 1, "interests": 2})
        self.assertEqual(self.embedder.passages, [["Compilers", "Graphics", "I love distributed systems"]])
        self.assertEqual(self.pending(), [])
        with portal.get_db() as db:
            hashes = db.execute("SELECT DISTINCT source_hash FROM profile_embeddings WHERE field = 'interests'"
                                " AND student_id = %s", (student_id,)).fetchall()
        self.assertEqual([h["source_hash"] for h in hashes],
                         [profile_vectors.source_hash(FakeEmbedder.model_name, "Compilers; Graphics, compilers")])

    def test_editing_a_field_replaces_chunks_and_removes_stale_ones(self):
        student_id = self.register(interests="a1; b2; c3; d4")
        self.assertEqual(self.chunk_counts(student_id)["interests"], 4)
        self.update(student_id, interests="a1; b2")
        self.assertEqual(self.chunk_counts(student_id)["interests"], 2)
        self.assertEqual(self.pending(), [])
        self.update(student_id, interests="  ")
        self.assertNotIn("interests", self.chunk_counts(student_id))
        self.assertEqual(self.pending(), [])

    def test_stale_hash_on_any_chunk_is_pending(self):
        student_id = self.register(interests="a1; b2; c3")
        with portal.get_db() as db:
            db.execute("UPDATE profile_embeddings SET source_hash = 'old' WHERE student_id = %s"
                       " AND field = 'interests' AND chunk = 2", (student_id,))
        self.assertEqual(self.pending(), [student_id])
        self.assertEqual(profile_vectors.sweep(portal.get_db, self.embedder), (1, 0))
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.chunk_counts(student_id)["interests"], 3)

    def test_failure_collapses_to_one_row_and_retry_fills_all_chunks(self):
        student_id = self.register(interests="a1; b2; c3")
        self.embedder.fail = True
        with self.assertLogs("matching.profile_vectors", "WARNING"):
            self.update(student_id, interests="a1; b2; c3; d4")
        self.assertEqual(self.chunk_counts(student_id)["interests"], 1)
        self.assertFalse(self.rows(student_id)["interests"]["embedded"])
        self.assertEqual(self.pending(), [student_id])
        self.embedder.fail = False
        self.assertEqual(profile_vectors.sweep(portal.get_db, self.embedder), (1, 0))
        self.assertEqual(self.chunk_counts(student_id)["interests"], 4)
        self.assertEqual(self.pending(), [])

    def test_punctuation_only_field_is_embedded_whole(self):
        student_id = self.register(interests="...")
        self.assertEqual(self.chunk_counts(student_id)["interests"], 1)
        self.assertEqual(self.pending(), [])

    def test_wrong_dimension_vectors_count_as_failures(self):
        class ShortEmbedder(FakeEmbedder):
            def embed_passages(self, texts):
                return [[1.0, 0.0] for _ in texts]
        with self.assertLogs("matching.profile_vectors", "WARNING"):
            portal.app.config["EMBEDDER"] = ShortEmbedder()
            student_id = self.register()
        self.assertEqual({r["attempts"] for r in self.rows(student_id).values()}, {1})

    def test_model_change_marks_profiles_pending(self):
        student_id = self.register()
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.pending("another-model"), [student_id])

    def test_refresh_failure_keeps_callers_transaction_usable(self):
        student_id = self.register()
        with portal.get_db() as db:
            db.execute("UPDATE students SET bio = 'Changed inside caller' WHERE id = %s", (student_id,))
            with self.assertLogs("matching.profile_vectors", "WARNING"):
                self.assertFalse(profile_vectors.refresh(db, FakeEmbedder(fail=True), student_id))
            self.assertEqual(db.execute("SELECT bio FROM students WHERE id = %s", (student_id,)).fetchone()["bio"],
                             "Changed inside caller")
        self.assertEqual(self.rows(student_id)["bio"]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()


class StartupSweepTests(PostgresTestCase):
    def test_missing_tables_log_migration_hint_instead_of_raising(self):
        with portal.get_db() as db:
            db.execute("DROP TABLE profile_embeddings")
        with self.assertLogs(portal.app.logger, "WARNING") as logs:
            portal.sweep_profile_embeddings()
        self.assertIn("migrate.py", logs.output[0])

    def test_unexpected_failure_logs_retry_hint(self):
        original = profile_vectors.sweep
        profile_vectors.sweep = lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))
        self.addCleanup(setattr, profile_vectors, "sweep", original)
        with self.assertLogs(portal.app.logger, "WARNING") as logs:
            portal.sweep_profile_embeddings()
        self.assertIn("embed_profiles.py", logs.output[0])
