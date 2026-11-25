# Course autocomplete

The peer-search course field accepts course codes and titles. Suggestions come
from registered students' self-reported completed courses. Confirmed, linked
Supabase users are included before their first app login. Courses from advisors
who paused advising can still appear because the availability filter applies
when finding peers.

`GET /api/courses?q=software%20engineering` returns a `courses` array with up to
ten distinct codes and a `titles` object keyed by those codes. Suggestions match
literal code prefixes and partial titles. Code matching ignores case, whitespace,
and hyphens. Title matching ignores case and collapses repeated spaces. Code
prefix matches appear first, with each group sorted by code.

Choosing a suggestion places its code in the search field. If a student submits
a title directly, `/api/students/search` finds peers who completed any matching
course and returns the normalized `course_codes` used in the search. Advice
requests use a matching completed course code when available.

[`backend/course_titles.csv`](../backend/course_titles.csv) contains 6,209 code
and title pairs from the 2026–27 [NC State course descriptions](https://catalog.ncsu.edu/course-descriptions/).
Refresh the `code,title` CSV from that catalog when titles change. Codes absent
from the snapshot remain searchable by code. The feature works with the existing
database schema.

The field waits 200 ms after typing before requesting suggestions and cancels
outdated requests. Arrow keys highlight options; Enter selects the highlighted
code without submitting the form. Enter again submits the search. Escape, blur,
or selection closes the list. Highlighted options scroll into view. Manual entry
remains available when no suggestion matches or the API fails or returns an
invalid response.

## Automated verification

From `frontend/`, run `npm test`, `npm run lint`, `npm run build`, and
`npx prettier --check "src/**/*.{js,jsx,ts,tsx,css,json}"`.

From the repository root, run the backend suite with a dedicated local database
as described in [Supabase verification](SUPABASE.md#verification).

Coverage includes keyboard selection and wrapping, scrolling, mouse selection,
Escape and blur, manual-search fallbacks, malformed API data, debouncing,
cancellation and stale responses, selection with advanced filters, normalization,
deduplication, result limits, literal prefixes, registered-account eligibility,
Supabase email confirmation, and suggestions changing after profile edits.

## Browser acceptance check

Use two fictional accounts: an advisor with several completed courses and a
student looking for advice.

1. Sign in as the student, enter a partial title such as `software engine`, and
   confirm that suggestions show each matching code and its title.
2. Use ArrowUp to highlight the final suggestion; confirm it scrolls into view.
3. Press Enter to select it, then Enter again to search and find the advisor.
4. Submit `software engineering` directly and confirm that peers from multiple
   matching courses can appear. Search `csc-510` to verify code normalization.
5. Repeat at a narrow mobile viewport; tap a suggestion and check that the page
   has no horizontal overflow.
6. Check that Escape and clicking elsewhere close the dropdown, and that typing
   an unknown code still permits manual search.

On October 28, 2026, local verification passed 30 frontend tests and 94 backend
tests, with two opt-in live Supabase tests skipped. Lint, formatting, and the
production build passed. Headless Chrome checked the production build against
Flask and isolated PostgreSQL at desktop and mobile sizes: suggestions, keyboard
scrolling/selection, normalized manual search, touch selection, and horizontal
overflow checks passed without JavaScript exceptions. Live Supabase data was not
used for these checks.
