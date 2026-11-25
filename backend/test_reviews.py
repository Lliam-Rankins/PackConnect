"""Reviews are bound to completed advice and its authenticated requester."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from psycopg.errors import UniqueViolation

import app as portal
from migrate import MIGRATIONS, migration_sql
from postgres_test_support import PostgresTestCase


class AdvisorReviewTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.ids = []
        with portal.get_db() as db:
            for name in ("Requester", "Advisor", "Outsider"):
                student_id = db.execute("""
                    INSERT INTO students (name, program, year, willing_to_advise)
                    VALUES (%s, 'CS', '1', true) RETURNING id
                """, (name,)).fetchone()["id"]
                db.execute("""
                    INSERT INTO accounts (student_id, email, password_hash)
                    VALUES (%s, %s, 'unused test hash')
                """, (student_id, name.lower() + "@example.test"))
                self.ids.append(student_id)
        self.sender = self.client_for(self.ids[0])
        self.advisor = self.client_for(self.ids[1])
        self.outsider = self.client_for(self.ids[2])

    def client_for(self, student_id):
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["student_id"] = student_id
        return client

    def completed_request(self, course="CSC 510"):
        response = self.sender.post("/api/requests", json={
            "recipient_id": self.ids[1], "course_code": course,
            "advice_topic": "Projects", "message": "Please help me prepare.",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        request_id = response.get_json()["request"]["id"]
        self.assertEqual(self.advisor.patch(f"/api/requests/{request_id}", json={"status": "accepted"}).status_code, 200)
        self.assertEqual(self.sender.patch(f"/api/requests/{request_id}", json={"status": "completed"}).status_code, 200)
        return request_id

    def test_completed_advice_review_persists_and_uses_request_course_and_identity(self):
        request_id = self.completed_request(" csc 510 ")
        response = self.sender.post(f"/api/requests/{request_id}/review", json={
            "rating": 5, "comment": " Clear project guidance. ",
            "course_code": "CSC 999", "reviewer_id": self.ids[2], "advisor_id": self.ids[2],
        })
        self.assertEqual(response.status_code, 201)
        review = response.get_json()["review"]
        self.assertEqual(review["course_code"], "CSC 510")
        self.assertEqual(review["comment"], "Clear project guidance.")
        portal.initialize_database()
        for client in (self.sender, self.advisor):
            row = client.get("/api/requests").get_json()["requests"][0]
            self.assertEqual(row["review_rating"], 5)
            self.assertEqual(row["review_comment"], "Clear project guidance.")
        profile = self.sender.get(f"/api/students/{self.ids[1]}").get_json()["student"]
        self.assertEqual(profile["review_summary"], {"average_rating": 5.0, "review_count": 1})
        self.assertEqual(profile["reviews"][0]["course_code"], "CSC 510")
        self.assertEqual(set(profile["reviews"][0]), {"request_id", "rating", "comment", "created_at", "course_code"})
        history = self.sender.get(f"/api/requests/{request_id}/messages").get_json()
        self.assertEqual(history["request"]["review_rating"], 5)

    def test_only_authenticated_requester_can_review(self):
        request_id = self.completed_request()
        url = f"/api/requests/{request_id}/review"
        self.assertEqual(portal.app.test_client().post(url, json={"rating": 4}).status_code, 401)
        self.assertEqual(self.advisor.post(url, json={"rating": 4}).status_code, 403)
        self.assertEqual(self.outsider.post(url, json={"rating": 4}).status_code, 404)
        self.assertEqual(self.sender.post("/api/requests/999999/review", json={"rating": 4}).status_code, 404)
        with self.sender.session_transaction() as session:
            session["auth_version"] = 99
        self.assertEqual(self.sender.post(url, json={"rating": 4}).status_code, 401)
        with portal.get_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM advice_reviews").fetchone()["count"], 0)

    def test_every_uncompleted_status_rejects_reviews(self):
        request_id = self.completed_request()
        for status in ("pending", "accepted", "declined", "cancelled", "expired", "closed"):
            with self.subTest(status=status):
                with portal.get_db() as db:
                    db.execute("UPDATE advice_requests SET status = %s WHERE id = %s", (status, request_id))
                response = self.sender.post(f"/api/requests/{request_id}/review", json={"rating": 4})
                self.assertEqual(response.status_code, 409)
        with portal.get_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM advice_reviews").fetchone()["count"], 0)

    def test_invalid_ratings_comments_and_bodies_do_not_create_reviews(self):
        request_id = self.completed_request()
        bodies = [None, [], "rating", {}, *({"rating": value} for value in (None, True, False, 0, 6, -1, 2.5, "5")),
                  {"rating": 5, "comment": None}, {"rating": 5, "comment": []},
                  {"rating": 5, "comment": "a" * 1001}]
        for body in bodies:
            with self.subTest(body=str(body)[:60]):
                self.assertEqual(self.sender.post(f"/api/requests/{request_id}/review", json=body).status_code, 400)
        self.assertEqual(self.sender.post(f"/api/requests/{request_id}/review", json={"rating": 1}).status_code, 201)

    def test_duplicates_are_rejected_and_original_review_is_preserved(self):
        request_id = self.completed_request()
        url = f"/api/requests/{request_id}/review"
        self.assertEqual(self.sender.post(url, json={"rating": 2, "comment": "Original"}).status_code, 201)
        self.assertEqual(self.sender.post(url, json={"rating": 5, "comment": "Replacement"}).status_code, 409)
        with self.assertRaises(UniqueViolation):
            with portal.get_db() as db:
                db.execute("INSERT INTO advice_reviews (request_id, rating) VALUES (%s, 5)", (request_id,))
        with portal.get_db() as db:
            row = db.execute("SELECT rating, comment FROM advice_reviews WHERE request_id = %s", (request_id,)).fetchone()
            self.assertEqual(dict(row), {"rating": 2, "comment": "Original"})

    def test_concurrent_submissions_create_exactly_one_review(self):
        request_id = self.completed_request()
        clients = [self.client_for(self.ids[0]), self.client_for(self.ids[0])]
        barrier = Barrier(2)

        def submit(client):
            barrier.wait(timeout=10)
            return client.post(f"/api/requests/{request_id}/review", json={"rating": 4}).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(submit, clients))
        self.assertEqual(sorted(statuses), [201, 409])
        with portal.get_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM advice_reviews").fetchone()["count"], 1)

    def test_profile_average_counts_all_courses_and_new_advisors_are_unrated(self):
        profile = self.outsider.get(f"/api/students/{self.ids[1]}").get_json()["student"]
        self.assertEqual(profile["review_summary"], {"average_rating": None, "review_count": 0})
        self.assertEqual(profile["reviews"], [])
        for course, rating in (("CSC 510", 5), ("CSC 540", 2)):
            request_id = self.completed_request(course)
            self.assertEqual(self.sender.post(f"/api/requests/{request_id}/review", json={"rating": rating}).status_code, 201)
        profile = self.outsider.get(f"/api/students/{self.ids[1]}").get_json()["student"]
        self.assertEqual(profile["review_summary"], {"average_rating": 3.5, "review_count": 2})
        self.assertEqual([review["course_code"] for review in profile["reviews"]], ["CSC 540", "CSC 510"])
        sender = self.sender.get(f"/api/students/{self.ids[0]}").get_json()["student"]
        self.assertEqual(sender["review_summary"]["review_count"], 0)

    def test_migration_preserves_existing_completed_advice_and_is_repeatable(self):
        request_id = self.completed_request()
        path = MIGRATIONS / "20261120000100_advisor_reviews.sql"
        with portal.get_db() as db:
            db.execute("DROP TABLE advice_reviews")
            db.execute(migration_sql(path).replace("public.", self.schema + "."), prepare=False)
            db.execute(migration_sql(path).replace("public.", self.schema + "."), prepare=False)
            self.assertEqual(db.execute("SELECT status FROM advice_requests WHERE id=%s", (request_id,)).fetchone()["status"], "completed")
        self.assertEqual(self.sender.post(f"/api/requests/{request_id}/review", json={"rating": 5, "comment": "x" * 1000}).status_code, 201)

    def test_summary_includes_reviews_beyond_the_visible_twenty(self):
        with portal.get_db() as db:
            for index in range(21):
                request_id = db.execute("""
                    INSERT INTO advice_requests
                    (sender_id, recipient_id, course_code, advice_topic, message, status)
                    VALUES (%s, %s, 'CSC 510', 'Projects', 'Previous advice', 'completed')
                    RETURNING id
                """, (self.ids[0], self.ids[1])).fetchone()["id"]
                db.execute("INSERT INTO advice_reviews (request_id, rating) VALUES (%s, %s)",
                           (request_id, 1 if index == 0 else 5))
        profile = self.sender.get(f"/api/students/{self.ids[1]}").get_json()["student"]
        self.assertEqual(profile["review_summary"]["review_count"], 21)
        self.assertAlmostEqual(profile["review_summary"]["average_rating"], 101 / 21)
        self.assertEqual(len(profile["reviews"]), 20)
        self.assertTrue(all(review["rating"] == 5 for review in profile["reviews"]))
