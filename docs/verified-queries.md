# Verified query library and feedback loop

Brief §16. Verified examples are questions with SQL that a person checked. The agent uses
the most similar ones as few-shot guidance; feedback from users feeds the admin review.

## The loop

```
user rates an answer ──> not helpful? ──> Admin › Review queue
                                             ├─ Verify or correct the SQL ──> verified library ──> N-05 ──> N-06 (few-shot)
                                             └─ Make eval case ──────────────> eval_cases (dataset "review-cases")
blocked queries and failures also appear in the queue (verify a corrected query, or re-run a failure)
```

## Library

- Table `app.verified_queries`: question, SQL, plain-language description, tables, metrics,
  allowed roles, author (`verified_by`, `verified_at`), source question, version, enabled.
- **Versioned.** A correction is a new version in the same lineage (`lineage_id`); the
  older versions stay for history and are disabled. Only one version per lineage is enabled.
- **Can be disabled.** A disabled example is never offered to the agent. Enabling it again
  re-checks its SQL against today's semantic layer and disables the other versions.
- **Seed.** `config/verified_queries.yaml` holds 18 examples. The seed adds version 1 of
  each lineage that does not exist yet (stable IDs: `uuid5(namespace, key)`), so admin
  corrections and disabled examples survive a re-seed.

## Saving rules (`app/services/verified_library.py`)

- The SQL must pass the Step 9 validator (`validate`) **for every allowed role**; the
  tables it uses are taken from the validator, not typed by hand.
- Allowed roles are business roles only and never wider than the roles of the metrics the
  SQL uses (for example, `revenue` is not an operations metric).
- The expected SQL of a new evaluation case is validated for the asking user's role.
- Every action is audited: `verified_query_created`, `verified_query_corrected`,
  `verified_query_enabled`, `verified_query_disabled`, `eval_case_created`.

## Retrieval (N-05) and use (N-06)

1. N-05 loads the enabled examples from the database for every question (changes apply
   at once) and keeps those that list the user's role.
2. It scores them by keyword similarity with the question (the standalone version for
   follow-ups): cosine similarity of the keyword sets, after the same tokenising as the
   semantic retriever and a small stop-word list.
3. Examples above `min_score` are re-validated for the user's role against the current
   semantic layer; the best `max_examples` are kept (`config/agent.yaml`,
   `verified_examples`).
4. N-06 adds them to the SQL prompt (`sql_generation` v2) as "Verified examples", with the
   instruction to follow their patterns but use this question's own period and filters.
5. The IDs of the examples used are stored with each generated query
   (`generated_queries.verified_query_ids`) and visible in the audit.

Loading problems are logged and the question continues without examples. Verified
examples never bypass anything: the generated SQL is validated by N-07 and executed by
N-08 under the user's role and region as usual.

**Why keyword similarity, not embeddings.** The library is small (tens of examples) and
the questions are short and domain-specific, so token overlap finds the right example;
it is deterministic, explainable in the review screen and needs no embedding model,
extra service or vector index. Embeddings can replace `similarity()` later without
changing the rest of the flow.

## Admin endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /admin/review?kind=` | Not-helpful answers (open), blocked queries and open failures, newest first |
| `GET /admin/verified-queries?is_active=` | The library, with every version |
| `POST /admin/verified-queries` | Verify a question and its SQL, or correct one (`lineage_id` = new version) |
| `PATCH /admin/verified-queries/{id}` | Enable or disable an example |
| `POST /admin/feedback/{id}/eval-case` | Turn a not-helpful answer into an evaluation case |

Feedback (`POST /feedback`) is linked to the question and to its latest agent run
(`feedback.run_id`). Its `review_status` moves from `open` to `verified` (when its question
is verified) or `converted` (when it becomes an evaluation case).

## Evaluation

Runs record `verified_examples_enabled`; the agent config switch
`verified_examples.enabled` turns retrieval off, so the evaluation (Step 22) can compare
accuracy with and without examples.
