"""Seed fictional demo accounts for trying search and advisor matching: `just seed`.

Creates signed-in-capable advisors (with reviews and helpful Q&A answers) and two
students to log in as. Every email ends in @packconnect.test. Safe to re-run: it
does nothing once the demo accounts exist. Refuses non-local databases unless
--allow-hosted is given, because demo users become visible to real users.
"""

import argparse
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from werkzeug.security import generate_password_hash

EMAIL_DOMAIN = "packconnect.test"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass(frozen=True)
class DemoPerson:
    key: str
    name: str
    program: str
    year: str
    bio: str = ""
    interests: str = ""
    skills: str = ""
    advice_topics: str = ""
    completed: tuple = ()
    advises: bool = False
    max_open_requests: int | None = 5
    ratings: tuple = ()                       # one completed request + review per rating
    helpful_answers: dict = field(default_factory=dict)  # course -> count

    @property
    def email(self):
        return f"{self.key}@{EMAIL_DOMAIN}"


STUDENTS = (
    DemoPerson("riley", "Riley Demo", "MS Computer Science", "First Year",
               bio="New to NC State and looking for course advice."),
    DemoPerson("casey", "Casey Demo", "MS Computer Engineering", "First Year",
               bio="Exploring electives and project courses."),
)

ADVISORS = (
    DemoPerson("priya", "Priya Raman", "MS Computer Science", "Second Year",
               bio="TA for software engineering; I like helping teams ship.",
               interests="hiking, board games",
               skills="pytest, GitHub Actions, Flask",
               advice_topics="unit testing; continuous integration; team project workflow",
               completed=("CSC 510", "CSC 517"), advises=True,
               ratings=(5, 5, 4), helpful_answers={"CSC 510": 3}),
    DemoPerson("marcus", "Marcus Hill", "MS Computer Science", "Second Year",
               bio="Backend developer before grad school.",
               interests="cycling",
               skills="PostgreSQL, SQL query tuning, schema design",
               advice_topics="database design; slow queries and indexing; ORMs",
               completed=("CSC 510", "CSC 540"), advises=True,
               ratings=(4, 4), helpful_answers={"CSC 540": 2}),
    DemoPerson("lena", "Lena Ortiz", "MS Computer Science", "Second Year",
               bio="Frontend focused, happy to review UI code.",
               interests="photography, coffee",
               skills="React, CSS, accessibility",
               advice_topics="React components and state; accessible frontends; course project demos",
               completed=("CSC 510", "CSC 519"), advises=True,
               ratings=(5,), helpful_answers={"CSC 510": 1}),
    DemoPerson("omar", "Omar Haddad", "MS Computer Science", "Third Year",
               bio="Research assistant in machine learning.",
               interests="chess",
               skills="Python, PyTorch, scikit-learn",
               advice_topics="machine learning projects; reading research papers; data cleaning",
               completed=("CSC 522", "CSC 510"), advises=True, max_open_requests=2,
               ratings=(4, 5)),
    DemoPerson("grace", "Grace Chen", "MS Computer Engineering", "Second Year",
               bio="Systems programmer; I debug C for fun.",
               interests="piano",
               skills="C, gdb, Linux",
               advice_topics="debugging segfaults and pointers; operating systems assignments",
               completed=("CSC 501", "CSC 510"), advises=True,
               ratings=(3, 4)),
    DemoPerson("diego", "Diego Santos", "MS Computer Science", "Second Year",
               bio="Interned twice; glad to talk careers.",
               interests="soccer",
               skills="system design, LeetCode",
               advice_topics="internship applications; technical interview practice; time management",
               completed=("CSC 510", "CSC 505"), advises=True),
)


def is_local(database_url):
    return conninfo_to_dict(database_url or "").get("host") in LOCAL_HOSTS


