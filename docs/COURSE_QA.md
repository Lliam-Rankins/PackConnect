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

## Automated browser regression

The dedicated `Q&A browser regression` workflow runs Chromium, Vite, the real
Flask API and PostgreSQL. It does not intercept or mock API requests. Two separate
browser contexts log in as fictional accounts, ask/answer, verify author-only
helpful selection, reload for persistence, then find advice by answer text with
course/status filters. It runs at 390px and 1280px and checks horizontal overflow.
An anonymous HTTP request must still be denied. A third test sends 12 concurrent
reads and checks response correctness and unchanged data, recording elapsed time.
This small correctness check is not a production load/capacity benchmark.

To run locally, install the existing backend requirements into a virtual env,
then from `frontend/`:

```sh
npm ci
npx playwright install chromium
TEST_DATABASE_URL='postgresql://USER@127.0.0.1/packconnect_test?sslmode=disable' \
  E2E_PYTHON=../.venv/bin/python npm run test:e2e
```

The runner refuses a remote host or a database name that does not end in `_test`.
It uses the existing test fixture to apply migrations in a temporary random
schema and cleans it up after a normal shutdown. It also creates the minimal
Supabase Auth table/roles needed by the existing local fixture. Never point it
at a database with real accounts. The servers bind only to localhost on ports
5052/5174 and refuse to reuse existing servers. Hosted credential environment
variables are blanked in the test process. No local `.env` file is rewritten.
CI stores the HTML report and failure traces/screenshots as artifacts.

The isolated unit checks can run without any database:

```sh
python -m unittest discover -s backend -p 'test_course_qa_unit.py' -v
```

They cover course normalization, invalid types/formats, exact text boundaries,
whitespace, Unicode and preserving plain text. Existing real-database tests
remain distinct. Hosted Supabase checks still require the team's approved
configuration; browser tests do not establish live deployment readiness.
