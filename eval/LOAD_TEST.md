# Load test

Run 2026-11-08 16:02 UTC with `python -m eval.load_test` (brief §28). Real API,
database, validator, executor, audit and checkpoints; the model is a stand-in
that waits 1.0 s per call (3 calls per question), so the numbers
show our own stack plus a typical model wait, without spending credits.

| Measure | Value |
| --- | --- |
| Concurrent users | 20 |
| Questions | 60 (3 per user) |
| Outcomes | ANSWERED 60 |
| HTTP errors | 0 |
| Latency p50 / p95 / max | 5.58 s / 7.09 s / 7.17 s |
| Wall time | 17.25 s |
| Throughput | 208.6 questions per minute |

The first runs found three problems under load, fixed in Step 26
(docs/decisions-log.md): parallel first use of the lookup pools (7 of 60 failed, 30 s
waits), driver UUIDs the checkpoint could not restore, and checkpoint saves after every
node behind the Postgres saver's single lock (p50 27 s; 44 questions per minute).
