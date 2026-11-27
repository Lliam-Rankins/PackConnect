"""Gather every ranking signal for eligible advisors in one database query."""

import math
import re

from availability import availability_columns, workload_join
from common.advisor_sql import advisor_conditions, profile_filters
from matching.embedder import vector_literal
from matching.scoring import Candidate

MAX_TERMS = 10
MIN_TERM_LENGTH = 3
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#]*")
# Filler words that would otherwise show up as "matched" reasons; Postgres drops its own stopwords too.
_STOPWORDS = frozenset("""
    about after also and any are can could for from get getting have help how into just like more need
    needs not now some than that the their them then there these this those want was what when where which
    who why will with would you your
""".split())

_DISPLAY_COLUMNS = "s.id, s.name, s.program, s.year, s.skills, s.advice_topics, s.willing_to_advise"
_COURSE_KEY = "regexp_replace(UPPER(q.course_code), '[[:space:]-]+', '', 'g')"


def need_terms(need):
    """Distinct need words worth reporting as matches, in their original order and case."""
    terms, seen = [], set()
    for word in _WORD.findall(need or ""):
        key = word.lower()
        if len(key) < MIN_TERM_LENGTH or key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(word)
        if len(terms) == MAX_TERMS:
            break
    return terms


def _similarity_sql(query_vector):
    if query_vector is None:
        return "'{}'::jsonb", []
    return """COALESCE((
            SELECT jsonb_object_agg(best.field, best.similarity)
            FROM (
                SELECT pe.field,
                       max(1 - (pe.embedding OPERATOR(extensions.<=>) %s::extensions.vector)) AS similarity
                FROM profile_embeddings pe
                WHERE pe.student_id = s.id AND pe.embedding IS NOT NULL
                GROUP BY pe.field
            ) best
        ), '{}'::jsonb)""", [vector_literal(query_vector)]


def _finite_similarities(raw):
    """Keep numeric, finite similarities (a zero query vector yields NaN)."""
    return {field: float(value) for field, value in (raw or {}).items()
            if isinstance(value, (int, float)) and math.isfinite(value)}


def _candidate(row):
    average = row["average_rating"]
    profile = {key: row[key] for key in (
        "id", "name", "program", "year", "skills", "advice_topics", "willing_to_advise",
        "max_open_requests", "pause_until", "open_request_count", "availability_status",
        "accepting_requests")}
    profile["willing_to_advise"] = bool(profile["willing_to_advise"])
    return Candidate(
        student_id=row["id"],
        keyword_rank=float(row["keyword_rank"]),
        matched_terms=list(row["matched_terms"]),
        field_similarity=_finite_similarities(row["field_similarity"]),
        review_count=row["review_count"],
        average_rating=float(average) if average is not None else None,
        helpful_answers=row["helpful_answers"],
        max_open_requests=row["max_open_requests"],
        open_request_count=row["open_request_count"],
        profile=profile,
    )


def fetch_candidates(db, *, viewer, course, need, query_vector=None, filters=None):
    """Return (candidates, course_codes) for advisors the viewer may ask about the course.

    Eligibility and hard filters match /api/students/search; the viewer is excluded.
    query_vector (a list of floats, or None for keyword-only) is compared with each
    stored profile field embedding.
    """
    conditions, where_params, course_codes = advisor_conditions(viewer, course)
    if viewer:
        conditions.append("s.id <> %s")
        where_params.append(viewer)
    filter_conditions, filter_params = profile_filters(filters or {})
    conditions += filter_conditions
    where_params += filter_params

    similarity_sql, similarity_params = _similarity_sql(query_vector)
    terms = need_terms(need)
    rows = db.execute(f"""
        SELECT {_DISPLAY_COLUMNS}, {availability_columns()},
            CASE WHEN numnode(nq.q) = 0 THEN 0 ELSE ts_rank(s.search_vector, nq.q, 32) END AS keyword_rank,
            ARRAY(
                SELECT t.term FROM unnest(%s::text[]) WITH ORDINALITY AS t(term, position)
                WHERE s.search_vector @@ plainto_tsquery('english', t.term)
                ORDER BY t.position
            ) AS matched_terms,
            {similarity_sql} AS field_similarity,
            rv.review_count, rv.average_rating, qa.helpful_answers
        FROM students s
        CROSS JOIN (
            SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery AS q
        ) nq
        {workload_join()}
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS review_count, AVG(v.rating) AS average_rating
            FROM advice_reviews v JOIN advice_requests r ON r.id = v.request_id
            WHERE r.recipient_id = s.id
        ) rv ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS helpful_answers
            FROM course_helpful_answers h
            JOIN course_answers a ON a.id = h.answer_id
            JOIN course_questions q ON q.id = h.question_id
            WHERE a.author_id = s.id AND q.author_id <> a.author_id
              AND {_COURSE_KEY} = ANY(%s::text[])
        ) qa ON true
        WHERE {" AND ".join(conditions)}
        ORDER BY s.id
    """, [terms, *similarity_params, need or "", course_codes, *where_params]).fetchall()
    return [_candidate(row) for row in rows], course_codes
