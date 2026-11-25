"""Member-visible course questions with server-owned identity and helpful answers."""

from functools import wraps
import re

from flask import Blueprint, jsonify, request, session
from course_catalog import course_key, course_label
from identity import session_student_id
from lifecycle import blocked


def course_code(value):
    if not isinstance(value, str) or len(value) > 30:
        raise ValueError("Use a course code such as CSC 510.")
    key = course_key(value)
    if not re.fullmatch(r"[A-Z]{2,4}[0-9]{3}[A-Z]?", key):
        raise ValueError("Use a course code such as CSC 510.")
    return course_label(key)


def text_field(data, name, limit):
    value = data.get(name)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError(f"{name.capitalize()} must contain 1–{limit} characters.")
    return value.strip()


# Each caller supplies fixed SQL aliases, never request data.
def visible_author(alias):
    return f"""NOT EXISTS (SELECT 1 FROM student_blocks b
        WHERE (b.blocker_id=%s AND b.blocked_id={alias}.author_id)
           OR (b.blocked_id=%s AND b.blocker_id={alias}.author_id))"""


def create_course_qa_blueprint(get_db):
    api = Blueprint("course_qa", __name__)

    def authenticated(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with get_db() as db:
                user = session_student_id(db, session)
                if user is None:
                    return jsonify(error="Sign in to use the course Q&A board."), 401
                try:
                    return function(db, user, *args, **kwargs)
                except ValueError as exc:
                    return jsonify(error=str(exc)), 400
        return wrapped

    def question(db, user, question_id, lock=False):
        if not 0 < question_id <= 9223372036854775807:
            return None
        return db.execute(f"""SELECT q.*, s.name AS author_name, h.answer_id AS helpful_answer_id
            FROM course_questions q JOIN students s ON s.id=q.author_id
            LEFT JOIN course_helpful_answers h ON h.question_id=q.id
            WHERE q.id=%s AND {visible_author('q')}
            {'FOR UPDATE OF q' if lock else ''}""", (question_id, user, user)).fetchone()

    @api.get("/api/qa/questions")
    @authenticated
    def list_questions(db, user):
        course = request.args.get("course", "").strip()
        query = request.args.get("q", "").strip()
        status = request.args.get("status", "all")
        if len(query) > 200 or status not in ("all", "answered", "unanswered"):
            raise ValueError("Invalid search or answer filter.")
        before = request.args.get("before", "")
        if before and (not before.isdecimal() or not 0 < int(before) <= 9223372036854775807):
            raise ValueError("Invalid page cursor.")
        clauses = [visible_author("q")]
        params = [user, user]
        if course:
            clauses.append("q.course_code=%s")
            params.append(course_code(course))
        if query:
            clauses.append(f"""(strpos(lower(q.title || ' ' || q.body), lower(%s))>0 OR EXISTS
                (SELECT 1 FROM course_answers a WHERE a.question_id=q.id AND {visible_author('a')}
                 AND strpos(lower(a.body),lower(%s))>0))""")
            params.extend([query, user, user, query])
        if status != "all":
            clauses.append(f"h.answer_id IS {'NOT ' if status == 'answered' else ''}NULL")
        if before:
            clauses.append("q.id<%s")
            params.append(int(before))
        rows = db.execute(f"""SELECT q.*, s.name AS author_name, h.answer_id AS helpful_answer_id,
            (SELECT count(*) FROM course_answers a WHERE a.question_id=q.id AND {visible_author('a')}) AS answer_count
            FROM course_questions q JOIN students s ON s.id=q.author_id
            LEFT JOIN course_helpful_answers h ON h.question_id=q.id
            WHERE {' AND '.join(clauses)} ORDER BY q.id DESC LIMIT 21""",
            (user, user, *params)).fetchall()
        return jsonify(questions=[dict(row) for row in rows[:20]],
                       next_before=rows[19]["id"] if len(rows) > 20 else None)

    @api.post("/api/qa/questions")
    @authenticated
    def post_question(db, user):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Send a question as a JSON object.")
        course = course_code(data.get("course_code"))
        title, body = text_field(data, "title", 160), text_field(data, "body", 4000)
        row = db.execute("""INSERT INTO course_questions(author_id,course_code,title,body)
            VALUES(%s,%s,%s,%s) RETURNING id""", (user, course, title, body)).fetchone()
        return jsonify(question=dict(question(db, user, row["id"]))), 201

    @api.get("/api/qa/questions/<int:question_id>")
    @authenticated
    def get_question(db, user, question_id):
        row = question(db, user, question_id)
        if not row:
            return jsonify(error="Question not found."), 404
        answers = db.execute(f"""SELECT a.*,s.name AS author_name FROM course_answers a
            JOIN students s ON s.id=a.author_id WHERE a.question_id=%s AND {visible_author('a')}
            ORDER BY a.id LIMIT 201""", (question_id, user, user)).fetchall()
        return jsonify(question=dict(row), answers=[dict(a) for a in answers[:200]],
                       answers_truncated=len(answers) > 200)

    @api.post("/api/qa/questions/<int:question_id>/answers")
    @authenticated
    def post_answer(db, user, question_id):
        if not question(db, user, question_id, lock=True):
            return jsonify(error="Question not found."), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Send an answer as a JSON object.")
        body = text_field(data, "body", 4000)
        count = db.execute("SELECT count(*) FROM course_answers WHERE question_id=%s", (question_id,)).fetchone()["count"]
        if count >= 200:
            return jsonify(error="This question has reached its 200-answer limit."), 409
        row = db.execute("""INSERT INTO course_answers(question_id,author_id,body)
            VALUES(%s,%s,%s) RETURNING id""", (question_id, user, body)).fetchone()
        return jsonify(answer_id=row["id"]), 201

    @api.put("/api/qa/questions/<int:question_id>/helpful-answer")
    @authenticated
    def mark_helpful(db, user, question_id):
        row = question(db, user, question_id, lock=True)
        if not row:
            return jsonify(error="Question not found."), 404
        if row["author_id"] != user:
            return jsonify(error="Only the question author can select a helpful answer."), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "answer_id" not in data:
            raise ValueError("Provide answer_id, or null to clear the selection.")
        answer_id = data["answer_id"]
        if answer_id is None:
            db.execute("DELETE FROM course_helpful_answers WHERE question_id=%s", (question_id,))
        else:
            if type(answer_id) is not int or not 0 < answer_id <= 9223372036854775807:
                raise ValueError("Invalid answer ID.")
            answer = db.execute("SELECT author_id FROM course_answers WHERE id=%s AND question_id=%s",
                                (answer_id, question_id)).fetchone()
            if not answer or blocked(db, user, answer["author_id"]):
                return jsonify(error="Answer not found for this question."), 404
            db.execute("""INSERT INTO course_helpful_answers(question_id,answer_id) VALUES(%s,%s)
                ON CONFLICT(question_id) DO UPDATE SET answer_id=excluded.answer_id""", (question_id, answer_id))
        return jsonify(helpful_answer_id=answer_id)

    return api
