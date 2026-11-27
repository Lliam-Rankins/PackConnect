# M0 results

Reporting data: seed 2, 120 requests, 180 advisors, model `BAAI/bge-small-en-v1.5`, available advisors only.

| Arm | Top-3 suitability | MRR |
|---|---|---|
| Course only (sorted by name, today's search) | 21.7% | 0.178 |
| Keyword only (alpha = 1) | 22.5% | 0.215 |
| Semantic only (alpha = 0, informational) | 69.2% | 0.579 |
| Hybrid (default weights) | 68.3% | 0.575 |

## Claims

- **FAIL** Inherited: hybrid >= 80% top-3 and >= 20 points above course-only (hybrid 68.3%, course-only 21.7%, gain +46.7 points)
- **PASS** New: hybrid >= 15 points above keyword-only (hybrid 68.3%, keyword-only 22.5%, gain +45.8 points)

## Alpha sweep on tuning data (seed 1, information only)

| alpha | Top-3 suitability | MRR |
|---|---|---|
| 0.0 | 55.8% | 0.488 |
| 0.2 | 57.5% | 0.486 |
| 0.4 | 56.7% | 0.470 |
| 0.6 | 52.5% | 0.439 |
| 0.8 | 49.2% | 0.412 |
| 1.0 | 30.0% | 0.279 |
