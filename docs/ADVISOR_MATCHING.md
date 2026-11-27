# Ranked advisor matching

Peer search filters advisors by course and sorts them by name. Advisor matching
adds a ranked view: a student enters a course and a short description of what
they need help with, and advisors who completed the course are ordered by fit.
Each result shows why it matched.

Matching is peer guidance, not a verified recommendation. Scores are relative
within one search and have no absolute meaning.

## Using it in the app

On the **Find peers** page (`#/app`), fill in the course, then the
**What do you need help with?** field (up to 300 characters, for example
`testing Flask apps`). Press **Find Students**.

- A course is required. Without one, the app asks you to enter a course.
- You must be signed in. The recommendations request is rejected for signed-out
  visitors.
- When the need field has text, results come from the recommendations endpoint
  in score order. Clear the field to return to the name-sorted search.
- The top result shows a **Best match** badge. Each card shows up to three
  reason chips, such as `Mentions testing, Flask`, `Similar advice topics`,
  `Rated 4.2 (6 reviews)`, `2 helpful Q&A answers`, or `2 open slots`.
  Scores are not shown as percentages.
- Program, year, skills, advice topics and the availability filter still apply
  as hard filters.
- Editing your own profile while in recommendation mode reloads the results, so
  the order reflects the saved profile.

## API

```
GET /api/students/recommendations?course=CSC%20510&need=testing%20Flask%20apps
```

| Parameter | Required | Notes |
| --- | --- | --- |
| `course` | yes | Course code or title, matched like `/api/students/search` |
| `need` | yes | Free text, 1 to 300 characters after trimming |
| `program`, `year`, `skills`, `advice_topics` | no | Case-insensitive substring filters, as in search |
| `available` | no | Defaults to `true`; `false` includes advisors who are not accepting requests |

Authentication: the session cookie for a signed-in student. The viewer is never
returned as a match.

| Status | When |
| --- | --- |
| 200 | Results, possibly an empty `students` list |
| 400 | `course` or `need` is missing, or `need` is longer than 300 characters; body `{"error": "..."}` |
| 401 | Not signed in; body `{"error": "Sign in to get recommendations."}` |

Up to 50 results are returned, best first. Ties break by ascending student ID.
An embedding failure does not cause an error; the server ranks by keywords only.

Response shape (abridged; the numbers follow the formula below):

```json
{
  "students": [
    {
      "id": 12,
      "name": "Advisor 012",
      "program": "Computer Science",
      "year": 3,
      "advice_topics": "testing Flask apps; pytest fixtures",
      "review_summary": {"average_rating": 4.2, "review_count": 6},
      "match": {
        "score": 0.7477,
        "breakdown": {
          "topic_fit": 0.8, "keyword": 0.5, "semantic": 0.875, "rating": 0.7417,
          "qa_help": 0.6131, "capacity": 0.5, "quality": 0.9347
        },
        "reasons": [
          {"type": "semantic", "field": "advice_topics"},
          {"type": "keyword", "terms": ["testing", "Flask"]},
          {"type": "rating", "average": 4.2, "count": 6},
          {"type": "qa_help", "count": 2},
          {"type": "capacity", "free": 2}
        ]
      }
    }
  ],
  "course_codes": ["CSC510"]
}
```

Reason types: `keyword` (need words found in the profile), `semantic` (the
profile field with the strongest similarity, when it is at least 0.6),
`rating`, `qa_help`, and `capacity` (`free` is `null` when there is no limit).
The frontend shows at most three, largest contribution first.

`/api/students/search` is unchanged.

## How ranking works

Eligibility uses the same rules as search, implemented once in
`backend/common/advisor_sql.py`: the advisor is a registered student who
completed the course (matched by course key, or by catalog title for unknown
codes), the advisor is not blocked in either direction with the viewer, and
the viewer is excluded.

Each eligible advisor gets these signals:

- **Keyword rank.** Postgres full-text search over a weighted `tsvector` on
  `students`: `advice_topics` (A), `skills` (B), `interests` (C), `bio` (D). The
  need becomes an OR query (`plainto_tsquery`, English stopwords removed) scored
  with `ts_rank` and normalized into 0 to 1. Up to ten distinct need words of
  three or more letters that appear in the profile are reported as reasons.
  There is no synonym list.
- **Semantic similarity.** The need is embedded with `query_embed`; each phrase
  of each stored profile field is embedded with `passage_embed` (see Storage).
  Model: `BAAI/bge-small-en-v1.5` (384 dimensions) through fastembed. A field's
  similarity is the highest cosine similarity from pgvector between the need and
  any of that field's phrases, clamped to 0 to 1. The semantic score is that
  similarity averaged over the fields the advisor has, using the field weights
  below.
