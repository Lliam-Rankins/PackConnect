import math
import os
import unittest

from fake_embedder import FakeEmbedder
from matching.embedder import FastEmbedEmbedder, vector_literal
from matching.scoring import (
    DEFAULT_WEIGHTS,
    Weights,
    Candidate,
    capacity_score,
    qa_help_score,
    rank,
    rating_score,
    score,
    semantic_score,
    topic_fit,
)


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


class SignalTests(unittest.TestCase):
    def test_semantic_weighted_average_over_present_fields(self):
        sims = {"advice_topics": 1.0, "bio": 0.0}
        # weights 0.4 and 0.15 -> 0.4 / 0.55
        self.assertAlmostEqual(semantic_score(sims), 0.4 / 0.55)

    def test_semantic_none_without_fields_and_clamps_negatives(self):
        self.assertIsNone(semantic_score({}))
        self.assertIsNone(semantic_score({"unknown_field": 0.9}))
        self.assertEqual(semantic_score({"skills": -0.5}), 0.0)
        self.assertEqual(semantic_score({"skills": 1.5}), 1.0)

    def test_topic_fit_blend_and_extremes(self):
        self.assertAlmostEqual(topic_fit(1.0, 0.5, 0.4), 0.4 + 0.3)
        self.assertEqual(topic_fit(0.7, 0.2, 1.0), 0.7)
        self.assertEqual(topic_fit(0.7, 0.2, 0.0), 0.2)

    def test_topic_fit_falls_back_to_keyword_without_semantic(self):
        self.assertEqual(topic_fit(0.8, None, 0.4), 0.8)

    def test_rating_smoothing_and_scale(self):
        self.assertAlmostEqual(rating_score(None, 0), (3.5 - 1) / 4)
        # one 5-star review is pulled towards the prior
        self.assertAlmostEqual(rating_score(5.0, 1), ((5 + 3 * 3.5) / 4 - 1) / 4)
        self.assertGreater(rating_score(5.0, 50), rating_score(5.0, 1))
        self.assertAlmostEqual(rating_score(1.0, 10_000), 0.0, places=2)

    def test_qa_help_curve(self):
        self.assertEqual(qa_help_score(0), 0.0)
        self.assertAlmostEqual(qa_help_score(5), 1.0)
        self.assertEqual(qa_help_score(50), 1.0)
        self.assertAlmostEqual(qa_help_score(2), math.log(3) / math.log(6))

    def test_capacity(self):
        self.assertEqual(capacity_score(None, 99), 1.0)
        self.assertEqual(capacity_score(4, 4), 0.0)
        self.assertEqual(capacity_score(4, 9), 0.0)
        self.assertEqual(capacity_score(4, 1), 0.75)
        self.assertEqual(capacity_score(0, 0), 0.0)


