# M0 evaluation: ranked advisor matching

M0 asks whether ranked advisor matching finds suitable advisors better than
today's course-only search, and whether the hybrid ranker beats keyword-only
ranking. The data is synthetic, generated from hidden labels, so results show how
the ranker behaves on that data. They do not show real-world effectiveness.

## Hypotheses

| Claim | Passes when |
| --- | --- |
| Inherited: hybrid finds suitable advisors | Hybrid top-3 suitability is at least 80%, and at least 20 points above course-only |
| New: hybrid beats keyword-only | Hybrid top-3 suitability is at least 15 points above keyword-only |

**Top-3 suitability** is the share of requests where the first suitable advisor
appears in the top three results. MRR (mean reciprocal rank of the first
suitable advisor) is reported alongside it.

Arms:

| Arm | Ranking |
| --- | --- |
| `course_only` | Eligible advisors sorted by name, as the app does today |
| `keyword_only` | Full-text rank only (alpha = 1) |
| `semantic_only` | Embedding similarity only (alpha = 0); reported for information, not a claim |
| `hybrid` | Default weights from `backend/matching/scoring.py` |

All arms use the production signal query and scoring code. Only the arm's
settings change.

## How the data is generated

`eval/generate.py` is standard-library Python. The same seed and
`eval/concepts.json` always produce the same output.