def _insert_person(db, person, password_hash):
    student_id = db.execute("""
        INSERT INTO students (name, program, year, bio, interests, skills, advice_topics,
                              willing_to_advise, max_open_requests)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (person.name, person.program, person.year, person.bio, person.interests, person.skills,
          person.advice_topics, person.advises, person.max_open_requests)).fetchone()["id"]
    db.execute("INSERT INTO accounts (student_id, email, password_hash) VALUES (%s, %s, %s)",
               (student_id, person.email, password_hash))
    db.cursor().executemany("INSERT INTO completed_courses (student_id, course_code) VALUES (%s, %s)",
                            [(student_id, course) for course in person.completed])
    return student_id


def _add_reviews(db, advisor, advisor_id, reviewer_ids):
    course = advisor.completed[0]
    for index, rating in enumerate(advisor.ratings):
        request_id = db.execute("""
            INSERT INTO advice_requests (sender_id, recipient_id, course_code, advice_topic, message, status)
            VALUES (%s, %s, %s, 'Course advice', 'Demo request', 'completed') RETURNING id
        """, (reviewer_ids[index % len(reviewer_ids)], advisor_id, course)).fetchone()["id"]
        db.execute("INSERT INTO advice_reviews (request_id, rating, comment) VALUES (%s, %s, %s)",
                   (request_id, rating, "Demo review"))


def _add_helpful_answers(db, advisor, advisor_id, asker_id):
    for course, count in advisor.helpful_answers.items():
        for number in range(count):
            question_id = db.execute("""
                INSERT INTO course_questions (author_id, course_code, title, body)
                VALUES (%s, %s, %s, 'Demo question') RETURNING id
            """, (asker_id, course, f"{course} question {number + 1} for {advisor.name}")).fetchone()["id"]
            answer_id = db.execute("""
                INSERT INTO course_answers (question_id, author_id, body)
                VALUES (%s, %s, 'Demo answer') RETURNING id
            """, (question_id, advisor_id)).fetchone()["id"]
            db.execute("INSERT INTO course_helpful_answers (question_id, answer_id) VALUES (%s, %s)",
                       (question_id, answer_id))


def seed(db, password, embedder):
    """Insert the demo data unless it already exists; returns (created, failed_embeddings)."""
    from matching import profile_vectors

    if db.execute("SELECT 1 FROM accounts WHERE lower(email) = %s", (STUDENTS[0].email,)).fetchone():
        return False, 0
    password_hash = generate_password_hash(password)
    student_ids = [_insert_person(db, person, password_hash) for person in STUDENTS]
    failed = 0
    for advisor in ADVISORS:
        advisor_id = _insert_person(db, advisor, password_hash)
        _add_reviews(db, advisor, advisor_id, student_ids)
        _add_helpful_answers(db, advisor, advisor_id, student_ids[0])
        failed += not profile_vectors.refresh(db, embedder, advisor_id)
    return True, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allow-hosted", action="store_true",
                        help="seed a non-local database (demo users become visible to real users)")
    args = parser.parse_args(argv)

    load_dotenv(Path(__file__).parent / ".env")
    database_url = os.getenv("SUPABASE_DB_URL")
    if not database_url:
        raise SystemExit("Set SUPABASE_DB_URL in backend/.env.")
    if not is_local(database_url) and not args.allow_hosted:
        raise SystemExit("Refusing to seed a non-local database. Re-run with --allow-hosted "
                         "(e.g. `just seed --allow-hosted`) if you really want demo users there.")

    import app as portal
    password = os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(12)
    with portal.get_db() as db:
        created, failed = seed(db, password, portal.app.config["EMBEDDER"])
    if not created:
        print("Demo accounts already exist; nothing to do.")
        return
    print(f"Seeded {len(STUDENTS)} students and {len(ADVISORS)} advisors (emails end in @{EMAIL_DOMAIN}).")
    print(f"Sign in as {STUDENTS[0].email}; password: "
          + ("from DEMO_PASSWORD" if os.getenv("DEMO_PASSWORD") else password))
    if failed:
        print(f"{failed} advisor profiles could not be embedded yet; run `just embed`.")


if __name__ == "__main__":
    sys.exit(main())