class ScoreAndRankTests(unittest.TestCase):
    def test_score_combines_default_weights(self):
        c = Candidate(
            student_id=1,
            keyword_rank=1.0,
            field_similarity={"advice_topics": 1.0},
            review_count=0,
            helpful_answers=5,
        )
        m = score(c)
        self.assertAlmostEqual(m.breakdown["topic_fit"], 0.4 + 0.6)
        w = DEFAULT_WEIGHTS
        quality = w.quality_floor + w.rating * 0.625 + w.qa_help * 1.0 + w.capacity * 1.0
        self.assertAlmostEqual(m.breakdown["quality"], quality)
        self.assertAlmostEqual(m.score, 1.0 * quality)

    def test_missing_vectors_uses_keyword_only(self):
        m = score(Candidate(student_id=1, keyword_rank=0.5))
        self.assertIsNone(m.breakdown["semantic"])
        self.assertEqual(m.breakdown["topic_fit"], 0.5)

    def test_alpha_extremes_change_ranking(self):
        keyword_heavy = Candidate(student_id=1, keyword_rank=1.0, field_similarity={"bio": 0.1})
        semantic_heavy = Candidate(student_id=2, keyword_rank=0.0, field_similarity={"bio": 0.9})
        kw_only = DEFAULT_WEIGHTS.with_alpha(1.0)
        sem_only = DEFAULT_WEIGHTS.with_alpha(0.0)
        self.assertEqual(rank([semantic_heavy, keyword_heavy], kw_only)[0][0].student_id, 1)
        self.assertEqual(rank([keyword_heavy, semantic_heavy], sem_only)[0][0].student_id, 2)

    def test_ties_break_by_student_id(self):
        cands = [Candidate(student_id=i) for i in (7, 3, 5)]
        self.assertEqual([c.student_id for c, _ in rank(cands)], [3, 5, 7])

    def test_rank_sorts_by_score_desc(self):
        low = Candidate(student_id=1)
        high = Candidate(student_id=2, keyword_rank=1.0, matched_terms=["x"])
        self.assertEqual([c.student_id for c, _ in rank([low, high])], [2, 1])

    def test_reasons_content(self):
        c = Candidate(
            student_id=1,
            keyword_rank=0.9,
            matched_terms=["testing"],
            field_similarity={"skills": 0.8, "bio": 0.2},
            review_count=4,
            average_rating=4.5,
            helpful_answers=2,
            max_open_requests=4,
            open_request_count=1,
        )
        reasons = score(c).reasons
        by_type = {r["type"]: r for r in reasons}
        self.assertEqual(by_type["keyword"], {"type": "keyword", "terms": ["testing"]})
        self.assertEqual(by_type["semantic"], {"type": "semantic", "field": "skills"})
        self.assertEqual(by_type["rating"], {"type": "rating", "average": 4.5, "count": 4})
        self.assertEqual(by_type["qa_help"], {"type": "qa_help", "count": 2})
        self.assertEqual(by_type["capacity"], {"type": "capacity", "free": 3})

    def test_reasons_omitted_when_signal_absent(self):
        c = Candidate(
            student_id=1,
            field_similarity={"skills": 0.3},
            max_open_requests=2,
            open_request_count=2,
        )
        self.assertEqual(score(c).reasons, [])

    def test_unlimited_capacity_reason_has_null_free(self):
        reasons = score(Candidate(student_id=1)).reasons
        self.assertEqual(reasons, [{"type": "capacity", "free": None}])

    def test_reasons_ordered_by_contribution(self):
        c = Candidate(
            student_id=1,
            keyword_rank=1.0,
            matched_terms=["a"],
            review_count=1,
            average_rating=3.0,
            helpful_answers=1,
        )
        types = [r["type"] for r in score(c).reasons]
        # keyword share ~0.4*q, rating 0.25*0.5=0.125, capacity 0.05, qa 0.1*0.39
        self.assertEqual(types, ["keyword", "rating", "capacity", "qa_help"])

    def test_zero_topic_scores_zero_even_with_perfect_rating(self):
        c = Candidate(student_id=1, review_count=50, average_rating=5.0, helpful_answers=20)
        m = score(c)
        self.assertEqual(m.score, 0.0)
        self.assertGreater(m.breakdown["quality"], 0.6)
        self.assertEqual(
            [r["type"] for r in m.reasons], ["rating", "qa_help", "capacity"]
        )  # tie at 0 keeps stable order

    def test_quality_reorders_equal_topic_candidates(self):
        base = dict(keyword_rank=0.5, matched_terms=["x"])
        plain = Candidate(student_id=1, max_open_requests=4, open_request_count=4, **base)
        good = Candidate(student_id=2, review_count=20, average_rating=5.0,
                         helpful_answers=5, **base)
        ranked = rank([plain, good])
        self.assertEqual([c.student_id for c, _ in ranked], [2, 1])
        w = DEFAULT_WEIGHTS
        self.assertAlmostEqual(ranked[1][1].score, 0.5 * (w.quality_floor + w.rating * 0.625))

    def test_breakdown_includes_quality(self):
        m = score(Candidate(student_id=1, keyword_rank=0.5))
        self.assertEqual(
            set(m.breakdown),
            {"topic_fit", "keyword", "semantic", "rating", "qa_help", "capacity", "quality"},
        )