- **Concepts.** `concepts.json` lists 25 expertise concepts. Each has several
  *profile phrases* (used in advisors' profiles) and several *request phrases*
  (used in students' needs). The two lists do not overlap, so a request rarely
  repeats an advisor's wording.
- **Advisors (180).** Each advisor completed one to three of six courses and
  holds one to three concepts. For each concept, phrases go into
  `advice_topics` and `skills`, or, with 20% probability, only into `bio`. Bio
  sentences and interests come from filler lists. Some advisors have no
  capacity limit; others have a limit of one to six with a random number of
  open requests.
- **Requests (120).** Each request picks a course and a target concept, and
  with 30% probability adds a secondary concept phrase. A request is kept only if
  at least one advisor is suitable and at least eight advisors completed the
  course.
- **Hidden labels.** Each advisor has a hidden quality value in 0 to 1 and the
  concepts they hold. These are never written into the profile text.
- **Suitability rule.** An advisor is suitable for a request when they completed
  the course, hold the target concept, have quality at least 0.5, and have free
  capacity. The generator records the secondary concept but does not use it for
  suitability.
- **Noisy evidence.** Ratings and Q&A help come from quality, not from labels
  directly. Each advisor has 0 to 8 reviews, with rating
  `round(clamp(1 + 4 × quality + N(0, 0.8), 1, 5))`. Helpful Q&A answers per
  completed course are drawn from a Poisson distribution with mean
  `(0.2 + 2 × quality) × U(0.5, 1.5)`.

The generator's own tests run from the `eval` directory:

```sh
cd eval && ../.venv/bin/python -m unittest test_generate -v
```

## Seeds

The datasets are not committed. `generate.py` recreates them from the seed and
`concepts.json`, locally (see below) and in CI. Changing the generator or
`concepts.json` changes the data, so rerun the eval afterwards.

- **Seed 1 (tuning):** `eval/data/seed1.json`. Used to explore alpha values and to set the quality weights.
- **Seed 2 (reporting):** `eval/data/seed2.json`. The default data for the
  reported claims.

Seed 1 is kept apart from the reporting seed. The `--tune` output lists top-3
scores for alpha values 0 to 1 for information only; it does not change the
reported arms, which use the default weights.

## Reproduce locally

You need a local PostgreSQL with pgvector, the backend requirements, and the
model download (about 130 MB on first run; set `FASTEMBED_CACHE_PATH` to choose
where it is cached).

```sh
docker run -d --name packconnect-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg17
docker exec packconnect-pg createdb -U postgres packconnect_test

export TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/packconnect_test?sslmode=disable'
python eval/generate.py --seed 1 --out eval/data/seed1.json
python eval/generate.py --seed 2 --out eval/data/seed2.json
python eval/run_m0.py --tune eval/data/seed1.json
```

`run_m0.py` requires `TEST_DATABASE_URL` to point at a local database. It loads
each dataset into a throwaway schema, which it drops afterwards, embeds profiles
with the real model, and ranks every request for each arm. It prints a markdown
report and writes it to `eval/results.md` (override with `--out`, or the reporting
dataset with `--data`). When `GITHUB_STEP_SUMMARY` is set, the same markdown is
appended to it.

The runner exits successfully whether or not the claims pass. Read the claims
table in the report to see the outcome.

## CI

The `m0-eval` job in `.github/workflows/ci.yml` runs on a pgvector PostgreSQL
service with the fastembed model cached. It runs the eval unit tests
(`python -m unittest discover -s eval -p "test_*.py"`), then
`python eval/run_m0.py --tune eval/data/seed1.json`. That reports the claims on
the default reporting dataset (seed 2) and the seed 1 alpha sweep, and appends the
report to the job summary. The job writes `eval/results.md` on the runner only;
CI does not commit it, so the checked-in file comes from a local run. The job
does not fail on a missed threshold. A failed hypothesis is a result, not a
broken build; the job fails only if the tests or the script crash.

## Results

The numbers for each run are in [`results.md`](results.md), which `run_m0.py`
writes. The spiral review below records the run history and quotes `results.md`
for the held-out run.

## Spiral review (Nov 26, 2026)

### Run 1: whole-field embeddings, additive score, alpha 0.4

Run 1 embedded each profile field as one vector and used an additive score with
alpha 0.4. It ran on seed 2, the reporting seed, with top-3 suitability:

| Arm | Top-3 suitability |
| --- | --- |
| Course only | 21.7% |
| Keyword only | 29.2% |
| Semantic only | 39.2% |
| Hybrid | 35.0% |

Both claims failed. The inherited claim needs at least 80%, and the new claim needs
hybrid at least 15 points above keyword-only (44.2% here).

**Diagnosis.** An oracle that ranks advisors by the hidden target concept reaches
97.5% top-3 on seed 2, so the data does not cap the score. On seed 1, for relevant
and other advisors, similarity differed by only about 0.56 against about 0.53. Whole-field
embeddings dilute several topics into one vector, and the additive rating and
capacity terms outweighed that small gap.

**Decision.** Persevere with two changes:

- topic-gated quality signals: an advisor's rating, Q&A and capacity only matter
  once topic fit is above zero;
- per-phrase embeddings: each field is split into phrases, and the field's
  similarity is the maximum over its phrases.

The weights were re-tuned on seed 1 only: alpha 0.2, quality weights 0.8 / 0.12 /
0.05 / 0.03. Seed-1 top-3 suitability rose from 33% to 57.5%.

### Run 2: held-out seed 2

Run 2 is the first run on seed 2 with the changed code and the seed 1 weights.
From `results.md`:

| Arm | Top-3 suitability | MRR |
| --- | --- | --- |
| Course only (sorted by name, today's search) | 21.7% | 0.178 |
| Keyword only (alpha = 1) | 22.5% | 0.215 |
| Semantic only (alpha = 0, informational) | 69.2% | 0.579 |
| Hybrid (default weights) | 68.3% | 0.575 |

- **FAIL** Inherited: hybrid >= 80% top-3 and >= 20 points above course-only (hybrid 68.3%, course-only 21.7%, gain +46.7 points)
- **PASS** New: hybrid >= 15 points above keyword-only (hybrid 68.3%, keyword-only 22.5%, gain +45.8 points)

The inherited claim fails on its 80% floor. Its requirement of at least 20 points
above course-only is met. The new claim passes. Semantic-only (69.2%) is slightly
above hybrid (68.3%) on this seed, within the uncertainty noted under Limitations.

### Remaining gap and next options

Hybrid is 11.7 points short of the 80% floor. These are options, not work done:

- **Larger embedding model.** In a topic-only test on seed 1, `bge-base` gave
  about 5 points more top-3 suitability than the current `bge-small`. That is the
  only evidence so far: it was a topic-only test, not the full ranker, and it was
  not run on seed 2.
- **Real pilot data.** Real profiles, requests and reviews would show whether the
  synthetic labels and phrase split generalize.

## Limitations

- **Synthetic data.** Profiles, requests, and reviews come from a generator, so
  the numbers depend on how well it resembles real students and advisors.
- **Labels are ours.** We chose the concepts, the phrase split, and the
  suitability rule. A different rule could give different results.
- **Ratings link to quality by assumption.** The generator assumes ratings and
  helpful answers track advisor quality. Real ratings may be biased or sparse.
- **Paraphrase split is designed.** Request and profile phrases are kept apart
  on purpose. Real students may share more or less wording with advisors.
- **Small scale.** Six courses, 180 advisors, and 120 requests give wide
  uncertainty on each percentage. Read differences of a few points with caution.
