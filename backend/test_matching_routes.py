"""GET /api/students/recommendations end to end with a deterministic embedder."""

import unittest

import app as portal
from fake_embedder import FakeEmbedder
from matching import profile_vectors
from matching.routes import QueryVectorCache
from postgres_test_support import PostgresTestCase

URL = "/api/students/recommendations"
PROFILE_KEYS = {"id", "name", "program", "year", "skills", "advice_topics", "willing_to_advise",
                "max_open_requests", "pause_until", "open_request_count", "availability_status",
                "accepting_requests"}
BREAKDOWN_KEYS = {"quality", "topic_fit", "keyword", "semantic", "rating", "qa_help", "capacity"}


class QueryVectorCacheTests(unittest.TestCase):
    def test_caches_per_model_and_need_and_evicts_least_recent(self):
        cache, embedder = QueryVectorCache(maxsize=2), FakeEmbedder()
        first = cache.vector(embedder, "graphs")
        self.assertEqual(cache.vector(embedder, "graphs"), first)
        self.assertEqual(embedder.query_calls, 1)
        cache.vector(embedder, "trees")
        cache.vector(embedder, "graphs")
        cache.vector(embedder, "heaps")  # evicts "trees"
        cache.vector(embedder, "graphs")
        self.assertEqual(embedder.query_calls, 3)
        cache.vector(embedder, "trees")
        self.assertEqual(embedder.query_calls, 4)

    def test_failures_return_none_and_are_not_cached(self):
        cache, embedder = QueryVectorCache(), FakeEmbedder(fail=True)
        with self.assertLogs("matching.routes", "WARNING"):
            self.assertIsNone(cache.vector(embedder, "graphs"))
        embedder.fail = False
        self.assertIsNotNone(cache.vector(embedder, "graphs"))


class RecommendationRouteTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.embedder = FakeEmbedder(aliases={"postgres": "database", "postgresql": "database"})
        self.embedder.model_name = "fake-hash-384-route-aliases"  # keeps the shared query cache consistent
        portal.app.config["EMBEDDER"] = self.embedder
        self.ids = {}
        self.viewer = self.student("Vera", course=None)
        self.client = portal.app.test_client()
        with self.client.session_transaction() as session:
            session["student_id"] = self.viewer

    def student(self, name, course="CSC 510", registered=True, **fields):
        columns = {"name": name, "program": "Computer Science", "year": "Second Year",
                   "willing_to_advise": True, **fields}
        with portal.get_db() as db:
            student_id = db.execute(
                f"INSERT INTO students ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
                list(columns.values())).fetchone()["id"]
            if registered:
                db.execute("INSERT INTO accounts (student_id, email, password_hash) VALUES (%s, %s, 'unused')",
                           (student_id, f"{name.lower()}@example.test"))
            if course:
                db.execute("INSERT INTO completed_courses (student_id, course_code) VALUES (%s, %s)",
                           (student_id, course))
            self.assertTrue(profile_vectors.refresh(db, self.embedder, student_id))
        self.ids[name] = student_id
        return student_id

    def recommend(self, status=200, **query):
        query = {"course": "CSC 510", "need": "projects", **query}
        response = self.client.get(URL, query_string=query)
        self.assertEqual(response.status_code, status, response.get_json())
        return response.get_json()

    def names(self, **query):
        return [row["name"] for row in self.recommend(**query)["students"]]

    def review(self, advisor, rating):
        with portal.get_db() as db:
            request_id = db.execute("""
                INSERT INTO advice_requests (sender_id, recipient_id, course_code, advice_topic, message, status)
                VALUES (%s, %s, 'CSC 510', 'Projects', 'Earlier advice', 'completed') RETURNING id
            """, (self.viewer, self.ids[advisor])).fetchone()["id"]
            db.execute("INSERT INTO advice_reviews (request_id, rating) VALUES (%s, %s)", (request_id, rating))

    def helpful_answer(self, asker_id, answerer, course="CSC 510"):
        with portal.get_db() as db:
            question_id = db.execute("""
                INSERT INTO course_questions (author_id, course_code, title, body)
                VALUES (%s, %s, 'Question', 'Details') RETURNING id""", (asker_id, course)).fetchone()["id"]
            answer_id = db.execute("""
                INSERT INTO course_answers (question_id, author_id, body) VALUES (%s, %s, 'Answer') RETURNING id
            """, (question_id, self.ids[answerer])).fetchone()["id"]
            db.execute("INSERT INTO course_helpful_answers (question_id, answer_id) VALUES (%s, %s)",
                       (question_id, answer_id))

    def test_requires_valid_sign_in(self):
        response = portal.app.test_client().get(URL, query_string={"course": "CSC 510", "need": "projects"})
        self.assertEqual((response.status_code, response.get_json()),
                         (401, {"error": "Sign in to get recommendations."}))
        with self.client.session_transaction() as session:
            session["auth_version"] = 99
        self.recommend(401)

    def test_validates_course_and_need(self):
        for query in ({"course": ""}, {"course": "   "}, {"need": ""}, {"need": "   "},
                      {"need": "x" * 301}):
            with self.subTest(query=query):
                self.assertIn("error", self.recommend(400, **query))
        self.assertEqual(self.recommend(need="x" * 300)["students"], [])
        self.student("Ana", advice_topics="Projects")
        self.assertEqual(self.names(need="the of !!!"), ["Ana"])  # stopwords only: no keyword query

    def test_eligibility_and_hard_filters_match_search(self):
        self.student("Ana")
        self.student("Blocker")
        self.student("Blocked")
        self.student("OtherCourse", course="CSC 540")
        self.student("Unregistered", registered=False)
        self.student("Paused", pause_until="2999-01-01")
        self.student("Full", max_open_requests=1)
        self.student("Stats", program="Statistics")
        with portal.get_db() as db:
            db.execute("INSERT INTO completed_courses (student_id, course_code) VALUES (%s, 'CSC 510')", (self.viewer,))
            db.execute("INSERT INTO student_blocks (blocker_id, blocked_id) VALUES (%s, %s), (%s, %s)",
                       (self.ids["Blocker"], self.viewer, self.viewer, self.ids["Blocked"]))
            db.execute("""INSERT INTO advice_requests (sender_id, recipient_id, course_code, advice_topic, message)
                          VALUES (%s, %s, 'CSC 510', 'Projects', 'Help')""", (self.ids["Ana"], self.ids["Full"]))
        self.assertEqual(sorted(self.names()), ["Ana", "Stats"])
        self.assertEqual(sorted(self.names(available="false")), ["Ana", "Full", "Paused", "Stats"])
        self.assertEqual(self.names(program="statistics"), ["Stats"])
        self.assertEqual(self.names(course="csc-510", year="first"), [])
        search = self.client.get("/api/students/search", query_string={"course": "CSC 510"}).get_json()
        self.assertEqual(sorted(row["name"] for row in search["students"]), ["Ana", "Stats", "Vera"])

    def test_semantic_synonym_beats_unrelated_profile(self):
        self.student("Writer", advice_topics="Resume writing")
        self.student("Dba", advice_topics="Database")
        body = self.recommend(need="postgres")
        self.assertEqual([row["name"] for row in body["students"]], ["Dba", "Writer"])
        best = body["students"][0]["match"]
        self.assertEqual(best["breakdown"]["keyword"], 0)
        self.assertGreater(best["breakdown"]["semantic"], 0.9)
        self.assertIn({"type": "semantic", "field": "advice_topics"}, best["reasons"])

    def test_best_chunk_of_a_multi_topic_field_beats_a_loosely_related_phrase(self):
        self.student("Loose", advice_topics="Database theory history essay writing seminar")
        self.student("Multi", advice_topics="Push notifications; Demo day; Database; Query speed")
        body = self.recommend(need="postgres")
        self.assertEqual([row["name"] for row in body["students"]], ["Multi", "Loose"])
        self.assertGreater(body["students"][0]["match"]["breakdown"]["semantic"], 0.9)

    def test_keyword_matches_are_reported_as_need_words(self):
        self.student("Javi", skills="Java")
        self.student("Pia", skills="Python, pytest")
        body = self.recommend(need="Help with Python and the testing plan")
        self.assertEqual([row["name"] for row in body["students"]], ["Pia", "Javi"])
        pia, javi = (row["match"] for row in body["students"])
        self.assertIn({"type": "keyword", "terms": ["Python"]}, pia["reasons"])
        self.assertGreater(pia["breakdown"]["keyword"], 0)
        self.assertNotIn("keyword", [reason["type"] for reason in javi["reasons"]])

    def test_ratings_and_course_helpful_answers_rank_and_explain(self):
        for name in ("Plain", "Proven", "SelfMarker"):
            self.student(name, advice_topics="Projects")
        for rating in (5, 5, 4):
            self.review("Proven", rating)
        asker = self.student("Asker", course=None)
        self.helpful_answer(asker, "Proven")
        self.helpful_answer(asker, "Proven", course="CSC 510")
        self.helpful_answer(asker, "Proven", course="CSC 540")  # another course
        self.helpful_answer(self.ids["Proven"], "Proven")  # marked on their own question
        self.helpful_answer(self.ids["SelfMarker"], "SelfMarker")
        body = self.recommend(need="projects")
        rows = {row["name"]: row for row in body["students"]}
        self.assertEqual(body["students"][0]["name"], "Proven")
        reasons = rows["Proven"]["match"]["reasons"]
        self.assertIn({"type": "rating", "average": 14 / 3, "count": 3}, reasons)
        self.assertIn({"type": "qa_help", "count": 2}, reasons)
        self.assertEqual(rows["Proven"]["review_summary"], {"average_rating": 14 / 3, "review_count": 3})
        self.assertEqual(rows["SelfMarker"]["match"]["breakdown"]["qa_help"], 0)
        self.assertEqual(rows["SelfMarker"]["match"]["breakdown"], rows["Plain"]["match"]["breakdown"])
        self.assertEqual(rows["Plain"]["review_summary"], {"average_rating": None, "review_count": 0})

    def test_query_embedding_failure_falls_back_to_keywords(self):
        self.student("Dba", advice_topics="Database")
        self.student("Indexer", skills="Indexes")
        self.embedder.fail = True
        with self.assertLogs("matching.routes", "WARNING"):
            body = self.recommend(need="postgres indexes after an outage")
        self.assertEqual([row["name"] for row in body["students"]], ["Indexer", "Dba"])
        self.assertTrue(all(row["match"]["breakdown"]["semantic"] is None for row in body["students"]))

    def test_response_contract(self):
        self.student("Ana", advice_topics="Projects", skills="Python", max_open_requests=4)
        self.student("Ben", advice_topics="Workload")
        body = self.recommend(course=" csc 510 ", need="projects in python")
        self.assertEqual(set(body), {"students", "course_codes"})
        self.assertEqual(body["course_codes"], ["CSC510"])
        scores = [row["match"]["score"] for row in body["students"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for row in body["students"]:
            self.assertEqual(set(row), PROFILE_KEYS | {"review_summary", "match"})
            self.assertEqual(set(row["match"]), {"score", "breakdown", "reasons"})
            self.assertEqual(set(row["match"]["breakdown"]), BREAKDOWN_KEYS)
            self.assertTrue(0 <= row["match"]["score"] <= 1)
        ana = body["students"][0]
        self.assertEqual(ana["name"], "Ana")
        self.assertIn({"type": "capacity", "free": 4}, ana["match"]["reasons"])
        self.assertTrue(ana["accepting_requests"])

    def test_same_need_is_embedded_once(self):
        self.student("Ana", advice_topics="Projects")
        calls = self.embedder.query_calls
        self.recommend(need="a need asked twice")
        self.recommend(need="a need asked twice")
        self.assertEqual(self.embedder.query_calls, calls + 1)

    def test_results_are_capped_at_fifty(self):
        for index in range(52):
            self.student(f"Advisor{index:02d}")
        self.assertEqual(len(self.recommend()["students"]), 50)

    def test_search_endpoint_is_unchanged(self):
        self.student("Ben", advice_topics="Projects")
        self.student("Ana", advice_topics="Projects")
        body = self.client.get("/api/students/search", query_string={"course": "CSC 510"}).get_json()
        self.assertEqual([row["name"] for row in body["students"]], ["Ana", "Ben"])
        self.assertTrue(all("match" not in row for row in body["students"]))
        self.assertEqual(body["course_codes"], ["CSC510"])


if __name__ == "__main__":
    unittest.main()