class WeightsTests(unittest.TestCase):
    def test_defaults_sum_to_one(self):
        w = Weights()
        self.assertAlmostEqual(w.quality_floor + w.rating + w.qa_help + w.capacity, 1.0)

    def test_rejects_bad_sum_or_negative(self):
        with self.assertRaises(ValueError):
            Weights(quality_floor=0.7)
        with self.assertRaises(ValueError):
            Weights(quality_floor=1.1, rating=-0.1, qa_help=0.1, capacity=-0.1)
        with self.assertRaises(ValueError):
            DEFAULT_WEIGHTS.with_quality(0.5, 0.25, 0.1, 0.05)

    def test_with_quality_replaces_and_validates(self):
        w = DEFAULT_WEIGHTS.with_quality(1.0, 0.0, 0.0, 0.0)
        self.assertEqual(w.quality_floor, 1.0)
        self.assertEqual(w.alpha, DEFAULT_WEIGHTS.alpha)
        m = score(Candidate(student_id=1, keyword_rank=0.5), w)
        self.assertAlmostEqual(m.score, 0.5)


class EmbedderTests(unittest.TestCase):
    def test_vector_literal_format(self):
        vec = [0.5] * 384
        lit = vector_literal(vec)
        self.assertTrue(lit.startswith("[0.5,0.5") and lit.endswith("0.5]"))
        self.assertEqual(len(lit.strip("[]").split(",")), 384)

    def test_vector_literal_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            vector_literal([0.1] * 10)
        with self.assertRaises(ValueError):
            vector_literal([float("nan")] + [0.0] * 383)
        with self.assertRaises(ValueError):
            vector_literal([float("inf")] + [0.0] * 383)

    def test_fake_embedder_deterministic_and_normalized(self):
        e = FakeEmbedder()
        a = e.embed_passages(["Unit testing with pytest"])[0]
        b = FakeEmbedder().embed_queries(["Unit testing with pytest"])[0]
        self.assertEqual(a, b)
        self.assertEqual(len(a), 384)
        self.assertAlmostEqual(cosine(a, a), 1.0)
        self.assertEqual(e.passage_calls, 1)

    def test_fake_embedder_similarity_and_stemming(self):
        e = FakeEmbedder()
        base, same, other = e.embed_passages(["testing suites", "tested suite", "cooking pasta"])
        self.assertGreater(cosine(base, same), 0.2)
        self.assertGreater(cosine(base, same), cosine(base, other))

    def test_fake_embedder_aliases_simulate_synonyms(self):
        plain = FakeEmbedder()
        aliased = FakeEmbedder(aliases={"pytest": "testing"})
        a, b = plain.embed_passages(["pytest", "testing"])
        self.assertLess(cosine(a, b), 0.9)
        a, b = aliased.embed_passages(["pytest", "testing"])
        self.assertAlmostEqual(cosine(a, b), 1.0)

    def test_fake_embedder_fail_mode(self):
        e = FakeEmbedder(fail=True)
        with self.assertRaises(RuntimeError):
            e.embed_passages(["x"])
        with self.assertRaises(RuntimeError):
            e.embed_queries(["x"])

    @unittest.skipUnless(os.environ.get("RUN_REAL_EMBEDDER") == "1", "set RUN_REAL_EMBEDDER=1")
    def test_real_fastembed_model(self):
        e = FastEmbedEmbedder()
        q = e.embed_queries(["unit testing with pytest"])[0]
        close, far = e.embed_passages(["writing test suites", "cooking pasta"])
        self.assertEqual(len(q), 384)
        self.assertGreater(cosine(q, close), cosine(q, far))


if __name__ == "__main__":
    unittest.main()
