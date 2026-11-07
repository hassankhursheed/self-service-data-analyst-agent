# Monitoring

Brief §26. The admin Monitoring page (`/admin/monitoring`) shows the operational health of
the agent for a chosen period: today, the last 7 or 30 days, or custom dates. It reads
`GET /admin/metrics?from=YYYY-MM-DD&to=YYYY-MM-DD` (admin only; default: today).

All numbers are SQL aggregations over the audit tables (`app/services/metrics.py`), run
with the application role. Periods are whole calendar days in the monitoring time zone
(`config/app.yaml`, `monitoring.time_zone`, default UTC), at most `max_period_days` (92).
Monitoring uses real time; the business reference date (6 May 2025) only applies to the
Northwind data.

## Metrics and where they come from

| Metric | Source | Definition |
| --- | --- | --- |
| Questions, per role | `questions` | Questions created in the period; role at the time of asking (`no_role` when none) |
| Outcomes | `questions.status` | answered, blocked, rejected, failed; `awaiting_clarification` (paused); `in_progress` (still running) |
| Blocked by reason | `blocked_queries` | Count per `reason_code` (guardrails, context and SQL validation) |
| Repair attempts | `generated_queries` (kind `repair`) | Repair queries in runs of the period |
| Repair success rate | `agent_runs` + `generated_queries` | Runs with at least one repair that ended ANSWERED / runs with at least one repair |
| Clarifications asked | `clarifications` | Clarifying questions recorded in the period |
| Latency average and p95 | `agent_runs.total_latency_ms` | Over runs started in the period; p95 is `percentile_cont(0.95)` |
| Tokens and estimated cost | `agent_runs` | Sum of input/output tokens and `estimated_cost_usd` |
| Helpful vs not helpful | `feedback` | Ratings given or changed in the period |
| Latest evaluation run | `eval_runs` | Most recent run overall (filled by Step 22) |
| Failed logins | `audit_log` (`login_failed`) | Failed sign-ins in the period |
| Daily series | `questions`, `agent_runs` | Outcomes and cost per day, for the chart |

A run is written when a question finishes (N-11), so a question waiting for a
clarification counts in the outcomes but not yet in latency, tokens or cost.

**p95.** `percentile_cont(0.95)` interpolates linearly between the two nearest values
(position `0.95 × (n − 1)` in the sorted list), the same as numpy's default. Example:
latencies 10, 20, …, 200 ms give position 18.05, so p95 = 190 + 0.05 × 10 = 190.5 ms.
`metrics.p95()` implements the same rule and is tested against the database.

## Indexes

Each query filters by time first. Indexes on `agent_runs(started_at)` and
`audit_log(event_type, occurred_at)` existed already; Step 21 adds `questions(created_at)`,
`blocked_queries(created_at)`, `clarifications(created_at)`, `feedback(updated_at)` and
`generated_queries(kind, run_id)` (migration `monitoring indexes`).

## The page

Metric cards (questions, answered rate, blocked or rejected rate, failure rate, p95 and
average latency, cost and tokens, repair success, clarifications, helpful ratings, failed
logins, latest evaluation run), a stacked bar chart of outcomes per day, and bar lists of
questions by role and blocked queries by reason.

Alerts (email or Slack above thresholds, stored in `alerts`) are a recommended extra for
Step 26.
