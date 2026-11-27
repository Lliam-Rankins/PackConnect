"""Fast tests for the pure parts of eval/run_m0.py (no model, no database).

Run from the repo root: python -m unittest discover -s eval -p "test_*.py"
"""

import unittest

import run_m0

REQUESTS = [
    {"id": "r1", "suitable_advisor_ids": ["a", "b"]},
    {"id": "r2", "suitable_advisor_ids": ["c"]},
    {"id": "r3", "suitable_advisor_ids": ["d"]},
    {"id": "r4", "suitable_advisor_ids": ["e"]},
]


class MetricTests(unittest.TestCase):
    def test_top3_and_mrr(self):
        rankings = {"r1": ["x", "b", "y"], "r2": ["x", "y", "z", "c"], "r3": ["d"], "r4": []}
        result = run_m0.evaluate_arm(rankings, REQUESTS)
        self.assertEqual(result["n"], 4)
        self.assertAlmostEqual(result["top3"], 2 / 4)  # r1 (rank 2) and r3 (rank 1)
        self.assertAlmostEqual(result["mrr"], (1 / 2 + 1 / 4 + 1 + 0) / 4)

    def test_missing_rankings_and_no_requests(self):
        self.assertEqual(run_m0.evaluate_arm({}, REQUESTS)["top3"], 0.0)
        self.assertEqual(run_m0.evaluate_arm({}, [])["top3"], 0.0)


def arms(course, keyword, hybrid):
    return {"course_only": {"top3": course, "mrr": 0}, "keyword_only": {"top3": keyword, "mrr": 0},
            "semantic_only": {"top3": 0.5, "mrr": 0}, "hybrid": {"top3": hybrid, "mrr": 0}}


class ClaimTests(unittest.TestCase):
    def passed(self, **values):
        return [claim["passed"] for claim in run_m0.evaluate_claims(arms(**values))]

    def test_both_claims_pass(self):
        self.assertEqual(self.passed(course=0.4, keyword=0.6, hybrid=0.85), [True, True])

    def test_inherited_needs_floor_and_gain(self):
        self.assertEqual(self.passed(course=0.4, keyword=0.5, hybrid=0.79)[0], False)
        self.assertEqual(self.passed(course=0.7, keyword=0.5, hybrid=0.85)[0], False)

    def test_new_claim_needs_gain_over_keyword(self):
        self.assertEqual(self.passed(course=0.3, keyword=0.75, hybrid=0.85)[1], False)

    def test_boundaries_count_as_passing(self):
        self.assertEqual(self.passed(course=0.6, keyword=0.65, hybrid=0.8), [True, True])


class ReportTests(unittest.TestCase):
    def report(self, **extra):
        data = arms(0.3, 0.5, 0.9)
        data = {name: {"n": 10, **values} for name, values in data.items()}
        return {"metadata": {"seed": 2}, "advisors": [1, 2], "model": "m", "arms": data,
                "claims": run_m0.evaluate_claims(data), **extra}

    def test_renders_arms_claims_and_is_deterministic(self):
        text = run_m0.render_report(self.report())
        self.assertEqual(text, run_m0.render_report(self.report()))
        self.assertIn("| Hybrid (default weights) | 90.0% |", text)
        self.assertIn("**PASS** Inherited", text)
        self.assertIn("10 requests", text)
        self.assertNotIn("Alpha sweep", text)

    def test_tuning_table(self):
        tune = {"seed": 1, "alphas": [(0.0, {"top3": 0.5, "mrr": 0.4}), (1.0, {"top3": 0.25, "mrr": 0.2})]}
        text = run_m0.render_report(self.report(tune=tune))
        self.assertIn("| 0.0 | 50.0% | 0.400 |", text)
        self.assertIn("| 1.0 | 25.0% | 0.200 |", text)


if __name__ == "__main__":
    unittest.main()
