"""HTTP endpoint for ranked advisor recommendations."""

import logging
import math
from collections import OrderedDict
from threading import Lock

from flask import Blueprint, jsonify, request, session

from common.advisor_sql import PROFILE_FILTER_COLUMNS
from identity import session_student_id
from matching.embedder import vector_literal
from matching.scoring import DEFAULT_WEIGHTS, rank
from matching.signals import fetch_candidates

MAX_NEED_LENGTH = 300
MAX_RESULTS = 50

log = logging.getLogger(__name__)


class QueryVectorCache:
    """Small thread-safe LRU of query embeddings keyed by (model_name, need)."""

    def __init__(self, maxsize=256):
        self.maxsize = maxsize
        self._vectors = OrderedDict()
        self._lock = Lock()

    def vector(self, embedder, need):
        """The need's query embedding, or None when the embedder fails (not cached)."""
        key = (embedder.model_name, need)
        with self._lock:
            if key in self._vectors:
                self._vectors.move_to_end(key)
                return self._vectors[key]
        try:
            vector = embedder.embed_queries([need])[0]
            vector_literal(vector)  # reject wrong dimensions or non-finite values up front
        except Exception as error:  # fall back to keyword-only ranking
            log.warning("Query embedding failed; ranking by keywords only: %s", type(error).__name__)
            return None
        with self._lock:
            self._vectors[key] = vector
            if len(self._vectors) > self.maxsize:
                self._vectors.popitem(last=False)
        return vector


def _number(value):
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), 4)


def _student_json(candidate, match):
    return {
        **candidate.profile,
        "review_summary": {"average_rating": candidate.average_rating,
                           "review_count": candidate.review_count},
        "match": {
            "score": _number(match.score),
            "breakdown": {name: _number(value) for name, value in match.breakdown.items()},
            "reasons": match.reasons,
        },
    }


def _request_filters(args):
    filters = {column: args.get(column, "").strip() for column in PROFILE_FILTER_COLUMNS}
    filters["available"] = args.get("available", "true").strip().lower() != "false"
    return filters


def create_matching_blueprint(get_db, get_embedder, weights=DEFAULT_WEIGHTS):
    api = Blueprint("matching", __name__)
    query_vectors = QueryVectorCache()

    @api.get("/api/students/recommendations")
    def recommendations():
        with get_db() as db:
            viewer = session_student_id(db, session)
        if viewer is None:
            return jsonify(error="Sign in to get recommendations."), 401
        course = request.args.get("course", "").strip()
        need = request.args.get("need", "").strip()
        if not course:
            return jsonify(error="Choose a course to get recommendations."), 400
        if not need:
            return jsonify(error="Describe what you need help with."), 400
        if len(need) > MAX_NEED_LENGTH:
            return jsonify(error=f"Keep what you need help with to {MAX_NEED_LENGTH} characters."), 400

        query_vector = query_vectors.vector(get_embedder(), need)
        with get_db() as db:
            candidates, course_codes = fetch_candidates(
                db, viewer=viewer, course=course, need=need,
                query_vector=query_vector, filters=_request_filters(request.args))
        ranked = rank(candidates, weights)[:MAX_RESULTS]
        return jsonify(students=[_student_json(c, m) for c, m in ranked], course_codes=course_codes)

    return api
