"""M0 instrument: does ranked matching beat today's course-only search and keyword-only ranking?

    TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/packconnect_test?sslmode=disable \\
        python eval/run_m0.py [--data eval/data/seed2.json] [--tune eval/data/seed1.json] [--out eval/results.md]

Loads a generated dataset into a throwaway schema (always dropped), embeds profiles with the real
model, then ranks every request with the production signals + scoring code for each arm.
"""

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TOP_K = 3
ALPHAS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
ARMS = ("course_only", "keyword_only", "semantic_only", "hybrid")
ARM_LABELS = {
    "course_only": "Course only (sorted by name, today's search)",
    "keyword_only": "Keyword only (alpha = 1)",
    "semantic_only": "Semantic only (alpha = 0, informational)",
    "hybrid": "Hybrid (default weights)",
}
INHERITED_MIN_TOP3 = 0.80
INHERITED_MIN_GAIN = 0.20
NEW_MIN_GAIN = 0.15
DEFAULT_DATA = ROOT / "eval" / "data" / "seed2.json"
DEFAULT_OUT = ROOT / "eval" / "results.md"


# ---- pure metrics, claims and report -------------------------------------------------------

def evaluate_arm(rankings, requests, k=TOP_K):
    """rankings: {request_id: advisor ids best first}. Returns {n, top3, mrr}."""
    hits, reciprocal = 0, 0.0
    for request in requests:
        suitable = set(request["suitable_advisor_ids"])
        order = rankings.get(request["id"], [])
        first = next((i for i, advisor in enumerate(order, 1) if advisor in suitable), None)
        hits += first is not None and first <= k
        reciprocal += 1 / first if first else 0.0
    n = len(requests)
    return {"n": n, "top3": hits / n if n else 0.0, "mrr": reciprocal / n if n else 0.0}


def evaluate_claims(arms):
    """arms: {arm: {top3, ...}}. Returns [{name, passed, detail}]."""
    hybrid, course, keyword = (arms[a]["top3"] for a in ("hybrid", "course_only", "keyword_only"))
    return [
        {"name": "Inherited: hybrid >= 80% top-3 and >= 20 points above course-only",
         "passed": hybrid >= INHERITED_MIN_TOP3 and hybrid - course >= INHERITED_MIN_GAIN - 1e-9,
         "detail": f"hybrid {hybrid:.1%}, course-only {course:.1%}, gain {100 * (hybrid - course):+.1f} points"},
        {"name": "New: hybrid >= 15 points above keyword-only",
         "passed": hybrid - keyword >= NEW_MIN_GAIN - 1e-9,
         "detail": f"hybrid {hybrid:.1%}, keyword-only {keyword:.1%}, gain {100 * (hybrid - keyword):+.1f} points"},
    ]


def render_report(report):
    """Deterministic markdown (no dates or timings) so reruns diff cleanly."""
    arms, meta = report["arms"], report["metadata"]
    lines = ["# M0 results", "",
             f"Reporting data: seed {meta.get('seed')}, {arms['hybrid']['n']} requests, "
             f"{len(report['advisors'])} advisors, model `{report['model']}`, available advisors only.", "",
             "| Arm | Top-3 suitability | MRR |", "|---|---|---|"]
    for arm in ARMS:
        lines.append(f"| {ARM_LABELS[arm]} | {arms[arm]['top3']:.1%} | {arms[arm]['mrr']:.3f} |")
    lines += ["", "## Claims", ""]
    for claim in report["claims"]:
        lines.append(f"- **{'PASS' if claim['passed'] else 'FAIL'}** {claim['name']} ({claim['detail']})")
    if report.get("tune"):
        tune = report["tune"]
        lines += ["", f"## Alpha sweep on tuning data (seed {tune['seed']}, information only)", "",
                  "| alpha | Top-3 suitability | MRR |", "|---|---|---|"]
        lines += [f"| {alpha:.1f} | {row['top3']:.1%} | {row['mrr']:.3f} |" for alpha, row in tune["alphas"]]
    return "\n".join(lines) + "\n"


