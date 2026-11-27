"""Pure ranking logic: turns a Candidate's signals into a score and reasons.

Topic-gated formula:
    quality = quality_floor + rating*rating_signal + qa_help*qa_signal + capacity*capacity_signal
    score   = topic_fit * quality
Weights (floor + the three multipliers) sum to 1, so quality is in [floor, 1]. An advisor with
no topic match scores 0 however well rated; among topic matches, quality reorders modestly.
"""

import math
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Candidate:
    student_id: int
    keyword_rank: float = 0.0
    matched_terms: list = field(default_factory=list)
    field_similarity: dict = field(default_factory=dict)
    review_count: int = 0
    average_rating: float | None = None
    helpful_answers: int = 0
    max_open_requests: int | None = None
    open_request_count: int = 0
    profile: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Weights:
    fields: dict = field(
        default_factory=lambda: {"advice_topics": 0.4, "skills": 0.3, "interests": 0.15, "bio": 0.15}
    )
    # Tuned on eval seed 1 only (eval/README.md); seed 2 is the held-out report.
    alpha: float = 0.2
    quality_floor: float = 0.8
    rating: float = 0.12
    qa_help: float = 0.05
    capacity: float = 0.03
    rating_prior_mean: float = 3.5
    rating_prior_count: float = 3
    qa_saturation: float = 5
    semantic_reason_threshold: float = 0.6

    def __post_init__(self):
        parts = (self.quality_floor, self.rating, self.qa_help, self.capacity)
        if any(p < 0 for p in parts):
            raise ValueError("quality weights must be >= 0")
        if abs(sum(parts) - 1.0) > 1e-9:
            raise ValueError("quality_floor + rating + qa_help + capacity must sum to 1.0")

    def with_alpha(self, alpha: float) -> "Weights":
        return replace(self, alpha=alpha)

    def with_quality(self, floor: float, rating: float, qa_help: float, capacity: float) -> "Weights":
        return replace(self, quality_floor=floor, rating=rating, qa_help=qa_help, capacity=capacity)


DEFAULT_WEIGHTS = Weights()


@dataclass(frozen=True)
class Match:
    score: float
    breakdown: dict
    reasons: list


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def semantic_score(field_similarity: dict, weights: Weights = DEFAULT_WEIGHTS):
    """Weighted average over present fields, similarity clamped to [0, 1]; None if none."""
    total = 0.0
    weight_sum = 0.0
    for name, weight in weights.fields.items():
        if name in field_similarity and weight > 0:
            total += weight * _clamp01(field_similarity[name])
            weight_sum += weight
    return total / weight_sum if weight_sum else None


def topic_fit(keyword: float, semantic, alpha: float) -> float:
    if semantic is None:
        return _clamp01(keyword)
    return alpha * _clamp01(keyword) + (1 - alpha) * semantic


def rating_score(average, count: int, weights: Weights = DEFAULT_WEIGHTS) -> float:
    n = count if average is not None else 0
    avg = average if average is not None else 0.0
    prior_n = weights.rating_prior_count
    smoothed = (n * avg + prior_n * weights.rating_prior_mean) / (n + prior_n)
    return _clamp01((smoothed - 1) / 4)


def qa_help_score(helpful_answers: int, saturation: float = 5) -> float:
    if helpful_answers <= 0:
        return 0.0
    return min(1.0, math.log(1 + helpful_answers) / math.log(1 + saturation))


def capacity_score(max_open_requests, open_request_count: int) -> float:
    if max_open_requests is None:
        return 1.0
    if max_open_requests <= 0:
        return 0.0
    free = max(0, max_open_requests - open_request_count)
    return free / max_open_requests


def _reasons(candidate, weights, kw, sem, fit, quality, rating, qa, cap):
    contributions = []
    if candidate.matched_terms:
        share = weights.alpha * kw if sem is not None else kw
        contributions.append(
            (share * quality, {"type": "keyword", "terms": list(candidate.matched_terms)})
        )
    sims = {k: v for k, v in candidate.field_similarity.items() if k in weights.fields}
    if sims and sem is not None:
        best = max(sims, key=lambda k: (sims[k], k))
        if sims[best] >= weights.semantic_reason_threshold:
            contributions.append(
                ((1 - weights.alpha) * sem * quality, {"type": "semantic", "field": best})
            )
    if candidate.review_count > 0 and candidate.average_rating is not None:
        contributions.append(
            (fit * weights.rating * rating,
             {"type": "rating", "average": candidate.average_rating, "count": candidate.review_count})
        )
    if candidate.helpful_answers > 0:
        contributions.append(
            (fit * weights.qa_help * qa, {"type": "qa_help", "count": candidate.helpful_answers})
        )
    if cap > 0:
        free = (None if candidate.max_open_requests is None
                else max(0, candidate.max_open_requests - candidate.open_request_count))
        contributions.append((fit * weights.capacity * cap, {"type": "capacity", "free": free}))
    contributions.sort(key=lambda pair: -pair[0])  # stable: ties keep insertion order
    return [reason for _, reason in contributions]


def score(candidate: Candidate, weights: Weights = DEFAULT_WEIGHTS) -> Match:
    kw = _clamp01(candidate.keyword_rank)
    sem = semantic_score(candidate.field_similarity, weights)
    fit = topic_fit(kw, sem, weights.alpha)
    rating = rating_score(candidate.average_rating, candidate.review_count, weights)
    qa = qa_help_score(candidate.helpful_answers, weights.qa_saturation)
    cap = capacity_score(candidate.max_open_requests, candidate.open_request_count)
    quality = (weights.quality_floor + weights.rating * rating
               + weights.qa_help * qa + weights.capacity * cap)
    breakdown = {
        "topic_fit": fit,
        "keyword": kw,
        "semantic": sem,
        "rating": rating,
        "qa_help": qa,
        "capacity": cap,
        "quality": quality,
    }
    return Match(score=fit * quality, breakdown=breakdown,
                 reasons=_reasons(candidate, weights, kw, sem, fit, quality, rating, qa, cap))


def rank(candidates, weights: Weights = DEFAULT_WEIGHTS):
    scored = [(c, score(c, weights)) for c in candidates]
    scored.sort(key=lambda pair: (-pair[1].score, pair[0].student_id))
    return scored
