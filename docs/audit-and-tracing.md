# Audit log, error records and tracing (N-11)

Brief sections 22, 23 and 27. Any question can be reconstructed end to end from the
database and its LangSmith trace.

Code: `app/agent/nodes/n11_audit.py`, `app/agent/audit.py` (`DatabaseAuditSink`),
`app/core/masking.py`.

## What N-11 writes (one transaction per run)

| Table | Rows | Section 23 fields |
| --- | --- | --- |
| `questions` | the question (created if the caller did not) | correlation ID, conversation, user, role, region, question text, resolved date range, assumptions, final status, completion time |
| `agent_runs` | one per run (`run_number` counts re-runs) | correlation ID, graph version, prompt versions (`answer@v1,intent@v2,...`), semantic layer version, model, input/output tokens, estimated cost, total latency, LangSmith reference, final status |
| `agent_steps` | one per node, N-11 included | node, from/to status, input and output summaries, start, duration (latency per node), error code |
| `generated_queries` | every SQL the LLM produced (initial and repairs) | SQL text, tables and metrics used, confidence, date range, verified examples used (Step 20) |
| `query_executions` | every execution | role scope (`analytics_ro/<view schema>`), region, status (success, db_error, timeout), rows returned, result size in bytes, latency, error |
| `blocked_queries` | the block, if any | stage (input guardrail, context, SQL validation), reason code, plain-language reason, the blocked SQL (linked) |
| `clarifications` | each clarifying question | question, options, the user's reply, times |
| `audit_log` | one `question_<status>` event | correlation ID, user, status, block reason, row count, role, region |
| `agent_errors` | for `FAILED` (or any error) | correlation ID, question, run, node, error code, retryable flag, message, and the **logged input** for a re-run (request, clarification answers, thread) |

Feedback (helpful / not helpful) is added in Step 20; logins and admin actions in
Step 17.

Every related row carries the correlation ID directly (`questions`, `agent_runs`,
`audit_log`, `agent_errors`) or through its run (`agent_steps`, `generated_queries`,
`query_executions`, `blocked_queries`).

## Never break the answer

N-11 catches every exception from the audit write, logs it with the correlation ID
(`audit write failed for correlation_id=...`) and sets `audit_ok = false` in the state. The
user still gets the answer.

## Tracing

The correlation ID is also the **LangSmith root run ID** (`run_id` in the graph config),
with metadata `correlation_id`, `role`, `region` and `graph_version`, so a question in the
database leads directly to its trace. `agent_runs.langsmith_trace_url` stores
`langsmith:<project>/runs/<correlation id>`. Tracing itself is switched on only by the
`LANGSMITH_*` environment variables (Step 10).

## Masking (section 27)

`mask_text` replaces e-mail addresses, phone numbers, card and bank-account numbers,
IBANs, API keys, bearer tokens and JWTs, `password=...`-style secrets and passwords in
connection strings with markers such as `[MASKED_EMAIL]`. Dates, amounts, order numbers
and ranges are kept.

Masking happens:
1. **Before the question enters the graph** (`Agent.run`, `Agent.resume`,
   `ConversationService`), so the LLM, the LangSmith trace, the checkpoint and the app
   tables never see the raw value.
2. **On the rows shown to the answer LLM** (for example a customer phone number a sales
   manager may see in the table is masked in the prompt).
3. **On everything the audit writes**: step summaries, SQL, error messages, block reasons,
   clarifications, audit details and the re-run snapshot.

## asyncpg and `set_config`

`set_config` is revoked from every role so a query cannot change its own role or region
(docs/access-control.md). asyncpg calls `set_config('jit', ...)` before introspecting some
types (for example `uuid[]` or `array_agg` results). The seed therefore sets `jit = off`
for both login roles, and `app/db/session.py` tells asyncpg that JIT is off so it skips
that call. `set_config` stays revoked.

## Tests

- `tests/integration/test_audit_db.py` (real database): ANSWERED, BLOCKED, REJECTED and
  FAILED questions each produce complete, linked rows; clarifications are stored; the
  correlation ID links every related row; an e-mail address and a phone number in the
  question never appear in plain text in any audit table.
- `tests/unit/test_audit.py`: masking rules, a failing audit write still answers, raw
  values never reach the LLM, attempt and execution records, the re-run snapshot.