# ---- database ------------------------------------------------------------------------------

def load_dataset(path):
    return json.loads(Path(path).read_text())


def _insert_student(db, name, program="Eval", year="1", registered=False, advising=False, **fields):
    columns = {"name": name, "program": program, "year": str(year), "willing_to_advise": advising, **fields}
    student_id = db.execute(
        f"INSERT INTO students ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
        list(columns.values())).fetchone()["id"]
    if registered:
        db.execute("INSERT INTO accounts (student_id, email, password_hash) VALUES (%s, %s, 'unused')",
                   (student_id, f"student{student_id}@eval.test"))
    return student_id


def _insert_advisor(db, advisor, dummies, asker):
    student_id = _insert_student(
        db, advisor["name"], advisor["program"], advisor["year"], registered=True, advising=True,
        bio=advisor["bio"], interests=advisor["interests"], skills=advisor["skills"],
        advice_topics=advisor["advice_topics"], max_open_requests=advisor["max_open_requests"])
    for course in advisor["completed_courses"]:
        db.execute("INSERT INTO completed_courses (student_id, course_code) VALUES (%s, %s)", (student_id, course))
    for sender in dummies[:advisor["open_request_count"]]:
        db.execute("""INSERT INTO advice_requests (sender_id, recipient_id, course_code, advice_topic, message)
                      VALUES (%s, %s, %s, 'Eval', 'Eval')""", (sender, student_id, advisor["completed_courses"][0]))
    for review in advisor["reviews"]:
        request_id = db.execute("""INSERT INTO advice_requests
            (sender_id, recipient_id, course_code, advice_topic, message, status)
            VALUES (%s, %s, %s, 'Eval', 'Eval', 'completed') RETURNING id""",
            (dummies[0], student_id, review["course"])).fetchone()["id"]
        db.execute("INSERT INTO advice_reviews (request_id, rating) VALUES (%s, %s)", (request_id, review["rating"]))
    for course, count in advisor["helpful_answers"].items():
        for _ in range(count):
            question = db.execute("""INSERT INTO course_questions (author_id, course_code, title, body)
                VALUES (%s, %s, 'Eval', 'Eval') RETURNING id""", (asker, course)).fetchone()["id"]
            answer = db.execute("INSERT INTO course_answers (question_id, author_id, body) VALUES (%s, %s, 'Eval') RETURNING id",
                                (question, student_id)).fetchone()["id"]
            db.execute("INSERT INTO course_helpful_answers (question_id, answer_id) VALUES (%s, %s)", (question, answer))
    return student_id


def build_database(db, dataset, embedder):
    """Insert the dataset through SQL and embed profiles; returns (viewer_id, {student_id: advisor_id})."""
    from matching import profile_vectors

    advisors = dataset["advisors"]
    pool = max([a["open_request_count"] for a in advisors] + [1])
    dummies = [_insert_student(db, f"Dummy sender {i}") for i in range(pool)]
    asker = _insert_student(db, "Dummy asker")
    viewer = _insert_student(db, "Viewer", registered=True)  # registered, not an advisor
    ids = {}
    for advisor in advisors:
        ids[_insert_advisor(db, advisor, dummies, asker)] = advisor["id"]
    for student_id in ids:
        if not profile_vectors.refresh(db, embedder, student_id):
            raise RuntimeError(f"Embedding failed for student {student_id}")
    return viewer, ids


@contextmanager
def throwaway_database(database_url):
    """Point the app at a fresh migrated schema, always dropping it afterwards."""
    import app as portal
    from common.temp_schema import create_schema, drop_schema

    schema = create_schema(database_url)
    original = portal.app.config.get("SUPABASE_DB_URL")
    portal.app.config.update(SUPABASE_DB_URL=database_url, TEST_DB_SCHEMA=schema)
    try:
        yield portal.get_db
    finally:
        portal.app.config.pop("TEST_DB_SCHEMA", None)
        portal.app.config["SUPABASE_DB_URL"] = original
        drop_schema(database_url, schema)


