"""Seeded synthetic data for the M0 eval of ranked advisor matching.

Standard library only. Same seed and same concepts.json give identical output.

Suitability is decided by HIDDEN labels (advisor["hidden"]["concepts"] and
advisor["hidden"]["quality"]), never by the visible text. Visible text is
built from the advisor's concepts' profile phrases, so some concepts only show
up in the bio. Requests use separate request phrases, so a student's need
rarely repeats an advisor's profile wording.

Usage:
    python eval/generate.py --seed 1 --out eval/data/seed1.json
"""

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

GENERATOR_VERSION = "1.0.0"

N_ADVISORS = 180
N_REQUESTS = 120
N_COURSES = 6
MIN_CANDIDATES = 8
QUALITY_THRESHOLD = 0.5
BIO_ONLY_PROB = 0.2
SECONDARY_PHRASE_PROB = 0.3
MAX_REQUEST_ATTEMPTS = 50000

HERE = Path(__file__).resolve().parent
CONCEPTS_PATH = HERE / "concepts.json"

COURSE_POOL = [
    "CSC 116", "CSC 216", "CSC 226", "CSC 316", "CSC 340", "CSC 401",
    "CSC 415", "CSC 491", "CSC 510", "CSC 517", "MAT 305", "ECE 306",
]
PROGRAMS = [
    "Computer Science",
    "Software Engineering",
    "Computer Engineering",
    "Electrical Engineering",
    "Data Science",
]