- **Rating.** Average of helpfulness ratings on completed advice, smoothed
  toward 3.5 as if three extra reviews existed, then scaled from 1–5 to 0–1.
  An advisor with no reviews gets the neutral value 0.625.
- **Q&A help.** Helpful answers the advisor wrote in this course on questions
  they did not ask. Scored as `min(1, log(1 + k) / log 6)`, so five answers reach 1.
- **Capacity.** Share of open slots left: 1 when the advisor has no limit, 0
  when the limit is 0, otherwise free slots divided by the limit. Open
  requests are accepted requests plus unexpired pending ones.

Scoring is topic-gated: topic fit decides whether an advisor matches at all, and
quality reorders the advisors who match. Default weights are in `DEFAULT_WEIGHTS`
(`backend/matching/scoring.py`):

```
similarity_f = max over the phrases p of field f of cos(need, p), clamped to 0..1
semantic     = sum(w_f * similarity_f) / sum(w_f)   over fields f the advisor has
topic_fit    = 0.2 * keyword + 0.8 * semantic
               (topic_fit = keyword when the advisor has no vectors or the need has no embedding)
quality      = 0.80 + 0.12 * rating + 0.05 * qa_help + 0.03 * capacity
score        = topic_fit * quality
```

The four quality weights (the 0.80 floor and the three multipliers) must sum to 1,
so quality lies between 0.80 and 1. An advisor whose `topic_fit` is 0 scores 0
however well rated they are. `alpha` (0.2 here) sets how much keyword overlap
counts against semantic similarity inside `topic_fit`.

Field weights: `advice_topics` 0.40, `skills` 0.30, `interests` 0.15, `bio` 0.15.
The semantic reason threshold is 0.6. Scores lie between 0 and 1.

The defaults were tuned on eval seed 1 only; seed 2 is the held-out report
(see [eval/README.md](../eval/README.md)).

`rank()` sorts by score, then by student ID. Scoring is pure Python with no
database access, so it is unit-tested directly.

## Storage and lifecycle

- **Keyword index.** Migration `20261126000100_advisor_matching.sql` adds the
  generated `students.search_vector` column with a GIN index.
- **Vectors.** Table `profile_embeddings` holds one row per student, field and
  phrase. Fields are `advice_topics`, `skills`, `interests` and `bio`. Each row
  has `embedding vector(384)`, `model`, `source_hash`, `attempts`,
  `last_error_at` and `updated_at`. `chunk` is the 0-based index of the phrase
  within its field, and the primary key is `(student_id, field, chunk)`. Empty
  fields have no rows. RLS is on and browser roles have no access; only the Flask
  service role reads and writes it.
- **Phrases.** `split_phrases` in `backend/matching/chunking.py` splits a field
  at `;`, `,`, `.`, newlines and bullet characters, drops duplicates, and keeps at
  most 20 phrases of 200 characters each. Text with no phrases (only punctuation)
  is embedded whole as one chunk. Each phrase is one embedding row.
- **Hash.** `source_hash` is the SHA-256 of the model name and the whole field
  text, and every chunk of a field stores that hash. A field is re-embedded only
  when its hash changes, so unchanged fields are skipped. Chunks whose hashes
  differ count as stale.
- **On save.** Registration and profile updates call `profile_vectors.refresh`
  after their normal writes, in the same transaction and inside a savepoint.
  Phrases from all changed fields are embedded in one call. If the model fails, the error is logged,
  the row is stored with a `NULL` embedding and `attempts` incremented, and the
  save still succeeds. If the database rejects the embedding write, only the
  savepoint is rolled back. Saving a profile never fails because of embedding.
- **Retry.** A field is pending when it has no rows, any of its rows has a hash
  that no longer matches the current text, or its embedding is `NULL` with fewer than **5**
  failed attempts. Emptied fields are deleted. A field that reaches five
  attempts stays `NULL` and is ignored by ranking until its text changes.
- **Sweeper.** `python backend/embed_profiles.py` embeds up to 100 pending
  students per run and prints how many succeeded. Schedule it like
  `backend/expire_requests.py` (for example every 15 minutes) and run it again
  when a large backlog remains. `python backend/app.py` also starts one sweep in
  a background thread when the development server starts.
- **Model cache.** Set `FASTEMBED_CACHE_PATH` to choose where the model is
  stored. The first embedding downloads the model, about 130 MB; later runs
  load it from the cache. Loading happens on first use, not at import time.

## Setup