# ---- ranking arms --------------------------------------------------------------------------

def _ids(ranked, ids):
    return [ids[candidate.student_id] for candidate, _ in ranked]


def rank_requests(db, dataset, embedder, viewer, ids, alphas=()):
    """Return ({arm: {request_id: advisor ids}}, {alpha: {request_id: advisor ids}})."""
    from matching.scoring import DEFAULT_WEIGHTS, rank
    from matching.signals import fetch_candidates

    available = {"available": True}
    arms = {arm: {} for arm in ARMS}
    sweep = {alpha: {} for alpha in alphas}
    for request in dataset["requests"]:
        course, need, key = request["course"], request["need"], request["id"]
        vector = embedder.embed_queries([need])[0]
        candidates, _ = fetch_candidates(db, viewer=viewer, course=course, need=need,
                                         query_vector=vector, filters=available)
        keyword_candidates, _ = fetch_candidates(db, viewer=viewer, course=course, need=need,
                                                 query_vector=None, filters=available)
        by_name = sorted(candidates, key=lambda c: (c.profile["name"], c.student_id))
        arms["course_only"][key] = [ids[c.student_id] for c in by_name]
        arms["keyword_only"][key] = _ids(rank(keyword_candidates, DEFAULT_WEIGHTS.with_alpha(1.0)), ids)
        arms["semantic_only"][key] = _ids(rank(candidates, DEFAULT_WEIGHTS.with_alpha(0.0)), ids)
        arms["hybrid"][key] = _ids(rank(candidates, DEFAULT_WEIGHTS), ids)
        for alpha in alphas:
            sweep[alpha][key] = _ids(rank(candidates, DEFAULT_WEIGHTS.with_alpha(alpha)), ids)
    return arms, sweep


def evaluate_dataset(database_url, dataset, embedder, alphas=()):
    """Load the dataset into a throwaway schema and score every arm (and alpha)."""
    with throwaway_database(database_url) as get_db:
        with get_db() as db:
            viewer, ids = build_database(db, dataset, embedder)
        with get_db() as db:
            rankings, sweep = rank_requests(db, dataset, embedder, viewer, ids, alphas)
    requests = dataset["requests"]
    return ({arm: evaluate_arm(rankings[arm], requests) for arm in ARMS},
            [(alpha, evaluate_arm(sweep[alpha], requests)) for alpha in alphas])


def run(database_url, data_path, tune_path=None, embedder=None):
    from matching.embedder import FastEmbedEmbedder

    embedder = embedder or FastEmbedEmbedder()
    dataset = load_dataset(data_path)
    arms, _ = evaluate_dataset(database_url, dataset, embedder)
    report = {"metadata": dataset["metadata"], "advisors": dataset["advisors"], "model": embedder.model_name,
              "arms": arms, "claims": evaluate_claims(arms)}
    if tune_path:
        tuning = load_dataset(tune_path)
        _, alphas = evaluate_dataset(database_url, tuning, embedder, ALPHAS)
        report["tune"] = {"seed": tuning["metadata"]["seed"], "alphas": alphas}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="reporting dataset")
    parser.add_argument("--tune", help="tuning dataset: prints top-3 per alpha (information only)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="markdown results file")
    args = parser.parse_args(argv)

    from common.temp_schema import require_local_database
    database_url = os.getenv("TEST_DATABASE_URL")
    require_local_database(database_url)

    started = time.monotonic()
    report = run(database_url, args.data, args.tune)
    markdown = render_report(report)
    print(markdown)
    Path(args.out).write_text(markdown)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(markdown + "\n")
    print(f"Finished in {time.monotonic() - started:.1f}s; wrote {args.out}")


if __name__ == "__main__":
    main()
