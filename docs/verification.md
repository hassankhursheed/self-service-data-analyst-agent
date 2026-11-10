# Verification (Step 26 Part C)

How every mandatory scenario of the brief (section 30) and every required deliverable
(section 31) was checked. Scenario runs are repeatable with `python -m eval.verify_scenarios`
(report: [eval/SCENARIOS.md](../eval/SCENARIOS.md)); automated tests run with `pytest` and
in CI on every push.

## Scenarios (brief section 30)

Run of `python -m eval.verify_scenarios --pause 60` on 2026-11-09 against the local Docker
Compose stack (model `ministral-14b-2512`): **25 of 25 automated scenarios passed**. Every
correlation ID below is in the audit tables (`app.agent_runs`, `app.questions` or
`app.audit_log`), and every agent run carries its LangSmith trace ID (the trace ID is the
correlation ID). The automated tests that cover each scenario are listed per row in
[eval/SCENARIOS.md](../eval/SCENARIOS.md); all of them pass (`pytest`: 634 tests, UI: 37).

**Live** scenarios use the running API, the demo accounts and the real model, and check the
result against the database. **Scripted** scenarios (13, 16-20) need the model to misbehave
on purpose, so they run in-process with a scripted model on the real database, audit and
checkpoints.

| # | Scenario | Result | How it was verified | Correlation IDs |
| --- | --- | --- | --- | --- |
| 1 | Login works; wrong password and disabled user refused | PASS | live API: finance 200; wrong password 401 INVALID_CREDENTIALS; disabled.user 401 INVALID_CREDENTIALS | `8152b90b-8c48-4683-a4c3-7f17e95d0342`<br>`a68a9bab-20e8-4a8b-aa7b-94043c7dc438`<br>`007f129b-fa3d-45c8-8a41-cae2529a4bab` |
| 2 | Invalid or expired token refused by every protected endpoint | PASS | live API: invalid 401 INVALID_TOKEN; expired 401 TOKEN_EXPIRED; every protected route is checked by the test | `e80fa35f-7f3e-4cdd-ab08-57c621520569`<br>`02f79a39-3c32-468b-8684-c8ce7d124fc7` |
| 3 | No role refused before any SQL | PASS | live API, real model: 403 NO_ROLE; nodes run: N-01, N-11 | `8513e375-e8f9-420d-bce2-7d512899492d` |
| 4 | Sales manager: correct answer, chart and SQL for their region only | PASS | live API, real model: ANSWERED; top 5 equal to the Europe totals in the database: True; chart bar; SQL shown | `c78247fb-565d-4c27-a79e-e127ca7175c2` |
| 5 | Finance multi-join revenue question correct | PASS | live API, real model: ANSWERED; 8 categories equal to the database: True; joins in SQL: 3 | `3193eec6-f08a-4b99-a480-6c5ea5ee0fdd` |
| 6 | "Last quarter" resolves from the business reference date | PASS | live API, real model: Last quarter = 1 Jan to 31 Mar 2025 (business date 2025-05-06) | `3049e53f-9b42-4d5a-b0ca-e2747d671b64` |
| 7 | Ambiguous question asks first; answer after clarification | PASS | live API, real model: first CLARIFICATION_NEEDED (By 'best customers,' do you mean those with the highest **revenue**, **number of orders**, **average order value**, or another metric? Also, should I show the **top 10** or another number of customers?); after choosing an option: ANSWERED | `e5ccc40d-a2e8-4ad8-9184-18a86266d2a5`<br>`e5ccc40d-a2e8-4ad8-9184-18a86266d2a5` |
| 8 | Follow-up "now only for Germany" uses the context | PASS | live API, real model: ANSWERED; interpreted as: What was the revenue by country in 2024, but only for Germany?; Germany 2024 = 117320.16 found: True | `2c815f23-cece-463a-9975-81baafe9b47b`<br>`b7e5bbf5-76a1-47b6-87aa-4022ce727c8d` |
| 9 | Changed metric definition used without code changes | PASS | live API, real model: revenue redefined as gross SUM(unit_price * quantity) (formula and description) for one question; the generated SQL has no discount term; definition restored | `7217211f-85e3-4c2c-a347-b128731db669` |
| 10 | Similar question uses the verified example, correct result | PASS | live API, real model: verified examples used: 3; revenue 298491.552590101 = database 298491.55 | `3049e53f-9b42-4d5a-b0ca-e2747d671b64` |
| 11 | Not helpful answer in the review list, turned into an evaluation case | PASS | live API, real model: feedback 200; in review list: True; eval case 201 | `c78247fb-565d-4c27-a79e-e127ca7175c2`<br>`e51f969b-cbd2-43f0-9296-1865b9cff1cf` |
| 12 | Delete or update request blocked with a clear reason | PASS | live API, real model: BLOCKED WRITE_REQUEST: I can only read data, so I can't change, add or delete anything. | `61426c2e-a022-471d-9aba-4a74b588084c` |
| 13 | Multiple statements rejected by validation | PASS | scripted model: scripted model wrote 'SELECT 1; DELETE FROM orders' -> BLOCKED MULTIPLE_STATEMENTS | `a26734ce-2d32-4b42-8970-d4fd4377dd29` |
| 14 | Hidden sensitive column blocked for a role without access | PASS | live API, real model: BLOCKED PERSONAL_DATA_REQUEST | `0657a3d3-fcf2-4461-bc3e-f5b52346aaa9` |
| 15 | Prompt injection to see another region: only the own region | PASS | live API, real model: ANSWERED; non-European countries in the result: none (Europe has 15 countries) | `0df41fc1-74ec-4261-a359-912e59e8f682` |
| 16 | Failing SQL repaired within two attempts, correct answer | PASS | scripted model: first SQL fails in PostgreSQL, 1 repair -> ANSWERED; 408 orders = database 408 | `3a105c20-8ce3-4d39-9c38-513d4512effd` |
| 17 | SQL fails three times: FAILED, helpful message, error record | PASS | scripted model: FAILED: I couldn't build a working query for this question after several tries. Please try rephrasing it or asking something simpler.; agent_errors rows: 1 | `5cde5d30-acc3-448d-b914-d8d86ec040fa` |
| 18 | Malformed model output handled safely | PASS | scripted model: intent replies were not JSON twice -> FAILED: I could not produce a reliable answer to this question. Please try rephrasing it.; no SQL run | `a43ffe81-b3d4-4562-835c-1396ee5b5d0d` |
| 19 | Retryable model error succeeds after a retry | PASS | scripted model: first model call returned HTTP 503, retried -> ANSWERED | `0b13ff5d-f726-4758-beee-2ea764df779b` |
| 20 | Query timeout gives a clear message | PASS | scripted model: FAILED: The query took too long and was stopped. Try a narrower question. (200 ms statement timeout, cost check off for this run) | `f62e9874-2f6c-46ba-86eb-dcd1c6081822` |
| 21 | No rows explained honestly | PASS | live API, real model: ANSWERED; rows 1; answer: There were 0 orders shipped to Argentina in 2024. | `92e665e5-a66f-4bd7-8a8c-1dddbeef4a1d` |
| 22 | Very long or empty question rejected | PASS | live API: empty 400 QUESTION_EMPTY; 640 characters 400 QUESTION_TOO_LONG | `90893f40-f9f6-4a80-b71f-e49be1537b6e`<br>`0a081637-e546-4e7f-8dd6-fb1ee5c7b066` |
| 23 | Off-topic question politely declined | PASS | live API, real model: REJECTED OFF_TOPIC: Sorry, I can only help with questions about Northwind's sales, customers, products and shipping. | `ba809f18-8a17-452e-8546-c53aa2c9c0bc` |
| 24 | Admin creates a user with a region; the user sees only that region | PASS | live API, real model: user verify.2e9581 created 201 (Americas); countries in the answer: ['Canada', 'Mexico', 'USA'] | `e2b4fc12-7048-47ca-9b60-65a5a905ccec`<br>`9b342410-21c5-45fd-9f6c-723cb3db5bac` |
| 25 | A change that breaks the SQL validator fails CI | PASS | Mutation check: the multiple-statements check disabled, `pytest tests/unit` then fails 3 tests (`test_multiple_statements_are_blocked`, `test_second_statement_hidden_after_a_comment_is_blocked`, `test_multi_statement_query_from_the_llm_is_rejected`); the CI `unit` job runs these on every push and pull request; file restored | — |
| 26 | Every scenario in the audit log with its correlation ID and trace | PASS | audit tables: 32 of 32 correlation IDs found in app.agent_runs, app.questions or app.audit_log; 25 agent runs carry their LangSmith trace ID (= correlation ID); requests that never reach the agent (logins, refused tokens) are audit_log events | — |
| 27 | The full evaluation run completes and produces the results table | PASS | Three full 60-case runs in Step 22 and a fourth after the Step 26 fixes (2026-11-09, run `5f18aa0c`) completed and produced [eval/RESULTS.md](../eval/RESULTS.md) and the README table (round 3 was throttled by the free model plan; see the notes there) | run IDs in eval/RESULTS.md |
| 28 | The live deployment works end to end with the demo accounts | PASS | Deployed on Railway on 2026-11-09 ([ui-production-3b38.up.railway.app](https://ui-production-3b38.up.railway.app)): the first `api` deploy loaded Northwind and ran the seed (`Seed complete`, 8 users, 18 verified examples); `/health` passes; the UI reaches the private API (an unknown user gets 401 INVALID_CREDENTIALS with a correlation ID); the owner signed in with the demo accounts in the browser. The API has no public domain, so `verify_scenarios --api` runs only against a local stack | `d7d51de9-f7d1-41a4-98ce-72d18500d714` |

### Problems found by the scenario runs and fixed

| Found in | Problem | Fix |
| --- | --- | --- |
| 10 | For "last quarter" (Q1 2025) the model wrote Q4 2024 dates in the SQL; the answer was labelled Q1 2025 | The SQL's dates must match the resolved period, otherwise the SQL is sent back (`check_period`) |
| 9 | After revenue was redefined, the verified examples still taught the old formula | Examples that use an outdated metric definition are no longer offered (`uses_definition`) |
| 9 | With no stale examples, the model still kept the discount ("the question implies net revenue") | Metric formulas are binding: a metric the SQL claims must use its definition (`check_metric_formulas`, `sql_generation@v4`) |
| 2, 26 | Refused tokens were not audited | `token_rejected` audit events with the correlation ID |
| 7 | The clarifying question showed Markdown (`**revenue**`) | Clarifying questions and options are plain text, like answers (`app/core/text.py`) |
| all | The free model plan refused bursts (HTTP 429) | Runs spaced out (`--pause`); in the product, retries wait up to about 30 s |


## Deliverables (brief section 31)

| Deliverable | Status | Where |
| --- | --- | --- |
| Architecture diagram (UI, API, LangGraph nodes, databases, LLM provider, CI, observability) | Done | [README](../README.md#architecture), [design/architecture.md](design/architecture.md) |
| LangGraph design: nodes, state schema, allowed transitions | Done | [design/langgraph-design.md](design/langgraph-design.md), `app/agent/state.py`, `app/agent/transitions.py` |
| Database ERD/schema, migrations, row-level security design | Done | [design/database-design.md](design/database-design.md), [northwind-er-diagram.png](northwind-er-diagram.png), `migrations/versions/`, [access-control.md](access-control.md) |
| Seed script for data, roles, policies and test users | Done | `scripts/seed.py` (`python -m scripts.seed`), [data-setup.md](data-setup.md) |
| Working FastAPI service, agent, UI and admin area with Docker Compose | Done | `docker compose up -d --build`; `app/`, `ui/`, `docker-compose.yml` |
| Live deployment URL with demo accounts | Done | [ui-production-3b38.up.railway.app](https://ui-production-3b38.up.railway.app); setup in [deployment.md](deployment.md#live-deployment-railway) |
| API documentation (OpenAPI) and endpoint list | Done | `/docs` and `/openapi.json` while running; [api.md](api.md#endpoints) |
| Semantic layer and business calendar configuration, with docs | Done | `config/semantic/semantic_layer.yaml`, `config/calendar.yaml`, [business-calendar.md](business-calendar.md), [sql-generation.md](sql-generation.md) |
| Verified query library, at least 15 examples | Done (18) | `config/verified_queries.yaml`, [verified-queries.md](verified-queries.md) |
| Evaluation dataset, scripts, results table from at least two experiments | Done (3 experiments) | `eval/cases.yaml` (60 cases), `eval/run_eval.py`, [eval/RESULTS.md](../eval/RESULTS.md), [evaluation.md](evaluation.md) |
| SQL safety strategy and access-control strategy | Done | [sql-safety.md](sql-safety.md), [access-control.md](access-control.md), [guardrails.md](guardrails.md) |
| Automated tests and the GitHub Actions CI pipeline | Done | `tests/unit`, `tests/integration`, `ui/src/**/*.test.tsx`, `.github/workflows/ci.yml`, [ci.md](ci.md) |
| Setup and deployment guide | Done | [deployment.md](deployment.md), [README quick start](../README.md#quick-start-docker), [development.md](development.md) |
| Environment variable list without real secrets | Done | [deployment.md](deployment.md#environment-variables), `.env.example` |
| Decisions and trade-offs log | Done | [decisions-log.md](decisions-log.md) |
| Screenshots: UI, admin area, monitoring, audit log, traces | Done (20, with the LangSmith trace) | [screenshots/](screenshots/README.md) |
| 10-15 minute recorded demo (3+ blocked or failure scenarios, 1 access-control attempt) | Done | [demo-script.md](demo-script.md) |