1. Apply migrations with the database URL in `SUPABASE_DB_URL`:

   ```sh
   python backend/migrate.py
   ```

   The migration enables the `vector` extension in the `extensions` schema
   (Supabase convention). On a plain PostgreSQL server, the database must allow
   `CREATE EXTENSION vector` and the pgvector package must be installed.

2. Install the backend requirements, which now include `fastembed`:

   ```sh
   pip install -r backend/requirements.txt
   ```

3. Backfill profiles that existed before this feature. This needs the model
   download once:

   ```sh
   python backend/embed_profiles.py
   ```

   Run it again until it embeds zero profiles. Profiles without vectors still rank
   by keyword, so this step is not required for the feature to work.

### Local backend tests

Tests run against a PostgreSQL database that has pgvector. A local container:

```sh
docker run -d --name packconnect-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg17
docker exec packconnect-pg createdb -U postgres packconnect_test
TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/packconnect_test?sslmode=disable' \
  python -m unittest discover -s backend -p 'test_*.py' -v
```

Tests use `backend/fake_embedder.py`, a deterministic hash-based embedder, so
they never download the model. To run the one test that loads the real model
(it downloads the model if it is not cached):

```sh
cd backend && RUN_REAL_EMBEDDER=1 python -m unittest test_matching_scoring -v
```

The M0 evaluation is documented in [eval/README.md](../eval/README.md).

## Code map

| File | Responsibility |
| --- | --- |
| `backend/common/advisor_sql.py` | Eligibility conditions and hard filters shared by search and recommendations. Pure SQL building. |
| `backend/matching/embedder.py` | `Embedder` protocol; `FastEmbedEmbedder` (lazy model load, cache path); `vector_literal` for pgvector. |
| `backend/matching/chunking.py` | `split_phrases`: splits a profile field into the phrases that are embedded one by one. |
| `backend/matching/profile_vectors.py` | Field list, source hashing, per-phrase storage on save, `refresh`, `pending_student_ids` and `sweep` for retries. |
| `backend/matching/signals.py` | The one candidate query: keyword rank, matched need words, per-field similarity (the best phrase per field), review and Q&A counts, workload. Returns `Candidate` objects. |
| `backend/matching/scoring.py` | `Weights`, the topic-gated formula, `score`, `rank`, reason building. No database access. |
| `backend/matching/routes.py` | `GET /api/students/recommendations`: sign-in, validation, query embedding cache, ranking, JSON. |
| `backend/embed_profiles.py` | Command-line sweeper for pending profile embeddings. |
| `backend/fake_embedder.py` | Test-only embedder with the same interface. |
| `supabase/migrations/20261126000100_advisor_matching.sql` | `vector` extension, `search_vector`, `profile_embeddings`, grants. |
| `frontend/src/matchReasons.js` | Turns reason objects into chip labels. |
| `frontend/src/MatchReasons.jsx` | Best-match badge and chip list on result cards. |

Changing the ranking means editing `Weights` in `scoring.py`: `alpha`, the four
quality weights (`quality_floor`, `rating`, `qa_help`, `capacity`; each must be
non-negative and they must sum to 1, or the constructor raises), or `fields`.
Rerun `test_matching_scoring.py`, then the M0 evaluation. Tune on seed 1 only and
report on seed 2. Retuning on the reporting seed would make its result optimistic.

Adding a profile field touches more than weights. The field needs a `students`
column, the `search_vector` expression and the `profile_embeddings.field` check
constraint updated in a new migration, and an entry in `Weights.fields` (which
`profile_vectors.FIELDS` reads). The sweeper SQL also refers to the columns by
name, so test it with a pending backlog.

## Limitations

- **Self-reported profiles.** Advisors write their own topics and bio. Matching
  can only rank what they wrote, and the reasons reflect that text.
- **English only.** Full-text search uses the `english` configuration, and the
  embedding model is English. Other languages match poorly.
- **No synonym map.** Keyword matching finds shared words. The semantic signal
  covers paraphrases, but only as well as the model does.
- **Limited signal.** Few reviews or Q&A answers leave the prior values in place.
  Rating, Q&A and capacity together move quality only between 0.80 and 1, so new
  advisors rank mostly on topic fit.
- **Latency.** The model runs on the CPU in the Flask process. The first query
  after startup pays the model load. Query embeddings are cached in memory for
  repeated needs, but each new need costs one model call.
- **No pagination.** Recommendations return the top 50 matches.
- **Weights are hand-set.** The `alpha` and quality weights were tuned on
  synthetic seed 1 data; seed 2 is the held-out report. See the M0 evaluation,
  including its spiral review, for what that does and does not show.
