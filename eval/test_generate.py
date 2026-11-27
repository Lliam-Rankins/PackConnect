"""Tests for eval/generate.py and eval/concepts.json.

Run from the repo root with:
    cd eval && ../.venv/bin/python -m unittest test_generate -v
"""

import json
import unittest

import generate as gen

SEED_A = 1
SEED_B = 2


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = gen.generate(SEED_A)
        cls.spec = gen.load_concepts()
        cls.concepts = {c["id"]: c for c in cls.spec["concepts"]}

    def test_same_seed_gives_identical_json(self):
        first = json.dumps(gen.generate(SEED_A), sort_keys=True)
        second = json.dumps(gen.generate(SEED_A), sort_keys=True)
        self.assertEqual(first, second)

    def test_different_seeds_differ(self):
        other = gen.generate(SEED_B)
        self.assertNotEqual(self.data["advisors"], other["advisors"])
        self.assertNotEqual(self.data["requests"], other["requests"])

    def test_schema_and_counts(self):
        self.assertEqual(set(self.data), {"metadata", "courses", "concepts", "advisors", "requests"})
        self.assertEqual(len(self.data["courses"]), gen.N_COURSES)
        for code in self.data["courses"]:
            self.assertRegex(code, r"^[A-Z]{3} \d{3}$")
        self.assertEqual(len(self.data["advisors"]), gen.N_ADVISORS)
        self.assertEqual(len(self.data["requests"]), gen.N_REQUESTS)
        self.assertEqual(self.data["metadata"]["seed"], SEED_A)
        self.assertEqual(self.data["metadata"]["generator_version"], gen.GENERATOR_VERSION)
        self.assertEqual(self.data["metadata"]["counts"]["advisors"], gen.N_ADVISORS)

        advisor_keys = {
            "id", "name", "program", "year", "completed_courses", "advice_topics", "skills",
            "interests", "bio", "max_open_requests", "open_request_count", "reviews",
            "helpful_answers", "hidden",
        }
        request_keys = {"id", "course", "need", "hidden", "candidate_count", "suitable_advisor_ids"}
        for advisor in self.data["advisors"]:
            self.assertEqual(set(advisor), advisor_keys)
            self.assertEqual(set(advisor["hidden"]), {"concepts", "quality"})
            self.assertTrue(1 <= len(advisor["completed_courses"]) <= 3)
            self.assertTrue(1 <= len(advisor["hidden"]["concepts"]) <= 3)
            self.assertTrue(0.0 <= advisor["hidden"]["quality"] <= 1.0)
            self.assertTrue(len(advisor["reviews"]) <= 8)
            for review in advisor["reviews"]:
                self.assertTrue(1 <= review["rating"] <= 5)
        for request in self.data["requests"]:
            self.assertEqual(set(request), request_keys)

    def test_every_request_has_suitable_advisor_matching_hidden_rule(self):
        for request in self.data["requests"]:
            expected = gen.suitable_advisor_ids(
                self.data["advisors"], request["course"], request["hidden"]["target_concept"]
            )
            self.assertTrue(expected, request["id"])
            self.assertEqual(request["suitable_advisor_ids"], expected, request["id"])
            self.assertGreaterEqual(request["candidate_count"], gen.MIN_CANDIDATES)

    def test_visible_text_mentions_only_held_concepts(self):
        for advisor in self.data["advisors"]:
            visible = " ".join(
                advisor[k] for k in ("advice_topics", "skills", "interests", "bio")
            )
            held = set(advisor["hidden"]["concepts"])
            for cid, concept in self.concepts.items():
                if cid in held:
                    continue
                for phrase in concept["profile_phrases"]:
                    self.assertNotIn(phrase, visible, f"{advisor['id']} leaks {cid}")

    def test_request_text_is_never_a_profile_phrase(self):
        profile = {p for c in self.spec["concepts"] for p in c["profile_phrases"]}
        for request in self.data["requests"]:
            self.assertNotIn(request["need"], profile, request["id"])
            for phrase in profile:
                self.assertNotIn(phrase, request["need"], request["id"])

    def test_concept_request_phrases_mostly_share_no_content_word(self):
        for concept in self.spec["concepts"]:
            cid = concept["id"]
            profile = concept["profile_phrases"]
            requests = concept["request_phrases"]
            self.assertTrue(5 <= len(profile) <= 6, cid)
            self.assertTrue(4 <= len(requests) <= 5, cid)
            self.assertFalse(set(requests) & set(profile), f"{cid}: identical strings")
            clean = 0
            profile_words = set()
            for p in profile:
                profile_words |= gen.content_words(p)
            for r in requests:
                if not (gen.content_words(r) & profile_words):
                    clean += 1
            self.assertGreaterEqual(clean * 2, len(requests), f"{cid}: only {clean} clean")

    def test_concepts_file_schema(self):
        ids = [c["id"] for c in self.spec["concepts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 25)
        for concept in self.spec["concepts"]:
            self.assertEqual(set(concept), {"id", "profile_phrases", "request_phrases"})
            self.assertRegex(concept["id"], r"^[a-z_]+$")
        self.assertGreaterEqual(len(self.spec["filler_bio_sentences"]), 30)
        self.assertGreaterEqual(len(self.spec["interest_phrases"]), 20)


if __name__ == "__main__":
    unittest.main()
