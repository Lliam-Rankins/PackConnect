# Course Q&A board

The board makes course advice reusable instead of leaving it only in private conversations.
Signed-in members can ask questions, answer other members, and search previous advice.
Only the question author can select, replace or clear one helpful answer. An answer
is peer advice, not an official or verified advisor response.

## Setup

Apply the versioned migrations with the existing backend setup before deploying:

```sh
python backend/migrate.py
```

This adds `course_questions`, `course_answers` and `course_helpful_answers`.
Existing profiles, requests, reviews and messaging tables are unchanged. The
Flask database role needs the same migration/service privileges as existing app
storage. Browser `anon` and `authenticated` roles have no direct table access;
all Q&A operations pass through the session-authenticated Flask API.
Do not apply a test database URL to the team's hosted project.

## Using the board

1. Sign in and open **Course Q&A** in the navigation (`#/app/qa`).
2. Ask a question with a course code, a title and details. `csc510`, `CSC-510`
   and `CSC 510` are stored consistently as `CSC 510`. Codes need not already
   appear in the local catalog.
3. A second member opens the question and posts an answer. The answer's author
   comes from the session, never from an ID supplied by the browser.
4. The question author marks an answer helpful. The author can select another
   answer or clear the selection. Other users do not have these controls, and
   direct attempts receive 403.
5. Search the text of questions and answers, filter by exact course code, or
   show questions with/without a helpful answer. “No helpful answer” can include
   questions that have responses the author has not selected.

Posts are visible to signed-in members, not private messages. Do not include
personal information. Existing blocks in either direction hide each other's
questions and answers. Blocked answer text cannot appear in search or counts.
There is no new moderator-content workflow in this version. Authors cannot edit
or delete posted text yet; use thoughtful, non-sensitive demo content.

## Limits and behavior

- Titles: 1–160 characters. Questions and answers: 1–4,000 characters after trimming.
- Search: up to 200 characters, literal case-insensitive substring matching
  (no fuzzy or semantic search). SQL parameters carry all request values.
- Newest questions first, 20 per page, with a stable ID cursor and Load more.
- Threads accept up to 200 answers. Question locks serialize answer-limit checks
  and helpful-answer changes; database constraints prevent cross-thread selection.
- Text renders as plain text, never raw HTML. Emails, account tokens and password
  fields are not included in the response.
- No automatic polling or new Supabase Realtime dependency. Refresh to see new
  activity from another member. A successful local action refreshes its thread.
- Original features and their APIs remain separate from this new blueprint.

## API

All endpoints require a valid existing account session. Revoked sessions receive 401.

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/qa/questions?course=CSC510&q=projects&status=all&before=123` | List/filter/search, `questions` and `next_before`; optional filters |
| POST | `/api/qa/questions` | `{course_code,title,body}`; returns `question`, HTTP 201 |
| GET | `/api/qa/questions/<id>` | `question` and visible `answers` |
| POST | `/api/qa/questions/<id>/answers` | `{body}`; returns `answer_id`, HTTP 201 |
| PUT | `/api/qa/questions/<id>/helpful-answer` | Author only; `{answer_id}` or `{answer_id:null}` to clear |

Missing/blocked resources return 404. Invalid input returns 400. Selecting an
answer from another question returns 404. Answer capacity returns 409.

## Tests

Use a dedicated **local** PostgreSQL database, not live Supabase:

```sh
TEST_DATABASE_URL='postgresql://USER@127.0.0.1/packconnect_test?sslmode=disable' \
  python -m unittest discover -s backend -p 'test_*.py'
cd frontend
npm test
npm run lint
npm run build
```

The Q&A tests exercise posting and persistence, session ownership, revoked and
anonymous sessions, cross-thread selection, course/text/status filtering,
blocked-content leakage, literal search, limits, paging, concurrent selection,
database constraints, browser-role permissions and frontend navigation/forms.
They run automatically through the existing CI discovery commands.

## Two-minute demonstration

Use fictional accounts and course questions:

1. Author asks “How should our CSC 510 team divide the project work?”
2. Another account posts a concrete answer.
3. Show that the second account cannot select a helpful answer.
4. Switch to the author and select the answer.
5. Search a distinctive phrase from the answer with course `CSC510` and the
   “Helpful answer selected” filter. Open the saved advice again.

This demonstrates new behavior since the inherited private-advice flow. It is
not evidence of a measured improvement in real student outcomes. A business M0
claim needs a separately designed retrieval/usability evaluation and reported
results; passing workflow tests alone does not establish that claim.
