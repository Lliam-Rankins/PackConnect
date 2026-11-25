import os
from unittest.mock import patch

import httpx

import app as portal
import live_updates
from postgres_test_support import PostgresTestCase

ENVIRONMENT = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SECRET_KEY": "test-secret-key",
    "SUPABASE_PUBLISHABLE_KEY": "test-public-key",
    "FLASK_SECRET_KEY": "test-flask-key",
}


class RealtimeTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        environment = patch.dict(os.environ, ENVIRONMENT)
        environment.start()
        self.addCleanup(environment.stop)
        post = patch.object(live_updates.httpx, "post")
        self.post = post.start()
        self.addCleanup(post.stop)
        self.clients, self.ids = [], []
        for name in ("sender", "recipient"):
            client = portal.app.test_client()
            credentials = {"email": name + "@example.edu", "password": "a long test password"}
            response = client.post("/api/auth/register", json={
                **credentials, "name": name, "program": "Computer Science", "year": "First Year",
                "willing_to_advise": True, "completed_courses": ["CSC 510"],
            })
            self.ids.append(response.get_json()["student"]["id"])
            self.assertEqual(client.post("/api/auth/login", json=credentials).status_code, 200)
            self.clients.append(client)
        self.sender, self.recipient = self.clients

    def topics(self, *user_ids):
        return {live_updates.topic(user_id, "test-flask-key") for user_id in user_ids}

    def signaled(self):
        messages = [message for call in self.post.call_args_list for message in call.kwargs["json"]["messages"]]
        self.assertTrue(all(message["payload"] == {} for message in messages))
        self.post.reset_mock()
        return {message["topic"] for message in messages}

    def create_request(self):
        return self.sender.post("/api/requests", json={
            "recipient_id": self.ids[1], "course_code": "CSC 510",
            "advice_topic": "Projects", "message": "Any tips?",
        })

    def test_subscription_requires_sign_in_and_hides_secrets(self):
        self.assertEqual(portal.app.test_client().get("/api/realtime").status_code, 401)
        first = self.sender.get("/api/realtime").get_json()
        second = self.recipient.get("/api/realtime").get_json()
        self.assertEqual(first, {
            "enabled": True, "url": ENVIRONMENT["SUPABASE_URL"], "key": "test-public-key",
            "topic": live_updates.topic(self.ids[0], "test-flask-key"),
        })
        self.assertNotEqual(first["topic"], second["topic"])

    def test_disabled_without_complete_configuration(self):
        for name in ENVIRONMENT:
            with self.subTest(name=name), patch.dict(os.environ, {name: "", "SUPABASE_ANON_KEY": ""}):
                self.assertEqual(self.sender.get("/api/realtime").get_json(), {"enabled": False})
                live_updates.publish({self.ids[0]})
        self.post.assert_not_called()

    def test_request_chat_and_completion_signal_the_affected_students(self):
        request_id = self.create_request().get_json()["request"]["id"]
        self.assertEqual(self.signaled(), self.topics(self.ids[1]))
        self.recipient.patch(f"/api/requests/{request_id}", json={"status": "accepted"})
        self.assertEqual(self.signaled(), self.topics(self.ids[0]))
        self.sender.post(f"/api/requests/{request_id}/messages", json={"body": "Hello"})
        self.assertEqual(self.signaled(), self.topics(*self.ids))
        self.recipient.patch(f"/api/requests/{request_id}", json={"status": "completed"})
        self.assertEqual(self.signaled(), self.topics(*self.ids))

    def test_signal_is_sent_after_commit(self):
        counts = []

        def count_committed(*args, **kwargs):
            with portal.get_db() as db:
                counts.append(db.execute("SELECT COUNT(*) FROM advice_requests").fetchone()["count"])
            return self.post.return_value

        self.post.side_effect = count_committed
        self.assertEqual(self.create_request().status_code, 201)
        self.assertEqual(counts, [1])

    def test_rollback_sends_nothing(self):
        with self.assertRaises(RuntimeError):
            with portal.get_db() as db:
                live_updates.signal(db, self.ids[0])
                raise RuntimeError("roll back")
        self.post.assert_not_called()

    def test_publish_failure_does_not_fail_the_request(self):
        self.post.side_effect = httpx.ConnectError("offline")
        with self.assertLogs("live_updates", "WARNING"):
            self.assertEqual(self.create_request().status_code, 201)