_STOPWORDS = frozenset(
    """a an the and or but of to in on at for with from by into about over
    my me i we our us you your it its is are was be do does did how what why
    when where which so that this these there than then just up down out as if
    not no any some more most very own all them they their here whether can t s
    doesn don won isn""".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def stem(word):
    """Strip simple English suffixes so plurals and -ing/-ed forms match."""
    if len(word) > 6 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 5 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 4 and word.endswith("es"):
        base = word[:-2]
        if base.endswith(("ss", "sh", "ch", "x")):
            return base
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def content_words(text):
    """Set of stemmed content words in text (stopwords and 1-char tokens dropped)."""
    tokens = _TOKEN_RE.findall(text.lower())
    return {stem(t) for t in tokens if len(t) > 1 and t not in _STOPWORDS}


def load_concepts(path=CONCEPTS_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _poisson(rng, lam):
    """Knuth's method; fine for the small means used here."""
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _has_capacity(advisor):
    maximum = advisor["max_open_requests"]
    return maximum is None or advisor["open_request_count"] < maximum


def suitable_advisor_ids(advisors, course, concept_id):
    """The hidden-label rule. Used by generate() and by the tests."""
    return sorted(
        a["id"]
        for a in advisors
        if course in a["completed_courses"]
        and concept_id in a["hidden"]["concepts"]
        and a["hidden"]["quality"] >= QUALITY_THRESHOLD
        and _has_capacity(a)
    )


def candidate_count(advisors, course):
    """Advisors who completed the course: the pool a course-only ranker sees."""
    return sum(1 for a in advisors if course in a["completed_courses"])


def _make_advisor(rng, index, courses, concepts_by_id, concept_ids, interests, fillers):
    completed = sorted(rng.sample(courses, rng.randint(1, 3)))
    held = sorted(rng.sample(concept_ids, rng.randint(1, 3)))
    quality = round(rng.random(), 4)

    topics, skills, bio_sentences = [], [], []
    for cid in held:
        phrases = concepts_by_id[cid]["profile_phrases"]
        chosen = rng.sample(phrases, rng.randint(1, 3))
        if rng.random() < BIO_ONLY_PROB:
            bio_sentences.extend(f"I can help with {p}." for p in chosen)
            continue
        topics.append(chosen[0])
        for phrase in chosen[1:]:
            (topics if rng.random() < 0.5 else skills).append(phrase)
        if rng.random() < 0.5:
            bio_sentences.append(f"Much of my work involves {chosen[-1]}.")

    bio_sentences.extend(rng.sample(fillers, rng.randint(1, 3)))
    rng.shuffle(bio_sentences)

    max_open = None if rng.random() < 0.3 else rng.randint(1, 6)
    if max_open is None:
        open_count = rng.randint(0, 3)
    else:
        open_count = rng.randint(0, max_open)

    reviews = []
    for _ in range(rng.randint(0, 8)):
        noisy = 1 + 4 * quality + rng.gauss(0, 0.8)
        reviews.append({
            "course": rng.choice(completed),
            "rating": int(round(_clamp(noisy, 1, 5))),
        })

    helpful = {}
    for course in completed:
        lam = (0.2 + 2.0 * quality) * rng.uniform(0.5, 1.5)
        helpful[course] = _poisson(rng, lam)

    return {
        "id": f"a{index:03d}",
        "name": f"Advisor {index:03d}",
        "program": rng.choice(PROGRAMS),
        "year": rng.randint(1, 4),
        "completed_courses": completed,
        "advice_topics": "; ".join(topics),
        "skills": ", ".join(skills),
        "interests": ", ".join(rng.sample(interests, rng.randint(1, 3))),
        "bio": " ".join(bio_sentences),
        "max_open_requests": max_open,
        "open_request_count": open_count,
        "reviews": reviews,
        "helpful_answers": helpful,
        "hidden": {"concepts": held, "quality": quality},
    }


def generate(seed: int) -> dict:
    rng = random.Random(seed)
    spec = load_concepts()
    concepts_by_id = {c["id"]: c for c in spec["concepts"]}
    concept_ids = [c["id"] for c in spec["concepts"]]
    fillers = spec["filler_bio_sentences"]
    interests = spec["interest_phrases"]

    courses = sorted(rng.sample(COURSE_POOL, N_COURSES))

    advisors = [
        _make_advisor(rng, i, courses, concepts_by_id, concept_ids, interests, fillers)
        for i in range(1, N_ADVISORS + 1)
    ]

    requests = []
    attempts = 0
    while len(requests) < N_REQUESTS:
        attempts += 1
        if attempts > MAX_REQUEST_ATTEMPTS:
            raise RuntimeError("could not build enough valid requests; adjust the generator")
        course = rng.choice(courses)
        target = rng.choice(concept_ids)
        need = rng.choice(concepts_by_id[target]["request_phrases"])
        secondary = None
        if rng.random() < SECONDARY_PHRASE_PROB:
            secondary = rng.choice([c for c in concept_ids if c != target])
            extra = rng.choice(concepts_by_id[secondary]["request_phrases"])
            need = f"{need}. Also, {extra}"

        suitable = suitable_advisor_ids(advisors, course, target)
        pool = candidate_count(advisors, course)
        if not suitable or pool < MIN_CANDIDATES:
            continue
        requests.append({
            "id": f"r{len(requests) + 1:03d}",
            "course": course,
            "need": need,
            "hidden": {"target_concept": target, "secondary_concept": secondary},
            "candidate_count": pool,
            "suitable_advisor_ids": suitable,
        })

    return {
        "metadata": {
            "seed": seed,
            "generator_version": GENERATOR_VERSION,
            "counts": {
                "courses": len(courses),
                "advisors": len(advisors),
                "requests": len(requests),
                "concepts": len(concept_ids),
            },
            "quality_threshold": QUALITY_THRESHOLD,
            "min_candidates": MIN_CANDIDATES,
        },
        "courses": courses,
        "concepts": concept_ids,
        "advisors": advisors,
        "requests": requests,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None,
                        help="output JSON path; prints to stdout when omitted")
    args = parser.parse_args(argv)

    text = json.dumps(generate(args.seed), sort_keys=True, indent=2) + "\n"
    if args.out is None:
        sys.stdout.write(text)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} (seed {args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
