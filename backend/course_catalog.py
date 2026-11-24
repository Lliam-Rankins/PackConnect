"""Course titles from the published NC State catalog."""

import csv
import re
from pathlib import Path


def course_key(value):
    """Ignore spacing and hyphens consistently for discovery and matching."""
    return re.sub(r"[\s-]+", "", value).upper()


def course_label(code):
    return re.sub(r"^([A-Z]+)(\d)", r"\1 \2", code)


def title_key(value):
    return " ".join(value.casefold().split())


with Path(__file__).with_name("course_titles.csv").open(encoding="utf-8", newline="") as catalog:
    COURSE_TITLES = {course_key(row["code"]): row["title"] for row in csv.DictReader(catalog)}

_TITLE_KEYS = {code: title_key(title) for code, title in COURSE_TITLES.items()}


def matching_title_codes(query):
    query = title_key(query)
    if not 2 <= len(query) <= 150:
        return []
    return [code for code, title in _TITLE_KEYS.items() if query in title]
