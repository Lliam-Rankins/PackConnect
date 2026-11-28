"""SQL eligibility rules shared by advisor search and advisor matching."""

from availability import availability_status_sql
from course_catalog import COURSE_TITLES, course_key, matching_title_codes
from identity import registered_student_sql

COMPLETED_COURSE_KEY = "regexp_replace(UPPER(c.course_code), '[[:space:]-]+', '', 'g')"

PROFILE_FILTER_COLUMNS = ("program", "year", "skills", "advice_topics")

_NOT_BLOCKED = ("NOT EXISTS (SELECT 1 FROM student_blocks b WHERE (b.blocker_id=%s AND b.blocked_id=s.id) "
                "OR (b.blocker_id=s.id AND b.blocked_id=%s))")


def advisor_conditions(viewer, course):
    """Return (conditions, params, course_codes) for advisors the viewer may see.

    Pure: no database access. Conditions assume the students table is aliased `s`
    and use %s placeholders; params are in the same order as the placeholders.
    - Always: advisor is a registered student.
    - viewer (student id or None): hides advisors blocked either way.
    - course (free text, may be empty): advisor completed it, matching by course
      key and, for unknown codes, by catalog title.
    course_codes is the list matched against (empty without a course).
    """
    conditions = [registered_student_sql()]
    params = []
    if viewer:
        conditions.append(_NOT_BLOCKED)
        params.extend([viewer, viewer])

    course_codes = []
    if course:
        code = course_key(course)
        course_codes = [code]
        if code not in COURSE_TITLES:
            course_codes.extend(matching_title_codes(course))
        conditions.append(f"""
            EXISTS (
                SELECT 1
                FROM completed_courses c
                WHERE c.student_id = s.id
                  AND {COMPLETED_COURSE_KEY} = ANY(%s::text[])
            )
        """)
        params.append(course_codes)
    return conditions, params, course_codes


def profile_filters(filters):
    """Return (conditions, params) for the optional hard filters on an advisor list.

    Pure. filters is a mapping: each PROFILE_FILTER_COLUMNS value (text, may be empty)
    is a case-insensitive substring match; `available` (default True) keeps only
    advisors accepting requests, which needs availability.workload_join() as `w`.
    """
    conditions, params = [], []
    if filters.get("available", True):
        conditions.append(f"({availability_status_sql()}) = 'available'")
    for column in PROFILE_FILTER_COLUMNS:
        value = filters.get(column)
        if value:
            conditions.append(f"LOWER(COALESCE(s.{column}, '')) LIKE %s")
            params.append(f"%{value.lower()}%")
    return conditions, params
